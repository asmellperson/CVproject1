"""
AiVision的总启动/停止调度中心
AIVision运行资源：
      Cameramanager：摄像头采集进程，负责rtsp采集和写共享内存
      InferenceRuntimeManager：模型推理进程，负责加载模型和推理任务队列
      Consumers：各检测功能的处理线程，负责从摄像头获取最新帧，调用模型推理，处理结果，写违规记录
      LogisticsChannelRuntime：汇总各摄像头快照，控制通道时段、异常事件并组织告警
      FrameReeaderRegistry：帧读取模块，负责从共享内存中读取最新帧，给Consumers和LogisticsChannelRuntime使用
      AlarmDispatcher：统一告警模块，负责喇叭、企业微信、违规记录、告警视频等告警相关的处理
      ViolationWriter：违规记录写入模块，负责违规截图，违规数据库记录，视频路径，状态
函数：
    生命周期          _init__()  start()  stop()
    consumer启动      _start_consumers()  _start_consumer()
    配置热更新        _handle_runtime_config_change() 以及摄像头辅助函数
    API查询接口       get_xxx()  runtime_status()
    异常监控          _monitor_consumer_threads()  _send_system_exception_alert()
    全局实例          init_orchestrator()  get_orchestrator()
"""
from __future__ import annotations
import datetime as dt
import threading
import time
from typing import Optional

from AiVision.core.logger import logger
from AiVision.core.cache import config_cache
from AiVision.core.db import ensure_schema_ready                        # 数据库检查
from AiVision.core.events import config_event_bus, ConfigChangeEvent         # 配置变化的时候，通知正在运行的模块更新
from AiVision.alarms.dispatcher import alarm_dispatcher                  # 统一告警处理
from AiVision.alarms.notifications.wechat import WeChatNotifier                        # 企业微信通知
from AiVision.runtime.process_cleanup import cleanup_aivision_residual_processes
from AiVision.core.settings import settings
from AiVision.core.system_config import system_config_service

from AiVision.features import all_specs                                     # 系统有那些检测功能
from AiVision.features._base.consumer import BaseFunctionConsumer           # 所有检测业务处理器的父类
from AiVision.features.recognize_face.records import RecognitionMediaReferences

from AiVision.cameras.runtime_manager import CameraRuntimeManager                  # 管理摄像头采集进程
from AiVision.cameras.frame_reader import frame_reader_registry     # 给主进程提供最新的视频帧
from AiVision.cameras.config_manager import camera_config_manager                 # 从数据库读/改摄像头配置
from AiVision.inference.runtime_manager import inference_runtime_manager           # 真正管理模型推理进程和推理队列
from AiVision.inference.model_registry import MODEL_SPECS
from AiVision.features.detect_logistics_single_person.constants import LOGISTICS_FEATURES
from AiVision.features.detect_logistics_single_person.runtime import LogisticsChannelRuntime
from AiVision.features.detect_logistics_single_person.service import logistics_channel_service
from AiVision.alarms.devices.runtime_manager import horn_runtime_manager                   # 喇叭设备
from AiVision.alarms.records.service import violation_writer                  # 写入违规记录
from AiVision.alarms.evidence.evidence_recorder import alarm_evidence_recorder  # 保存告警前后视频证据

# 全局常量，这些改了可能需要重启摄像头进程
_CAMERA_RUNTIME_FIELDS = ("url", "fps", "max_restart", "enabled", "enable")
_ANNOTATED_FRAME_FRESH_SECONDS = 2.0                                       # 带检测框的结果帧新鲜的秒数
# 摄像头运行异常类型集合
_CAMERA_RUNTIME_ALERT_TYPES = {
    "启动失败",
    "启动超时",
    "视频流异常",
    "摄像头未运行",
}

class Orchestrator:
    """系统总编排器"""

    # ---------- 初始化 ----------

    def __init__(self, mp_manager):
        """此阶段主要创建和保存各子模块对象
        接收mp_manager:跨进程共享管理器
        主要创建：
            1、摄像头采集进程管理器CameraRuntimeManager
            2、各检测功能的Consumer字典
            3、喇叭运行管理器
            4、企业微信通知对象（告警对象）
            5、物流通道实时业务模块LogisticsChannelRuntime
        """
        self.camera_runtime_manager = CameraRuntimeManager(mp_manager)                      # 摄像头采集进程
        self.consumers: dict[str, BaseFunctionConsumer] = {}                 # 所有检测业务处理器，字典，key为检测业务名称，Value为具体的检测业务对象，取具体检测业务的时候只要名字就行
        self.horn_runtime_manager = horn_runtime_manager                                           # 当前运行中的喇叭设备
        self._wechat: Optional[WeChatNotifier] = None                        # 企业微信
        self._started = False                                                # 启动按钮
        self._last_system_exception_alerts: dict[tuple[str, str], float] = {} # 系统异常告警最后发送时间表
        self._system_exception_alert_lock = threading.Lock()                 # 异常告警的锁
        # 物流通道实时业务模块
        self.logistics_channel_runtime = LogisticsChannelRuntime(
            channel_service=logistics_channel_service,            # 查物流通道配置的服务
            dispatcher=alarm_dispatcher,                          # 统一告警模块
            is_camera_active=frame_reader_registry.is_active,     # 摄像头存活函数，传函数名，需要调用的时候自己调用
            frame_provider=lambda shm_name: frame_reader_registry.latest_frames.get(shm_name),   # 获取摄像头最新画面函数
            evidence_recorder=alarm_evidence_recorder,
        )

        # 监听配置变更
        config_event_bus.subscribe_wildcard(self._handle_runtime_config_change)

    # ---------- 生命周期 ----------

    def start(self):
        """
        启动顺序：
            1、整理数据库和配置
            2、初始化企业微信异常通知
            3、启动摄像头采集进程
            4、启动帧读取和违规记录
            5、初始化告警模块
            6、创建推理Queue
            7、启动YOLO模型进程
            8、启动各检测功能线程
            9、AiVision启动完成
        """
        # 重复调用退出
        if self._started:
            return
        logger.info("=" * 20 + " Orchestrator 启动 " + "=" * 20)

        # 1) 数据库 schema 修补，在启动摄像头和模型之前，把配置整理干净
        ensure_schema_ready()                             # 创建新表并核验数据库结构
        camera_config_manager.normalize_shm_names()                   # 整理摄像头共享内存名称
        camera_config_manager.ensure_feature_configs() # 确保每台摄像头需要的功能配置存在
        config_cache.init()                                     # 把配置从数据库加载到运行时缓存

        # 2) 企微客户端先初始化,摄像头启动异常可直接推送
        if settings.alarm.wechat_enable:
            self._wechat = WeChatNotifier()                             # 创建企业微信客户端
            self.camera_runtime_manager.configure_runtime_alerts(self._send_system_exception_alert)        # 摄像头运行过程中异常，调用异常通知函数
            inference_runtime_manager.configure_runtime_alerts(self._send_system_exception_alert)          # 模型异常，调用异常通知函数
        else:
            self.camera_runtime_manager.configure_runtime_alerts(None)
            inference_runtime_manager.configure_runtime_alerts(None)

        # 3) 摄像头进程
        cameras = camera_config_manager.list_cameras()                   # 查摄像头数据库配置
        cleanup_count = cleanup_aivision_residual_processes(      # 清理残留进程
            camera_shm_names=[c["shm_name"] for c in cameras],
            camera_urls=[c["url"] for c in cameras],
            model_names=list(MODEL_SPECS),
        )
        if cleanup_count:
            logger.warning(f"[Orchestrator] 启动前已清理 {cleanup_count} 个 AiVision 残留进程")

        # 转成 CameraRuntimeManager 期望的格式(把功能配置展平后传)
        cam_configs = []
        for c in cameras:
            functions = c.get("functions") or {}
            cam_configs.append({
                "name": c["name"],
                "shm_name": c["shm_name"],
                "url": c["url"],
                "fps": c["fps"],
                "max_restart": c["max_restart"],
                "enable": bool(c["enabled"]) and self._camera_has_enabled_feature(functions),       # 摄像头真正启用必须满足摄像头本身enabled=true,以及至少有一个功能需要这台摄像头
                "shape": c.get("shape") or [1080, 1920, 3],
            })
        # 启动摄像头
        self.camera_runtime_manager.initialize_configs(cam_configs)       # 初始化摄像头配置
        self.camera_runtime_manager.start_all()                           # 启动摄像头采集进程：采集RTSP以及写共享内存
        frame_reader_registry.start_all()                         # 启动帧读取：从共享内存中读取最新帧，给检测模块使用
        alarm_evidence_recorder.set_status_callback(violation_writer.update_video_status)  # 回调函数，告诉报警记录器，当状态发生变化时，自动调用violation_writer.update_video_status函数
        alarm_evidence_recorder.start(lambda: frame_reader_registry.latest_frames)         # 告警视频录制模块，需要持续访问最新帧，所以把最新帧获取方式交给它

        # 4) 违规图片写入
        violation_writer.configure_media_cleanup(RecognitionMediaReferences())
        violation_writer.start()          # 共用其媒体清理调度；识别记录仍由自己的 Consumer 异步写入

        # 5) 告警通道
        self.horn_runtime_manager.start()      #创建真正运行中的喇叭对象
        # 告警模块配置（依赖注入：调度器把报警依赖交给AlarmDispatcher，将工具给它，以后由它负责告警）
        alarm_dispatcher.configure(
            horn_runtime_manager=self.horn_runtime_manager,             #喇叭对象
            wechat=self._wechat,                   # 微信客户端
            violation_writer=violation_writer,     # 违规保存数据库记录模块
            evidence_recorder=alarm_evidence_recorder,  # 报警视频模块
        )

        # 6) 推理 Worker 进程
        inference_runtime_manager.initialize_queues()         # 创建模型任务队列
        inference_runtime_manager.configure_runtime_monitor(self._monitor_consumer_threads)
        inference_runtime_manager.start_all()                 # 启动所有模型进程，启动后：加载模型，然后等待infer_queue任务

        # 7) 开启物流通道实时检测模块
        self.logistics_channel_runtime.start()
        # 开启所有检测功能的处理线程
        self._start_consumers()                               # 调用函数

        self._started = True                          # Orchestrator已经完成启动流程
        logger.info("=" * 20 + " Orchestrator 启动完成 " + "=" * 20)

    def stop(self):
        """
        关闭顺序是启动的反方向
        启动：摄像头->帧读取->违规记录->告警->模型->Consumer
        关闭：Consumer->模型->告警相关->帧读取->摄像头  ：先关闭启动资源的人，再关闭资源本身
        """
        # 没启动不用重复关闭
        if not self._started:
            return
        logger.info("=" * 20 + " Orchestrator 停止 " + "=" * 20)
        inference_runtime_manager.configure_runtime_monitor(None)

        # 逆序停止，先停上层使用者，在停下面提供资源的模块
        # 1、先停止所有的检测功能线程
        for name, consumer in list(self.consumers.items()):       # list相当于先复制一份当前内容，避免遍历时字典变化带来的问题
            try:
                consumer.stop()
            except Exception as e:
                logger.warning(f"[Orchestrator] 停止 Consumer {name} 失败: {e}")
        self.consumers.clear()                      # 清空Consumer字典
        try:
            self.logistics_channel_runtime.stop()   # 停止物流通道
        except Exception as e:
            logger.warning(f"[Orchestrator] 停止物流通道运行时失败，将继续清理其余资源: {e}")

        try:
            # 2、停止模型推理进程
            inference_runtime_manager.stop_all()
        except Exception as e:
            logger.warning(f"[Orchestrator] 停止推理失败: {e}")
        try:
            alarm_dispatcher.stop()
        except Exception as e:
            logger.warning(f"[Orchestrator] 停止微信告警线程失败: {e}")
        # 3、停止喇叭心跳
        try:
            self.horn_runtime_manager.stop()
        except Exception as e:
            logger.warning(f"[Orchestrator] 停止喇叭运行管理器失败: {e}")
        # 4、停止告警视频记录模块
        try:
            alarm_evidence_recorder.stop()
        except Exception:
            pass
        # 5、停止告警记录写入模块
        try:
            violation_writer.stop()
        except Exception as exc:
            logger.error(f"[Orchestrator] 停止告警写入和平台媒体清理失败: {exc}")
        # 6、停止帧读取
        try:
            frame_reader_registry.stop_all()
        except Exception:
            pass
        # 7、停止摄像头采集进程
        try:
            self.camera_runtime_manager.stop_all()
        except Exception:
            pass
        # 8、释放数据库连接
        from AiVision.core.db import dispose
        dispose()

        self._started = False                                    # 修改状态
        logger.info("=" * 20 + " Orchestrator 已停止 " + "=" * 20)

    # ---------- Consumer 管理 ----------

    def _start_consumers(self):
        """
        批量启动所有已注册检测功能：
        流程：
            1、从 all_specs() 获取所有已注册检测功能
            2、调用 _start_consumer() 逐个创建并启动检测业务处理器
            3、单个功能启动失败只记录异常和发送系统告警

        Consumer 常驻运行，具体处理哪些摄像头由各摄像头的功能绑定配置决定。
        """
        # 遍历系统所有检测功能，一个一个启动
        for name, spec in all_specs().items():
            try:
                # 真正启动检测功能
                self._start_consumer(name, spec)
            except Exception:
                logger.exception(f"[Orchestrator] 启动 Consumer {name} 失败")
                # 发送系统自身异常告警
                self._send_system_exception_alert(
                    target_name=name,
                    target_key=name,
                    event_type="功能启动异常",
                    detail=f"Consumer {name} 启动失败",
                )

        logger.info(f"[Orchestrator] 已启动 {len(self.consumers)} 个 Consumer")

    def _start_consumer(self, name: str, spec=None):
        """创建并启动一个 Consumer具体检测功能处理器；依赖模型不可用时明确失败。
        例如detect_phone:
            1、获取手机检测FeatureSpec
            2、检测yolo_phone等依赖模型是否已经运行
            3、将模型任务队列、结果队列、最新视频帧、摄像头状态检测函数等资源传给PhoneConsumer
            4、创建PhoneConsumer实例
            5、调用start()启动detect_phone的处理线程
            6、保存到self.consumers中，供后续停止，热更新的查询
        """
        # 1、防止重复启动
        if name in self.consumers and self.consumers[name].running:
            return self.consumers[name]
        # 2、获取检测功能的spec
        spec = spec or all_specs().get(name)
        if spec is None:
            raise ValueError(f"未知检测能力: {name}")
        # 3、检测模型是否已经启动
        running_models = set(inference_runtime_manager.list_running())
        missing = [model for model in spec.required_models if model not in running_models]    # 找出缺失的模型
        # 缺失模型时不启动检测功能
        if missing:
            raise RuntimeError(
                f"依赖模型未启动: {', '.join(missing)}; "
                f"当前运行模型: {', '.join(sorted(running_models)) or '无'}"
            )
        # 4、给检测功能处理器准备好需要的关键词参数
        consumer_kwargs = dict(
            spec=spec,                                        # 功能说明书
            infer_dict=inference_runtime_manager.infer_queues,        # 推理任务队列
            result_queue=inference_runtime_manager.result_queues[name],# name检测功能结果返回队列
            latest_frames=frame_reader_registry.latest_frames, # 当前所有摄像头的最新帧
            is_camera_active=frame_reader_registry.is_active,  # 摄像头是否在线函数
            runtime_alert_handler=self._send_system_exception_alert,  # Orchestrator的系统异常通知函数
        )
        # 5、物流通道特殊处理
        if name in LOGISTICS_FEATURES:
            consumer_kwargs["logistics_runtime"] = self.logistics_channel_runtime # 关键词参数加上logistics_runtime
        # 创建各检测功能的consumer
        consumer = spec.consumer_cls(**consumer_kwargs)
        # 启动线程主要调用函数
        consumer.start()                               # 启动当前功能consumer线程
        self.consumers[name] = consumer                # 保存实例
        return consumer                                # consumer对象

    # ---------- 配置热更新 ----------

    def _handle_runtime_config_change(self, event: ConfigChangeEvent):
        """
        在初始化函数里订阅了这个函数：config_event_bus.subscribe_wildcard(self._handle_runtime_config_change)，只要其他地方发生配置变化事件，这个函数就会被调用
        系统运行过程中，只要摄像头、检测功能或者物流通道的配置发生变化，这个函数就负责接收变化通知，并把变化转交给对应的运行模块，让配置立即生效，不用重启AiVision
        函数通过event.change_type判断变化类型
        主要处理：
            1、物流通道变化：刷新对应的LogisticsChannelRuntime
            2、摄像头新增、修改、删除，动态启动、重启、停止或移除摄像头
            3、检测功能配置变化，找对对应的Consumer，enabled、disabled、config_updated
        函数调用链：
            1、摄像头新增：_add_camera_to_runtime（热添加摄像头）  ===>  build_camera_runtime_config（从数据库加载新配置，整理成comsumer所需要的配置）  ===>  camera_has_enabled_feature()
            2、摄像头修改：_camera_update_requires_restart(摄像头配置修改后的重启需求)  
            3、摄像头修改：_restart_or_stop_camera（停止旧进程，新配置重新启动）  ===>  build_camera_runtime_config 
            4、普通信息修改： _refresh_consumer_camera_config（让正在运行的Comsumer去加载新配置）
            5、功能绑定启用/禁用：_sync_camera_process_state（让摄像头实际运行状态和配置要求状态一致）  +===>  build_camera_runtime_config  +===>
            6、物流配置变化：logistics_channel_runtime.refresh_xxx()
        """
        # 取字段
        change = event.change_type
        cam_id = event.camera_id

        # 判断是不是物流通道更新
        if change == "logistics_channel_updated":
            value = event.new_value or {}                     # 修改后新配置的附加信息
            feature_name = value.get("feature_name")          # 功能名称（比如电子电工事业部对应的物流通道检测）
            channel_id = value.get("channel_id")               # 物流通道名称（一个通道可以配置多个摄像头）
            if feature_name in LOGISTICS_FEATURES and channel_id is not None:
                # 让正在运行的物流通道模块重新读取这个通道的最新配置
                self.logistics_channel_runtime.refresh_channel(
                    feature_name,
                    int(channel_id),
                )
            return                                        # 如果是物流通道配置发生变化，处理完了就结束

        # 摄像头层面，处理新增摄像头、修改摄像头、删除摄像头
        if change == "camera_added":
            # 直接把摄像头加入运行系统，会重新读取摄像头的配置，然后交给CameraRuntimeManager，应该运行就start_camera()
            # 这里的camera_name是shm_name
            self._add_camera_to_runtime(event.camera_name)
            return
        if change == "camera_updated":
            # 如果物流通道也引用了这台摄像头，那么摄像头配置变了以后，物流模块也要刷新
            if cam_id is not None:
                self.logistics_channel_runtime.refresh_camera_all(cam_id)# 让所有使用这台摄像头的物流通道重新读取它
            # 这次修改需不需要重启摄像头进程（rtsp流以及摄像头的禁用什么的需要重启或者关闭，名称什么的不需要）
            if self._camera_update_requires_restart(event):
                self._restart_or_stop_camera(event.camera_name)
            else:
                self._refresh_consumer_camera_config(cam_id)           # 通知Consumer重新读取即可
                logger.info(f"[Orchestrator] 摄像头展示信息已热更新 cam_id={cam_id} shm={event.camera_name}")
            return
        if change == "camera_removed":
            if cam_id is not None:
                for name, consumer in list(self.consumers.items()):
                    try:
                        consumer.remove_camera(cam_id, event.camera_name)
                    except Exception:
                        logger.exception(f"[Orchestrator] 清理 Consumer 失败 feature={name} cam_id={cam_id}")
            # 通知物流模块，这台摄像头已经不存在了
            if cam_id is not None:
                try:
                    self.logistics_channel_runtime.refresh_camera_all(cam_id)
                except Exception:
                    logger.exception(f"[Orchestrator] 删除后刷新物流通道失败 cam_id={cam_id}")
            # 从CameraRuntimeManager运行配置里彻底移除这台摄像头
            self.camera_runtime_manager.remove_camera_config(event.camera_name)
            logger.info(f"[Orchestrator] 摄像头已热移除 cam_id={cam_id} shm={event.camera_name}")
            return

        """
        检测功能配置变化
        事件格式：
            detect_xxxx_enabled
            detect_xxxx_disabled
            detect_xxxx_config_updated
        处理逻辑：
            1、判断属于哪个feature
            2、找到对应的Consumer
            3、enabled/disabled：把摄像头加入或者移除该Consumer
            4、config_updated:重新加载该摄像头的最新功能配置
        """
        for fname in sorted(all_specs(), key=len, reverse=True):        # 按照功能名名字，从长到短排列
            if change.startswith(f"{fname}_"):                  # 把名字中的功能名部分截取出来（比如fname=detect_phone_config_uodated,截取前面就是fname=detect_phone）
                action = change[len(fname) + 1:]                #
                # 物流通道特殊处理
                if (
                    fname in LOGISTICS_FEATURES
                    and action not in ("enabled", "disabled")
                    and cam_id is not None
                ):
                    self.logistics_channel_runtime.refresh_camera(fname, cam_id)    # 只是配置变化就通知物流运行模块刷新这台摄像头
                # 找到对应的Consumer
                consumer = self.consumers.get(fname)
                if action in ("enabled", "disabled"):
                    if consumer is not None:
                        # 添加/移除 Consumer 的摄像头处理状态
                        consumer.update_status(cam_id, action == "enabled")
                    # 功能绑定变化只同步期望状态，不强制重启仍被其他功能使用的摄像头。
                    self._sync_camera_process_state(event.camera_name)
                else:  # 如果是配置更新，重新读取这台摄像头的功能参数
                    if consumer is None:             # Consumer 没启动，不更新其配置
                        return
                    consumer.update_config(cam_id)
                return

    # ---------- 摄像头辅助函数 ----------

    @staticmethod
    def _camera_has_enabled_feature(functions: dict) -> bool:
        """摄像头至少绑定一个已启用的检测功能时返回 True。"""
        return any(bool(enabled) for enabled in functions.values())

    @staticmethod
    def _camera_update_requires_restart(event: ConfigChangeEvent) -> bool:
        """
        摄像头配置修改的重启需求
        如果RTSP地址、FPS、最大重启次、启停状态等运行参数发生变化，则返回True
        如果只是摄像头名称、部门等不影响采集字段变化，则返回False，只刷新业务配置，不重启摄像头进程
        缺少新或者旧的完整配置，返回True
        """
        old_value = event.old_value or {}         # 修改前配置
        new_value = event.new_value or {}          # 修改后配置
        # 如果没有完整的修改前后数据，返回True（需要重启，宁可重启一次，也不要冒险使用新配置）
        if not old_value or not new_value:
            return True

        # 遍历影响采集进程的字段，如果新旧配置不一样就需要重启
        for field in _CAMERA_RUNTIME_FIELDS:
            if old_value.get(field) != new_value.get(field):
                return True
        return False

    def _refresh_consumer_camera_config(self, camera_id: int | None):
        """
        让正在运行Consumer去重新加载指定摄像头的最新配置
        参数：
            camera_id:指定摄像头
        """
        if camera_id is None:
            return
        # 遍历所有正在运行的Consumer
        for consumer in self.consumers.values():
            # 各个摄像头去检查camera_id和自己有没有关系，有就加载最新配置
            try:
                consumer.update_config(camera_id)
            except Exception as e:
                logger.warning(f"[Orchestrator] 刷新 Consumer 摄像头展示信息失败 cam_id={camera_id}: {e}")

    def _build_camera_runtime_config(self, key: str) -> dict | None:
        """
        从数据库拿到摄像头的完整配置，整理成CameraRuntimeManager真正需要的运行配置
        参数：
            key：shm_name
        enable的规则：
            摄像头自身enabled=True，并且至少存在一个当前有效的检测能力，才允许摄像头采集进程进行
        """
        # 去摄像头配置里找对应的摄像头
        camera = camera_config_manager.get_camera(key)
        if camera is None:
            logger.warning(f"[Orchestrator] 摄像头配置不存在: {key}")
            return None
        # 取摄像头功能配置
        functions = camera.get("functions") or {}
        # 返回新字典
        return {
            "name": camera["name"],
            "shm_name": camera["shm_name"],
            "url": camera["url"],
            "fps": camera["fps"],
            "max_restart": camera["max_restart"],                # 摄像头异常后最多允许尝试重启多少次
            "enable": bool(camera["enabled"]) and self._camera_has_enabled_feature(functions),    # 1、摄像头本身必须启用，2、必须至少有一个有效的检测功能
            "shape": camera.get("shape") or [1080, 1920, 3],                   # 图像尺寸
        }

    def _add_camera_to_runtime(self, key: str):
        """
        热添加摄像头（将摄像头加入Aivision运行系统）
        读取某台摄像头最新运行配置，把配置交给CameraRuntimeManager，如果摄像头应该运行就尝试启动，如果不应该运行就确保他停止
        包含两件事情：
            1、更新摄像头配置
            2、根据摄像头配置决定运行状态
        """
        cfg = self._build_camera_runtime_config(key)
        if cfg is None:
            return
        shm_name = cfg["shm_name"]
        # 把最新配置交给CameraRuntimeManager
        self.camera_runtime_manager.update_camera_config(shm_name, cfg)
        # 根据当前系统状态计算后，这台摄像头现在是否应该启动采集线程
        if not cfg.get("enable", True):
            self.camera_runtime_manager.stop_camera(shm_name)
            logger.info(f"[Orchestrator] 摄像头已禁用,未启动 shm={shm_name}")
            return
        ok = self.camera_runtime_manager.start_camera(shm_name)
        if ok:
            logger.info(f"[Orchestrator] 摄像头已热启动 shm={shm_name}")
        else:
            logger.warning(f"[Orchestrator] 摄像头热启动失败 shm={shm_name}")

    def _sync_camera_process_state(self, key: str):
        """检查摄像头现在应该运行还是停止，然后让实际状态和配置一致"""
        cfg = self._build_camera_runtime_config(key)
        if cfg is None:
            return
        shm_name = cfg["shm_name"]
        self.camera_runtime_manager.update_camera_config(shm_name, cfg)

        should_run = bool(cfg.get("enable"))
        is_running = self.camera_runtime_manager.is_running(shm_name)
        if should_run == is_running:
            return
        if should_run:
            self.camera_runtime_manager.start_camera(shm_name)
            logger.info(f"[Orchestrator] 摄像头已按功能绑定热启动 shm={shm_name}")
        else:
            self.camera_runtime_manager.stop_camera(shm_name)
            logger.info(f"[Orchestrator] 摄像头已按功能绑定热停止 shm={shm_name}")

    def _restart_or_stop_camera(self, key: str):
        """
        摄像头底层参数真正变化时，先停旧进程，在感觉新配置决定是否重新启动
        将这个与_add_camera_to_runtime做区分：
            _add_camera_to_runtime: 读取配置，更新配置，需要运行：start（不会强制stop）
            _restart_or_stop_camera: 读取配置，先stop，更新配置，还需要运行:是就start，否就保持停止
        前者适合新增摄像头
        后者适合已有摄像头运行参数修改
        """
        # 获取摄像头最新配置
        cfg = self._build_camera_runtime_config(key)
        if cfg is None:
            return
        shm_name = cfg["shm_name"]
        # 先无条件停止旧进程
        self.camera_runtime_manager.stop_camera(shm_name)
        # 更新CameraRuntimeManager配置
        self.camera_runtime_manager.update_camera_config(shm_name, cfg)
        # 判断新配置允许不允许运行，不允许就停止
        if not cfg.get("enable", True):
            logger.info(f"[Orchestrator] 摄像头已热停止 shm={shm_name}")
            return
        # 允许就重新启动
        ok = self.camera_runtime_manager.start_camera(shm_name)
        if ok:
            logger.info(f"[Orchestrator] 摄像头已热重启 shm={shm_name}")
        else:
            logger.warning(f"[Orchestrator] 摄像头热重启失败 shm={shm_name}")

    # ---------- 运行监控与系统异常告警 ----------

    def _monitor_consumer_threads(self) -> None:
        """由现有运行时 watchdog 检查 Consumer 线程并发送异常告警。"""
        if not self._started:
            return
        for name, consumer in list(self.consumers.items()):
            if not consumer.running:
                self._send_system_exception_alert(
                    target_name=name,
                    target_key=name,
                    event_type="功能线程退出",
                    detail=f"Consumer {name} 已不在运行状态",
                )

    def _send_system_exception_alert(self, target_name: str, target_key: str, event_type: str, detail: str):
        """
        当摄像头、模型或者其他运行模块发生系统异常时，按照系统异常告警配置，通过企业微信发送一条异常停止，并做重复告警抑制
        参数：
            target_name：前端显示的摄像头名称
            target_key:shm_name
            event_type:异常类型，比如视频流异常
            detail:异常详细信息
        """
        # 检查微信有没有初始化
        if self._wechat is None:
            return
        # 系统异常的告警配置（配置控制系统异常要不要发微信，发给谁，同类异常多久允许重复发一次）
        alert = system_config_service.get_exception_alert()
        # 判断异常告警有没有开启
        if not alert.get("wechat_enable"):
            return
        # 获取收件人
        recipients = str(alert.get("wechat_user") or "").strip()
        if not recipients:
            return
        now = time.time()
        # 合并一些看起来不太同但是属于一类的异常问题，防止一个摄像头连续出现多个异常疯狂刷新微信
        alert_group = self._system_exception_alert_group(event_type)
        # 给异常生成一个shm_name + alert_group的iD编号
        alert_key = (target_key, alert_group)
        # 计算冷却时间
        cooldown_seconds = float(alert["repeat_interval_minutes"]) * 60.0
        with self._system_exception_alert_lock:                                 # 加锁
            # 检查上一次什么时候发过
            last = self._last_system_exception_alerts.get(alert_key, 0.0)
            if now - last < cooldown_seconds:
                return
            # 记下这次告警时间
            self._last_system_exception_alerts[alert_key] = now
        # 格式化当前时间
        now_text = time.strftime("%Y-%m-%d %H:%M:%S")
        # 发送企业微信
        self._wechat.send_text(
            content=(
                "AiVision 系统异常\n"
                f"**对象**: {target_name}\n"
                f"**标识**: {target_key}\n"
                f"**类型**: {event_type}\n"
                f"**详情**: {detail}\n"
                f"**时间**: {now_text}\n"
            ),
            recipients=recipients,
        )

    @staticmethod
    def _system_exception_alert_group(event_type: str) -> str:
        """
        _CAMERA_RUNTIME_ALERT_TYPES:启动失败、启动超时、视频流异常、摄像头未运行
        字符串开头为采集进程退出以及画面停更
        将其归类为一个摄像头运行异常报警组

        如果不是上述这一块的摄像头相关异常，就保持原来的异常类型
        """
        if event_type in _CAMERA_RUNTIME_ALERT_TYPES:
            return "摄像头运行异常"
        if event_type.startswith("采集进程退出") or event_type.startswith("画面停更"):
            return "摄像头运行异常"
        return event_type

    # ---------- API 查询函数 ----------

    """
    以下是给前端或者其他模块提供的查询接口，主要是获取摄像头画面和检测状态
    1、get_camera_frame(shm_name, feature=None) 获取摄像头画面，优先取标注后的帧，没有就取原始帧
       →  get_camera_frame_info(shm_name, feature=None) 获取摄像头画面和更新时间，优先取标注后的帧，没有就取原始帧
    2、get_feature_monitor_status(shm_name, feature) 获取摄像头在某个检测功能下的实时监控状态，主要供前端实时状态展示使用
    3、get_logistics_channel_status(shm_name, feature, channel_id) 获取摄像头在某个物流通道下的实时监控状态，主要供前端实时状态展示使用
        → LogisticsChannelRuntime.get_channel_status()
    4、get_logistics_channel_frame(shm_name, feature, channel_id) 获取摄像头在某个物流通道下的标注画面，主要供前端实时状态展示使用
         → LogisticsChannelRuntime.get_channel_frame()
    5、runtime_status() 获取AiVision Orchestrator的运行状态，主要供前端实时状态展示使用
    """

    def get_camera_frame(self, shm_name: str, feature: str | None = None):
        """获取摄像头画面：指定 feature 只返回标注帧；配置编辑读取原始帧"""
        # frame:图像，_updated_at:最后更新的时间
        frame, _updated_at = self.get_camera_frame_info(shm_name, feature=feature)
        return frame

    def get_camera_frame_info(self, shm_name: str, feature: str | None = None):
        """
        从原始帧和算法标注帧中，选择当前最适合展示的一帧
            1、指定检测功能时，只返回对应 Consumer 最近 2 秒内的标注画面
            2、未指定检测功能时，返回最近 10 秒内的原始画面供配置编辑
            3、需要的画面过期或不存在时返回 None
        """
        now = time.time()
        # 获取原始帧，来自于共享内存的lastest_frames
        raw = frame_reader_registry.latest_frames.get(shm_name)
        # 原始帧更新时间
        raw_updated_at = frame_reader_registry.latest_frame_times.get(shm_name, 0.0)
        # 这帧话画面是否是新鲜的：满足三个条件：1、真的有图片，2、记录过更新时间，3、画面距离现在不能超过十秒
        raw_is_fresh = raw is not None and raw_updated_at > 0 and now - raw_updated_at <= 10.0
        annotated_updated_at = 0.0               # 初始化标注帧更新时间
        if feature and feature in self.consumers:
            consumer = self.consumers[feature]            # 找到功能对应的Consumer
            # 从Consumer中拿标注画面
            annotated = consumer.result_dict.get(shm_name)
            annotated_updated_at = consumer.result_updated_at.get(shm_name, 0.0)
            # 判断标注帧是不是最新的，_ANNOTATED_FRAME_FRESH_SECONDS是2，所以这里是大于2秒就不在新鲜
            annotated_is_fresh = (
                annotated is not None
                and annotated_updated_at > 0
                and now - annotated_updated_at <= _ANNOTATED_FRAME_FRESH_SECONDS
            )
            if annotated_is_fresh:
                return annotated, annotated_updated_at      # 标注有效就返回标注帧
        if not feature and raw_is_fresh:
            return raw, raw_updated_at              # 原始帧仅用于配置编辑
        return (
            None,
            max(raw_updated_at, annotated_updated_at),
        )      # 两个都没有就帧返回None，更新时间选最近的

    def get_feature_monitor_status(self, shm_name: str, feature: str) -> dict:
        """
        查看shm_name在feature检测功能下的当前监控状态
        主要供前端实时状态展示使用
        流程：
            1、从CameraRuntimeManager判断摄像头采集进程是否在线
            2、根据feature找到对应Consumer
            3、调用Consumer.get_monitor_status()获取最新检测状态
            4、只有最近2秒内更新的状态才认为有效
            5、有效时返回人数、告警、原因、持续时间等
            6、无结果或者结果过期时返回unknown，避免前端显示旧检测结果

        """
        # 判断摄像头采集进程有没有在运行
        online = shm_name in set(self.camera_runtime_manager.list_running())
        consumer = self.consumers.get(feature)                          # 找到对应的Consumer
        getter = getattr(consumer, "get_monitor_status", None)          # 查看Consumer有没有一个叫get_monitor_status的函数
        snapshot = getter(shm_name) if callable(getter) else None       # 从get_monitor_status函数里取当前摄像头的监控状态， callable()：这个东西能不能像函数一样被调用
        updated_at_s = float(snapshot.get("updated_at_s") or 0.0) if snapshot else 0.0   #取状态更新时间
        # 判断状态是不是最新的(2秒内更新)
        fresh = bool(
            snapshot
            and updated_at_s > 0
            and time.time() - updated_at_s <= _ANNOTATED_FRAME_FRESH_SECONDS
        )
        # 如果状态过期，返回自定义字典
        if not fresh:
            return {
                "camera_key": shm_name,
                "feature": feature,
                "online": online,
                "count": None,
                "alarm": False,
                "reason": "unknown",                  # 状态未知
                "duration_seconds": None,
                "threshold_seconds": None,
                "updated_at": None,
                **({"detections": [], "frame_width": None, "frame_height": None} if feature == "recognize_face" else {}),
            }
        # 如果状态有效，就转换时间
        updated_at = dt.datetime.fromtimestamp(
            updated_at_s,
            tz=dt.timezone.utc,
        ).astimezone().isoformat()        # .astimezone()表示转换成服务器本地时区
        return {
            "camera_key": shm_name,
            "feature": feature,
            "online": online,
            "count": snapshot.get("count"),
            "alarm": bool(snapshot.get("alarm")),
            "reason": str(snapshot.get("reason") or "unknown"),
            "duration_seconds": snapshot.get("duration_seconds"),
            "threshold_seconds": snapshot.get("threshold_seconds"),
            "updated_at": updated_at,
            **({
                "detections": snapshot.get("detections", []) if online else [],
                "frame_width": snapshot.get("frame_width"),
                "frame_height": snapshot.get("frame_height"),
            } if feature == "recognize_face" else {}),
        }

    def get_logistics_channel_status(self, feature: str, channel_id: int) -> dict | None:
        """把channel_id这个通道相关摄像头信息综合得到的整体状态"""
        return self.logistics_channel_runtime.get_channel_status(feature, channel_id)

    def get_logistics_channel_frame(self, feature: str, channel_id: int):
        """获取物流通道的最新拼接标注画面。"""
        return self.logistics_channel_runtime.get_channel_frame(feature, channel_id)

    def runtime_status(self) -> dict:
        """
        汇总AiVision的整体运行状态，主要供健康检测和状态接口使用
        包括：
            1、当前正在运行的摄像头采集进程
            2、当前正在运行的模型推理进程
            3、Consuemr本身及其依赖模型是否正常
            4、InferenceWorker和各Consumer的详细推理状态
        """
        # 真正已经启动的模型推理进程有哪些
        running_models = inference_runtime_manager.list_running()
        running_model_set = set(running_models)
        # 遍历所有Consumer，如果这个Consumer支持inference_status(),就把自己的推理状态收集起来
        consumer_inference = {
            name: consumer.inference_status()
            for name, consumer in self.consumers.items()
            if callable(getattr(consumer, "inference_status", None))
        }
        # Consumer在运行，并且这个consumer依赖的所有模型也必须正在运行
        running_consumers = [
            name
            for name, consumer in self.consumers.items()
            if consumer.running and all(model in running_model_set for model in consumer.spec.required_models)
        ]
        # 最后返回系统整体运行状态
        return {
            "started": self._started,                             # Orchestrator整体有没有完成启动
            "running_cameras": self.camera_runtime_manager.list_running(), # 当前正在运行采集的摄像头
            "running_models": running_models,                     # 当前正在运行的模型推理进程
            "running_consumers": running_consumers,              # Consumer本身正常，而且它依赖的模型也全部正常的检测功能
            "inference": {
                "workers": inference_runtime_manager.runtime_status(),     # 模型推理进程的详细状态
                "consumers": consumer_inference,                   # 每个consumer自己的推理调用状态
            },
        }


# ---------- 类外全局实例 ----------
# 全局唯一的Orchestrator实例，程序刚开始启动时未创建，先为None
# main调用init_orchestrator后才真正实例化，后续其他模块通过get_orchestrator获取同一对象
orchestrator: Optional[Orchestrator] = None

def get_orchestrator() -> Orchestrator:
    """
    获取已经初始化好的全局Orchestrator对象
    本函数只负责获取，不负责创建
    """
    if orchestrator is None:
        raise RuntimeError("Orchestrator 未初始化,请先在 main.py 调用 init_orchestrator()")
    return orchestrator

def init_orchestrator(mp_manager) -> Orchestrator:
    """
    负责创建并保存全局orchestrator实例
    第一次调用时使用 mp_manager 创建 Orchestrator
    后续再次调用不会重复创建，而是返回已有实例。
    """
    global orchestrator
    if orchestrator is None:
        orchestrator = Orchestrator(mp_manager)         # 创建orchestrator对象
    return orchestrator                                # 返回orchestrator这个全局对象
