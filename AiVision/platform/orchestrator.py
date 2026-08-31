# 文件说明：实现`orchestrator` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/orchestrator.py
总编排 — 替代旧 utils/cap.py 里 700 行的 CapManager 上帝对象。

新版本只做编排,具体职责委托给:
    CameraManager      → 摄像头进程
    InferenceManager   → 推理 Worker 进程  
    FrameReaderRegistry→ 统一帧读取
    AsyncViolationWriter → 违规图片写入
    AlarmDispatcher    → 告警分发
    Consumer 实例      → 业务处理(每 feature 一个)

启动顺序: 缓存 → Camera → Inference → Violation → Alarm → Consumer
关闭顺序逆序进行。
"""
from __future__ import annotations
import datetime as dt
import threading
import time
from typing import Optional

from core.logger import logger
from core.cache import config_cache
from core.db import ensure_schema_compatible
from core.events import config_event_bus, ConfigChangeEvent
from core.alarm.dispatcher import alarm_dispatcher
from core.alarm.wechat import WeChatNotifier
from core.process_cleanup import cleanup_aivision_residual_processes
from core.settings import settings
from core.system_config import system_config_service

from features import all_specs
from features._base.consumer import BaseFunctionConsumer

from platform.camera.manager import CameraManager
from platform.camera.frame_reader import frame_reader_registry
from platform.camera.service import camera_service
from platform.inference.manager import inference_manager
from platform.inference.service import model_service
from platform.logistics_channel.constants import LOGISTICS_FEATURES
from platform.logistics_channel.runtime import LogisticsChannelRuntime
from platform.logistics_channel.service import logistics_channel_service
from platform.alarm_device.service import horn_service
from platform.violation.service import violation_writer
from platform.violation.evidence_recorder import alarm_evidence_recorder


_CAMERA_RUNTIME_FIELDS = ("url", "fps", "max_restart", "enabled", "enable")
_ANNOTATED_FRAME_FRESH_SECONDS = 2.0
_CAMERA_RUNTIME_ALERT_TYPES = {
    "启动失败",
    "启动超时",
    "视频流异常",
    "摄像头未运行",
}


# 功能：系统总编排器；输入与输出详见下方说明
# 参数：
#   - `mp_manager`（未显式标注）：`mp_manager` 对应的业务输入值
# 返回：Orchestrator；返回新建的 `Orchestrator` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/orchestrator.py` 的 `init_orchestrator` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class Orchestrator:
    """系统总编排器"""

    # 功能：初始化或配置 `__init__` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `mp_manager`（未显式标注）：`mp_manager` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`CameraManager`、`threading.RLock`、`threading.Lock`、`LogisticsChannelRuntime`、`frame_reader_registry.latest_frames.get`、`config_event_bus.subscribe_wildcard`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self, mp_manager):
        self.camera_manager = CameraManager(mp_manager)
        self.consumers: dict[str, BaseFunctionConsumer] = {}
        self._horn_dict: dict = {}
        self._wechat: Optional[WeChatNotifier] = None
        self._started = False
        self._feature_runtime_lock = threading.RLock()
        self._feature_states: dict[str, bool] = {}
        self._last_system_exception_alerts: dict[tuple[str, str], float] = {}
        self._system_exception_alert_lock = threading.Lock()
        self.logistics_channel_runtime = LogisticsChannelRuntime(
            channel_service=logistics_channel_service,
            dispatcher=alarm_dispatcher,
            is_camera_active=frame_reader_registry.is_active,
            frame_provider=lambda shm_name: frame_reader_registry.latest_frames.get(shm_name),
            evidence_recorder=alarm_evidence_recorder,
        )

        # 订阅配置变更事件
        config_event_bus.subscribe_wildcard(self._on_config_change)

    # ---------- 启动 / 停止 ----------

    # 功能：启动或执行 `start` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`logger.info`、`ensure_schema_compatible`、`model_service.normalize_builtin_models`、`camera_service.normalize_shm_names`、`camera_service.ensure_feature_configs`、`config_cache.init`、`system_config_service.get_feature_runtime_states`、`self._ordinary_feature_names`、`logistics_channel_service.migrate_existing_feature_cameras`、`logger.warning`
    #          等共 32 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def start(self):
        if self._started:
            return
        logger.info("=" * 20 + " Orchestrator 启动 " + "=" * 20)

        # 1) 数据库 schema 修补
        ensure_schema_compatible()
        model_service.normalize_builtin_models()
        camera_service.normalize_shm_names()
        camera_service.ensure_feature_configs(enable_all=False)
        config_cache.init()
        self._feature_states = system_config_service.get_feature_runtime_states(
            self._ordinary_feature_names()
        )
        migration = logistics_channel_service.migrate_existing_feature_cameras()
        if migration.failed:
            logger.warning(
                f"[Orchestrator] 物流通道迁移存在失败 created={migration.created} "
                f"skipped={migration.skipped} failed={migration.failed} "
                f"errors={migration.errors}"
            )
        else:
            logger.info(
                f"[Orchestrator] 物流通道迁移完成 created={migration.created} "
                f"skipped={migration.skipped}"
            )

        # 2) 企微客户端先初始化,摄像头启动异常可直接推送
        if settings.alarm.wechat_enable:
            self._wechat = WeChatNotifier()
            self.camera_manager.configure_runtime_alerts(self._send_system_exception_alert)
            inference_manager.configure_runtime_alerts(self._send_system_exception_alert)
        else:
            self.camera_manager.configure_runtime_alerts(None)
            inference_manager.configure_runtime_alerts(None)

        # 3) 摄像头进程
        cameras = camera_service.list_cameras()
        models = model_service.list_models(enabled_only=True)
        cleanup_count = cleanup_aivision_residual_processes(
            camera_shm_names=[c["shm_name"] for c in cameras],
            camera_urls=[c["url"] for c in cameras],
            model_names=[m["name"] for m in models],
        )
        if cleanup_count:
            logger.warning(f"[Orchestrator] 启动前已清理 {cleanup_count} 个 AiVision 残留进程")

        # 转成 CameraManager 期望的格式(把功能配置展平后传)
        cam_configs = []
        for c in cameras:
            functions = c.get("functions") or {}
            cam_configs.append({
                "name": c["name"],
                "shm_name": c["shm_name"],
                "url": c["url"],
                "fps": c["fps"],
                "max_restart": c["max_restart"],
                "enable": bool(c["enabled"]) and self._has_active_function(functions),
                "shape": c.get("shape") or [1080, 1920, 3],
            })
        self.camera_manager.initialize_configs(cam_configs)
        self.camera_manager.start_all()
        frame_reader_registry.start_all()
        alarm_evidence_recorder.set_status_callback(violation_writer.update_video_status)
        alarm_evidence_recorder.start(lambda: frame_reader_registry.latest_frames)

        # 4) 违规图片写入
        violation_writer.start()

        # 5) 告警通道
        self._horn_dict = horn_service.load_runtime_instances()
        alarm_dispatcher.configure(
            horn_dict=self._horn_dict,
            wechat=self._wechat,
            violation_writer=violation_writer,
            evidence_recorder=alarm_evidence_recorder,
        )

        # 6) 推理 Worker 进程
        inference_manager.initialize_queues()
        inference_manager.start_all()

        # 7) Feature Consumers
        self.logistics_channel_runtime.start()
        self._start_consumers()

        self._started = True
        logger.info("=" * 20 + " Orchestrator 启动完成 " + "=" * 20)

    # 功能：停止并释放 `stop` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`logger.info`、`list`、`self.consumers.items`、`consumer.stop`、`logger.warning`、`self.consumers.clear`、`self.logistics_channel_runtime.stop`、`inference_manager.stop_all`、`self._horn_dict.values`、`horn.stop_heartbeat`
    #          等共 16 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；可能创建、写入、移动或删除本地文件；会向日志系统输出运行或异常信息。
    def stop(self):
        if not self._started:
            return
        logger.info("=" * 20 + " Orchestrator 停止 " + "=" * 20)

        # 逆序停止
        for name, consumer in list(self.consumers.items()):
            try:
                consumer.stop()
            except Exception as e:
                logger.warning(f"[Orchestrator] 停止 Consumer {name} 失败: {e}")
        self.consumers.clear()
        try:
            self.logistics_channel_runtime.stop()
        except Exception as e:
            logger.warning(f"[Orchestrator] 停止物流通道运行时失败，将继续清理其余资源: {e}")

        try:
            inference_manager.stop_all()
        except Exception as e:
            logger.warning(f"[Orchestrator] 停止推理失败: {e}")

        for horn in self._horn_dict.values():
            try:
                horn.stop_heartbeat()
            except Exception:
                pass
        self._horn_dict.clear()

        try:
            alarm_evidence_recorder.stop()
        except Exception:
            pass

        try:
            violation_writer.stop()
        except Exception:
            pass

        try:
            frame_reader_registry.stop_all()
        except Exception:
            pass

        try:
            self.camera_manager.stop_all()
        except Exception:
            pass

        from core.db import dispose
        dispose()

        self._started = False
        logger.info("=" * 20 + " Orchestrator 已停止 " + "=" * 20)

    # ---------- Consumer 启动 ----------

    # 功能：启动或执行 `_start_consumers` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::start` 调用本符号；`AiVision/tests/test_orchestrator_camera_update.py`
    #         的 `test_start_consumers_injects_runtime_only_into_logistics_features`
    #         调用本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的
    #         `test_start_consumers_skips_persistently_disabled_ordinary_feature` 调用本符号
    #   - 内部调用：`all_specs().items`、`all_specs`、`self._is_feature_desired_enabled`、`logger.info`、`self._start_consumer`、`logger.exception`、`self._send_system_exception_alert`、`len`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；会向日志系统输出运行或异常信息。
    def _start_consumers(self):
        for name, spec in all_specs().items():
            if name not in LOGISTICS_FEATURES and not self._is_feature_desired_enabled(name):
                logger.info(f"[Orchestrator] 检测能力已关闭，跳过 Consumer '{name}'")
                continue
            try:
                self._start_consumer(name, spec)
            except Exception:
                logger.exception(f"[Orchestrator] 启动 Consumer {name} 失败")
                self._send_system_exception_alert(
                    target_name=name,
                    target_key=name,
                    event_type="功能启动异常",
                    detail=f"Consumer {name} 启动失败",
                )

        logger.info(f"[Orchestrator] 已启动 {len(self.consumers)} 个 Consumer")

    # 功能：创建并启动一个 Consumer；依赖模型不可用时明确失败；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `name`（str）：业务对象名称
    #   - `spec`（未显式标注）：`spec` 对应的业务输入值；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_start_consumers` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::set_feature_enabled` 调用本符号
    #   - 内部调用：`all_specs().get`、`all_specs`、`ValueError`、`set`、`inference_manager.list_running`、`RuntimeError`、`',
    #          '.join`、`sorted`、`dict`、`spec.consumer_cls` 等共 11 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    def _start_consumer(self, name: str, spec=None):
        """创建并启动一个 Consumer；依赖模型不可用时明确失败。"""
        if name in self.consumers and self.consumers[name].running:
            return self.consumers[name]
        spec = spec or all_specs().get(name)
        if spec is None:
            raise ValueError(f"未知检测能力: {name}")

        running_models = set(inference_manager.list_running())
        missing = [model for model in spec.required_models if model not in running_models]
        if missing:
            raise RuntimeError(
                f"依赖模型未启动: {', '.join(missing)}; "
                f"当前运行模型: {', '.join(sorted(running_models)) or '无'}"
            )

        consumer_kwargs = dict(
            spec=spec,
            infer_dict=inference_manager.infer_queues,
            result_queue=inference_manager.result_queues[name],
            latest_frames=frame_reader_registry.latest_frames,
            is_camera_active=frame_reader_registry.is_active,
            runtime_alert_handler=self._send_system_exception_alert,
        )
        if name in LOGISTICS_FEATURES:
            consumer_kwargs["logistics_runtime"] = self.logistics_channel_runtime
        consumer = spec.consumer_cls(**consumer_kwargs)
        consumer.start()
        self.consumers[name] = consumer
        return consumer

    # 功能：启停普通检测能力，并保存重启后的期望状态；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    #   - `enabled`（bool）：是否启用相应能力
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_orchestrator_camera_update.py` 的
    #         `test_feature_stop_persists_state_and_keeps_shared_camera_running`
    #         调用本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的 `test_logistics_feature_cannot_use_global_runtime_switch`
    #         调用本符号；`AiVision/api/v2/runtime.py` 的 `_set_capability_state` 调用本符号
    #   - 内部调用：`self._ordinary_specs().get`、`self._ordinary_specs`、`ValueError`、`bool`、`system_config_service.save_feature_runtime_state`、`self._start_consumer`、`self.consumers.pop`、`consumer.stop`、`self._reconcile_feature_cameras`、`self.get_feature_runtime_status`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def set_feature_enabled(self, feature_name: str, enabled: bool) -> dict:
        """启停普通检测能力，并保存重启后的期望状态。"""
        spec = self._ordinary_specs().get(feature_name)
        if spec is None:
            if feature_name in LOGISTICS_FEATURES:
                raise ValueError("物流通道检测请在通道管理中启用或停用")
            raise ValueError(f"未知检测能力: {feature_name}")

        with self._feature_runtime_lock:
            desired = bool(enabled)
            system_config_service.save_feature_runtime_state(feature_name, desired)
            self._feature_states[feature_name] = desired

            error: RuntimeError | None = None
            if desired:
                try:
                    self._start_consumer(feature_name, spec)
                except RuntimeError as exc:
                    error = exc
            else:
                consumer = self.consumers.pop(feature_name, None)
                if consumer is not None:
                    consumer.stop()

            self._reconcile_feature_cameras(feature_name)
            if error is not None:
                raise error
            return self.get_feature_runtime_status(feature_name)

    # 功能：读取或查询 `get_feature_runtime_status` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::set_feature_enabled` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::list_feature_runtime_statuses` 调用本符号
    #   - 内部调用：`self._ordinary_specs().get`、`self._ordinary_specs`、`ValueError`、`self._is_feature_desired_enabled`、`self.consumers.get`、`bool`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def get_feature_runtime_status(self, feature_name: str) -> dict:
        spec = self._ordinary_specs().get(feature_name)
        if spec is None:
            raise ValueError(f"未知检测能力: {feature_name}")
        desired = self._is_feature_desired_enabled(feature_name)
        consumer = self.consumers.get(feature_name)
        running = bool(consumer is not None and consumer.running)
        return {
            "feature": feature_name,
            "display_name": spec.display_name,
            "enabled": desired,
            "running": running,
            "state": "running" if running else ("error" if desired else "stopped"),
        }

    # 功能：读取或查询 `list_feature_runtime_statuses` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::runtime_status` 调用本符号；`AiVision/api/v2/runtime.py` 的
    #         `list_capabilities` 调用本符号
    #   - 内部调用：`self.get_feature_runtime_status`、`self._ordinary_specs`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_feature_runtime_statuses(self) -> list[dict]:
        return [
            self.get_feature_runtime_status(name)
            for name in self._ordinary_specs()
        ]

    # 功能：实现 `_ordinary_specs` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::set_feature_enabled` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::get_feature_runtime_status` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::list_feature_runtime_statuses` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::_ordinary_feature_names` 调用本符号
    #   - 内部调用：`all_specs().items`、`all_specs`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _ordinary_specs() -> dict:
        return {
            name: spec
            for name, spec in all_specs().items()
            if name not in LOGISTICS_FEATURES
        }

    # 功能：实现 `_ordinary_feature_names` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    # 返回：tuple[str, ...]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::start` 调用本符号
    #   - 内部调用：`tuple`、`cls._ordinary_specs`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @classmethod
    def _ordinary_feature_names(cls) -> tuple[str, ...]:
        return tuple(cls._ordinary_specs())

    # 功能：检查或判断 `_is_feature_desired_enabled` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_start_consumers` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::get_feature_runtime_status` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::_has_active_function` 调用本符号
    #   - 内部调用：`bool`、`getattr(self, '_feature_states', {}).get`、`getattr`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _is_feature_desired_enabled(self, feature_name: str) -> bool:
        return bool(getattr(self, "_feature_states", {}).get(feature_name, True))

    # 功能：检查或判断 `_has_active_function` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `functions`（dict）：`functions` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::start` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::_camera_runtime_config` 调用本符号
    #   - 内部调用：`functions.items`、`self._is_feature_desired_enabled`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _has_active_function(self, functions: dict) -> bool:
        for feature_name, configured in functions.items():
            if not configured:
                continue
            if feature_name in LOGISTICS_FEATURES or self._is_feature_desired_enabled(feature_name):
                return True
        return False

    # 功能：实现 `_reconcile_feature_cameras` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature_name`（str）：`feature_name` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::set_feature_enabled` 调用本符号
    #   - 内部调用：`camera_service.list_cameras`、`(camera.get('functions') or {}).get`、`camera.get`、`self._reconcile_camera_runtime`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _reconcile_feature_cameras(self, feature_name: str):
        for camera in camera_service.list_cameras():
            if not (camera.get("functions") or {}).get(feature_name):
                continue
            self._reconcile_camera_runtime(camera["shm_name"])

    # 功能：实现 `_reconcile_camera_runtime` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_reconcile_feature_cameras` 调用本符号
    #   - 内部调用：`self._camera_runtime_config`、`self.camera_manager.update_camera_config`、`self.camera_manager.is_running`、`cfg.get`、`self.camera_manager.start_camera`、`self.camera_manager.stop_camera`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def _reconcile_camera_runtime(self, key: str):
        cfg = self._camera_runtime_config(key)
        if cfg is None:
            return
        shm_name = cfg["shm_name"]
        self.camera_manager.update_camera_config(shm_name, cfg)
        running = self.camera_manager.is_running(shm_name)
        if cfg.get("enable") and not running:
            self.camera_manager.start_camera(shm_name)
        elif not cfg.get("enable") and running:
            self.camera_manager.stop_camera(shm_name)

    # ---------- 配置变更事件路由 ----------

    # 功能：处理 `_on_config_change` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event`（ConfigChangeEvent）：待处理的事件对象
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_orchestrator_camera_update.py` 的 `test_camera_display_update_does_not_restart_runtime`
    #         调用本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的 `test_camera_runtime_update_restarts_runtime`
    #         调用本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的
    #         `test_camera_remove_refreshes_logistics_runtime_before_removal`
    #         调用本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的
    #         `test_prefixed_logistics_feature_event_reaches_exact_consumer` 调用本符号；另有 2 处静态调用
    #   - 内部调用：`value.get`、`self.logistics_channel_runtime.refresh_channel`、`int`、`self._start_or_update_camera`、`self.logistics_channel_runtime.refresh_camera_all`、`self._camera_update_requires_restart`、`self._restart_or_stop_camera`、`self._refresh_consumer_camera_config`、`logger.info`、`self.camera_manager.remove_camera_config`
    #          等共 18 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _on_config_change(self, event: ConfigChangeEvent):
        change = event.change_type
        cam_id = event.camera_id

        if change == "logistics_channel_updated":
            value = event.new_value or {}
            feature_name = value.get("feature_name")
            channel_id = value.get("channel_id")
            if feature_name in LOGISTICS_FEATURES and channel_id is not None:
                self.logistics_channel_runtime.refresh_channel(
                    feature_name,
                    int(channel_id),
                )
            return

        # 摄像头层面
        if change == "camera_added":
            self._start_or_update_camera(event.camera_name)
            return
        if change == "camera_updated":
            if cam_id is not None:
                self.logistics_channel_runtime.refresh_camera_all(cam_id)
            if self._camera_update_requires_restart(event):
                self._restart_or_stop_camera(event.camera_name)
            else:
                self._refresh_consumer_camera_config(cam_id)
                logger.info(f"[Orchestrator] 摄像头展示信息已热更新 cam_id={cam_id} shm={event.camera_name}")
            return
        if change == "camera_removed":
            if cam_id is not None:
                self.logistics_channel_runtime.refresh_camera_all(cam_id)
            self.camera_manager.remove_camera_config(event.camera_name)
            logger.info(f"[Orchestrator] 摄像头已热移除 cam_id={cam_id} shm={event.camera_name}")
            return

        # 功能层面: 解析 "{feature}_{action}"
        # 形如 blocks_enabled / detect_face_config_updated
        # 功能名可能存在前缀关系（例如 detect_logistics_single_person 与其
        # 各事业部变体），必须优先匹配最长名称，避免事件被短名称截获。
        for fname in sorted(all_specs(), key=len, reverse=True):
            if change.startswith(f"{fname}_"):
                action = change[len(fname) + 1:]
                if (
                    fname in LOGISTICS_FEATURES
                    and action not in ("enabled", "disabled")
                    and cam_id is not None
                ):
                    self.logistics_channel_runtime.refresh_camera(fname, cam_id)
                consumer = self.consumers.get(fname)
                if consumer is None:
                    return
                if action in ("enabled", "disabled"):
                    consumer.update_status(cam_id, action == "enabled")
                    self._restart_or_stop_camera(event.camera_name)
                else:  # config_updated, alarm_updated, ...
                    consumer.update_config(cam_id)
                return

    # 功能：更新或保存 `_camera_update_requires_restart` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `event`（ConfigChangeEvent）：待处理的事件对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_on_config_change` 调用本符号
    #   - 内部调用：`old_value.get`、`new_value.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _camera_update_requires_restart(event: ConfigChangeEvent) -> bool:
        old_value = event.old_value or {}
        new_value = event.new_value or {}
        if not old_value or not new_value:
            return True

        for field in _CAMERA_RUNTIME_FIELDS:
            if old_value.get(field) != new_value.get(field):
                return True
        return False

    # 功能：实现 `_refresh_consumer_camera_config` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int | None）：摄像头唯一标识
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_on_config_change` 调用本符号
    #   - 内部调用：`self.consumers.values`、`consumer.update_config`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _refresh_consumer_camera_config(self, camera_id: int | None):
        if camera_id is None:
            return
        for consumer in self.consumers.values():
            try:
                consumer.update_config(camera_id)
            except Exception as e:
                logger.warning(f"[Orchestrator] 刷新 Consumer 摄像头展示信息失败 cam_id={camera_id}: {e}")

    # 功能：实现 `_camera_runtime_config` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_reconcile_camera_runtime`
    #         调用本符号；`AiVision/platform/orchestrator.py` 的 `Orchestrator::_start_or_update_camera`
    #         调用本符号；`AiVision/platform/orchestrator.py` 的 `Orchestrator::_restart_or_stop_camera` 调用本符号
    #   - 内部调用：`camera_service.get_camera`、`logger.warning`、`camera.get`、`bool`、`self._has_active_function`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _camera_runtime_config(self, key: str) -> dict | None:
        camera = camera_service.get_camera(key)
        if camera is None:
            logger.warning(f"[Orchestrator] 摄像头配置不存在: {key}")
            return None
        functions = camera.get("functions") or {}
        return {
            "name": camera["name"],
            "shm_name": camera["shm_name"],
            "url": camera["url"],
            "fps": camera["fps"],
            "max_restart": camera["max_restart"],
            "enable": bool(camera["enabled"]) and self._has_active_function(functions),
            "shape": camera.get("shape") or [1080, 1920, 3],
        }

    # 功能：发送或分发 `_send_system_exception_alert` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `target_name`（str）：`target_name` 对应的业务输入值
    #   - `target_key`（str）：`target_key` 对应的业务输入值
    #   - `event_type`（str）：事件类型标识
    #   - `detail`（str）：`detail` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_start_consumers` 调用本符号；`AiVision/platform/orchestrator.py` 的
    #         `Orchestrator::runtime_status` 调用本符号；`AiVision/tests/test_orchestrator_camera_update.py` 的
    #         `test_camera_runtime_alert_types_share_one_repeat_interval` 调用本符号
    #   - 内部调用：`system_config_service.get_exception_alert`、`alert.get`、`str(alert.get('wechat_user') or
    #          '').strip`、`str`、`time.time`、`self._system_exception_alert_group`、`float`、`self._last_system_exception_alerts.get`、`time.strftime`、`self._wechat.send_text`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    def _send_system_exception_alert(self, target_name: str, target_key: str, event_type: str, detail: str):
        if self._wechat is None:
            return
        alert = system_config_service.get_exception_alert()
        if not alert.get("wechat_enable"):
            return
        recipients = str(alert.get("wechat_user") or "").strip()
        if not recipients:
            return
        now = time.time()
        alert_group = self._system_exception_alert_group(event_type)
        alert_key = (target_key, alert_group)
        cooldown_seconds = float(alert["repeat_interval_minutes"]) * 60.0
        with self._system_exception_alert_lock:
            last = self._last_system_exception_alerts.get(alert_key, 0.0)
            if now - last < cooldown_seconds:
                return
            self._last_system_exception_alerts[alert_key] = now
        now_text = time.strftime("%Y-%m-%d %H:%M:%S")
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

    # 功能：实现 `_system_exception_alert_group` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `event_type`（str）：事件类型标识
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_send_system_exception_alert` 调用本符号
    #   - 内部调用：`event_type.startswith`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    @staticmethod
    def _system_exception_alert_group(event_type: str) -> str:
        if event_type in _CAMERA_RUNTIME_ALERT_TYPES:
            return "摄像头运行异常"
        if event_type.startswith("采集进程退出") or event_type.startswith("画面停更"):
            return "摄像头运行异常"
        return event_type

    # 功能：更新或保存 `_start_or_update_camera` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_on_config_change` 调用本符号
    #   - 内部调用：`self._camera_runtime_config`、`self.camera_manager.update_camera_config`、`cfg.get`、`self.camera_manager.stop_camera`、`logger.info`、`self.camera_manager.start_camera`、`logger.warning`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _start_or_update_camera(self, key: str):
        cfg = self._camera_runtime_config(key)
        if cfg is None:
            return
        shm_name = cfg["shm_name"]
        self.camera_manager.update_camera_config(shm_name, cfg)
        if not cfg.get("enable", True):
            self.camera_manager.stop_camera(shm_name)
            logger.info(f"[Orchestrator] 摄像头已禁用,未启动 shm={shm_name}")
            return
        ok = self.camera_manager.start_camera(shm_name)
        if ok:
            logger.info(f"[Orchestrator] 摄像头已热启动 shm={shm_name}")
        else:
            logger.warning(f"[Orchestrator] 摄像头热启动失败 shm={shm_name}")

    # 功能：停止并释放 `_restart_or_stop_camera` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `key`（str）：用于查询、分组或缓存的键
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::_on_config_change` 调用本符号
    #   - 内部调用：`self._camera_runtime_config`、`self.camera_manager.stop_camera`、`self.camera_manager.update_camera_config`、`cfg.get`、`logger.info`、`self.camera_manager.start_camera`、`logger.warning`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _restart_or_stop_camera(self, key: str):
        cfg = self._camera_runtime_config(key)
        if cfg is None:
            return
        shm_name = cfg["shm_name"]
        self.camera_manager.stop_camera(shm_name)
        self.camera_manager.update_camera_config(shm_name, cfg)
        if not cfg.get("enable", True):
            logger.info(f"[Orchestrator] 摄像头已热停止 shm={shm_name}")
            return
        ok = self.camera_manager.start_camera(shm_name)
        if ok:
            logger.info(f"[Orchestrator] 摄像头已热重启 shm={shm_name}")
        else:
            logger.warning(f"[Orchestrator] 摄像头热重启失败 shm={shm_name}")

    # ---------- API 用查询接口 ----------

    # 功能：获取摄像头画面 — 优先取 feature 标注后的帧,无则取原始帧；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `feature`（str | None）：`feature` 对应的业务输入值；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.get_camera_frame_info`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera_frame(self, shm_name: str, feature: str | None = None):
        """获取摄像头画面 — 优先取 feature 标注后的帧,无则取原始帧"""
        frame, _updated_at = self.get_camera_frame_info(shm_name, feature=feature)
        return frame

    # 功能：获取摄像头画面及更新时间,用于 API 层复用 JPEG 编码结果；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `feature`（str | None）：`feature` 对应的业务输入值；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/orchestrator.py` 的 `Orchestrator::get_camera_frame` 调用本符号
    #   - 内部调用：`time.time`、`frame_reader_registry.latest_frames.get`、`frame_reader_registry.latest_frame_times.get`、`consumer.result_dict.get`、`consumer.result_updated_at.get`、`max`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_camera_frame_info(self, shm_name: str, feature: str | None = None):
        """获取摄像头画面及更新时间,用于 API 层复用 JPEG 编码结果。"""
        now = time.time()
        raw = frame_reader_registry.latest_frames.get(shm_name)
        raw_updated_at = frame_reader_registry.latest_frame_times.get(shm_name, 0.0)
        raw_is_fresh = raw is not None and raw_updated_at > 0 and now - raw_updated_at <= 10.0
        annotated_updated_at = 0.0
        if feature and feature in self.consumers:
            consumer = self.consumers[feature]
            annotated = consumer.result_dict.get(shm_name)
            annotated_updated_at = consumer.result_updated_at.get(shm_name, 0.0)
            annotated_is_fresh = (
                annotated is not None
                and annotated_updated_at > 0
                and now - annotated_updated_at <= _ANNOTATED_FRAME_FRESH_SECONDS
            )
            if annotated_is_fresh:
                return annotated, annotated_updated_at
        if raw_is_fresh:
            return raw, raw_updated_at
        return (
            None,
            max(raw_updated_at, annotated_updated_at),
        )

    # 功能：Return the latest display-only feature snapshot for one camera；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `shm_name`（str）：摄像头共享内存名称
    #   - `feature`（str）：`feature` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`set`、`self.camera_manager.list_running`、`self.consumers.get`、`getattr`、`callable`、`getter`、`float`、`snapshot.get`、`bool`、`time.time`
    #          等共 14 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_feature_monitor_status(self, shm_name: str, feature: str) -> dict:
        """Return the latest display-only feature snapshot for one camera."""
        online = shm_name in set(self.camera_manager.list_running())
        consumer = self.consumers.get(feature)
        getter = getattr(consumer, "get_monitor_status", None)
        snapshot = getter(shm_name) if callable(getter) else None
        updated_at_s = float(snapshot.get("updated_at_s") or 0.0) if snapshot else 0.0
        fresh = bool(
            snapshot
            and updated_at_s > 0
            and time.time() - updated_at_s <= _ANNOTATED_FRAME_FRESH_SECONDS
        )

        if not fresh:
            return {
                "camera_key": shm_name,
                "feature": feature,
                "online": online,
                "count": None,
                "alarm": False,
                "reason": "unknown",
                "duration_seconds": None,
                "threshold_seconds": None,
                "updated_at": None,
            }

        updated_at = dt.datetime.fromtimestamp(
            updated_at_s,
            tz=dt.timezone.utc,
        ).astimezone().isoformat()
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
        }

    # 功能：获取物流通道的最新聚合状态；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（str）：`feature` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：dict | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.logistics_channel_runtime.get_channel_status`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_logistics_channel_status(self, feature: str, channel_id: int) -> dict | None:
        """获取物流通道的最新聚合状态。"""
        return self.logistics_channel_runtime.get_channel_status(feature, channel_id)

    # 功能：获取物流通道的最新拼接标注画面；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（str）：`feature` 对应的业务输入值
    #   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.logistics_channel_runtime.get_channel_frame`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def get_logistics_channel_frame(self, feature: str, channel_id: int):
        """获取物流通道的最新拼接标注画面。"""
        return self.logistics_channel_runtime.get_channel_frame(feature, channel_id)

    # 功能：实现 `runtime_status` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`inference_manager.list_running`、`set`、`consumer.inference_status`、`self.consumers.items`、`callable`、`getattr`、`all`、`self._send_system_exception_alert`、`self.camera_manager.list_running`、`inference_manager.runtime_status`
    #          等共 11 个调用。
    # 副作用/注意事项：可能发起网络请求或发送外部消息。
    def runtime_status(self) -> dict:
        running_models = inference_manager.list_running()
        running_model_set = set(running_models)
        consumer_inference = {
            name: consumer.inference_status()
            for name, consumer in self.consumers.items()
            if callable(getattr(consumer, "inference_status", None))
        }
        running_consumers = [
            name
            for name, consumer in self.consumers.items()
            if consumer.running and all(model in running_model_set for model in consumer.spec.required_models)
        ]
        for name, consumer in self.consumers.items():
            if not consumer.running:
                self._send_system_exception_alert(
                    target_name=name,
                    target_key=name,
                    event_type="功能线程退出",
                    detail=f"Consumer {name} 已不在运行状态",
                )
        return {
            "started": self._started,
            "running_cameras": self.camera_manager.list_running(),
            "running_models": running_models,
            "running_consumers": running_consumers,
            "inference": {
                "workers": inference_manager.runtime_status(),
                "consumers": consumer_inference,
            },
            "capabilities": self.list_feature_runtime_statuses(),
        }


# 单例 — 由 main.py 启动时实例化(因为需要传入 mp_manager)
orchestrator: Optional[Orchestrator] = None


# 功能：读取或查询 `get_orchestrator` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：Orchestrator；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/deps.py` 的 `get_current_orchestrator` 调用本符号
#   - 内部调用：`RuntimeError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def get_orchestrator() -> Orchestrator:
    if orchestrator is None:
        raise RuntimeError("Orchestrator 未初始化,请先在 main.py 调用 init_orchestrator()")
    return orchestrator


# 功能：初始化或配置 `init_orchestrator` 对应的`orchestrator` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `mp_manager`（未显式标注）：`mp_manager` 对应的业务输入值
# 返回：Orchestrator；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Orchestrator`。
# 副作用/注意事项：会修改全局或闭包状态。
def init_orchestrator(mp_manager) -> Orchestrator:
    global orchestrator
    if orchestrator is None:
        orchestrator = Orchestrator(mp_manager)
    return orchestrator
