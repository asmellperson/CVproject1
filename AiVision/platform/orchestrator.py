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
import time
from typing import Optional

from core.logger import logger
from core.cache import config_cache
from core.db import ensure_schema_compatible
from core.events import config_event_bus, ConfigChangeEvent
from core.alarm.dispatcher import alarm_dispatcher
from core.alarm.wechat import WeChatNotifier
from core.settings import settings

from features import all_specs
from features._base.consumer import BaseFunctionConsumer

from platform.camera.manager import CameraManager
from platform.camera.frame_reader import frame_reader_registry
from platform.camera.service import camera_service
from platform.inference.manager import inference_manager
from platform.alarm_device.service import horn_service
from platform.violation.service import violation_writer


class Orchestrator:
    """系统总编排器"""

    def __init__(self, mp_manager):
        self.camera_manager = CameraManager(mp_manager)
        self.consumers: dict[str, BaseFunctionConsumer] = {}
        self._horn_dict: dict = {}
        self._wechat: Optional[WeChatNotifier] = None
        self._started = False

        # 订阅配置变更事件
        config_event_bus.subscribe_wildcard(self._on_config_change)

    # ---------- 启动 / 停止 ----------

    def start(self):
        if self._started:
            return
        logger.info("=" * 20 + " Orchestrator 启动 " + "=" * 20)

        # 1) 数据库 schema 修补
        ensure_schema_compatible()
        # 确保部门种子数据
        from platform.department.service import department_service
        from core.db import session_scope
        with session_scope() as s:
            department_service.ensure_seed_data(s)
        camera_service.normalize_shm_names()
        camera_service.ensure_feature_configs(enable_all=False)
        config_cache.init()

        # 2) 摄像头进程
        cameras = camera_service.list_cameras()
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
                "enable": bool(c["enabled"]) and any(bool(v) for v in functions.values()),
                "shape": c.get("shape") or [1080, 1920, 3],
            })
        self.camera_manager.initialize_configs(cam_configs)
        self.camera_manager.start_all()
        frame_reader_registry.start_all()

        # 3) 违规图片写入
        violation_writer.start()

        # 4) 告警通道
        self._horn_dict = horn_service.load_runtime_instances()
        if settings.alarm.wechat_enable:
            self._wechat = WeChatNotifier()
        alarm_dispatcher.configure(
            horn_dict=self._horn_dict,
            wechat=self._wechat,
            violation_writer=violation_writer,
        )

        # 5) 推理 Worker 进程
        inference_manager.initialize_queues()
        inference_manager.start_all()

        # 6) Feature Consumers
        self._start_consumers()

        self._started = True
        logger.info("=" * 20 + " Orchestrator 启动完成 " + "=" * 20)

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

    def _start_consumers(self):
        for name, spec in all_specs().items():
            # 检查依赖的模型是否都启动了
            running_models = set(inference_manager.list_running())
            missing = [m for m in spec.required_models if m not in running_models]
            if missing:
                logger.warning(
                    f"[Orchestrator] 跳过 Consumer '{name}': 依赖模型未启动 {missing} "
                    f"(已启动: {sorted(running_models)})"
                )
                continue

            try:
                consumer = spec.consumer_cls(
                    spec=spec,
                    infer_dict=inference_manager.infer_queues,
                    result_queue=inference_manager.result_queues[name],
                    latest_frames=frame_reader_registry.latest_frames,
                    is_camera_active=frame_reader_registry.is_active,
                )
                consumer.start()
                self.consumers[name] = consumer
            except Exception:
                logger.exception(f"[Orchestrator] 启动 Consumer {name} 失败")

        logger.info(f"[Orchestrator] 已启动 {len(self.consumers)} 个 Consumer")

    # ---------- 配置变更事件路由 ----------

    def _on_config_change(self, event: ConfigChangeEvent):
        change = event.change_type
        cam_id = event.camera_id

        # 摄像头层面
        if change == "camera_added":
            self._start_or_update_camera(event.camera_name)
            return
        if change == "camera_updated":
            self._restart_or_stop_camera(event.camera_name)
            return
        if change == "camera_removed":
            self.camera_manager.stop_camera(event.camera_name)
            logger.info(f"[Orchestrator] 摄像头已热移除 cam_id={cam_id} shm={event.camera_name}")
            return

        # 功能层面: 解析 "{feature}_{action}"
        # 形如 blocks_enabled / detect_face_config_updated
        for fname in all_specs():
            if change.startswith(f"{fname}_"):
                action = change[len(fname) + 1:]
                consumer = self.consumers.get(fname)
                if consumer is None:
                    return
                if action in ("enabled", "disabled"):
                    consumer.update_status(cam_id, action == "enabled")
                    self._restart_or_stop_camera(event.camera_name)
                else:  # config_updated, alarm_updated, ...
                    consumer.update_config(cam_id)
                return

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
            "enable": bool(camera["enabled"]) and any(bool(v) for v in functions.values()),
            "shape": camera.get("shape") or [1080, 1920, 3],
        }

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

    def get_camera_frame(self, shm_name: str, feature: str | None = None):
        """获取摄像头画面 — 优先取 feature 标注后的帧,无则取原始帧"""
        frame, _updated_at = self.get_camera_frame_info(shm_name, feature=feature)
        return frame

    def get_camera_frame_info(self, shm_name: str, feature: str | None = None):
        """获取摄像头画面及更新时间,用于 API 层复用 JPEG 编码结果。"""
        if feature and feature in self.consumers:
            consumer = self.consumers[feature]
            annotated = consumer.result_dict.get(shm_name)
            updated_at = consumer.result_updated_at.get(shm_name, 0.0)
            if annotated is not None:
                raw = frame_reader_registry.latest_frames.get(shm_name)
                if raw is None or time.time() - updated_at <= 2.0:
                    return annotated, updated_at
        return (
            frame_reader_registry.latest_frames.get(shm_name),
            frame_reader_registry.latest_frame_times.get(shm_name, 0.0),
        )

    def runtime_status(self) -> dict:
        return {
            "started": self._started,
            "running_cameras": self.camera_manager.list_running(),
            "running_models": inference_manager.list_running(),
            "running_consumers": list(self.consumers.keys()),
        }


# 单例 — 由 main.py 启动时实例化(因为需要传入 mp_manager)
orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    if orchestrator is None:
        raise RuntimeError("Orchestrator 未初始化,请先在 main.py 调用 init_orchestrator()")
    return orchestrator


def init_orchestrator(mp_manager) -> Orchestrator:
    global orchestrator
    if orchestrator is None:
        orchestrator = Orchestrator(mp_manager)
    return orchestrator
