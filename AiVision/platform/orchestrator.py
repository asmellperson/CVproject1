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
from platform.alarm_device.service import horn_service
from platform.violation.service import violation_writer


_CAMERA_RUNTIME_FIELDS = ("url", "fps", "max_restart", "enabled", "enable")
_ANNOTATED_FRAME_FRESH_SECONDS = 2.0


class Orchestrator:
    """系统总编排器"""

    def __init__(self, mp_manager):
        self.camera_manager = CameraManager(mp_manager)
        self.consumers: dict[str, BaseFunctionConsumer] = {}
        self._horn_dict: dict = {}
        self._wechat: Optional[WeChatNotifier] = None
        self._started = False
        self._last_system_exception_alerts: dict[tuple[str, str], float] = {}
        self._system_exception_alert_cooldown = 300.0

        # 订阅配置变更事件
        config_event_bus.subscribe_wildcard(self._on_config_change)

    # ---------- 启动 / 停止 ----------

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
                "enable": bool(c["enabled"]) and any(bool(v) for v in functions.values()),
                "shape": c.get("shape") or [1080, 1920, 3],
            })
        self.camera_manager.initialize_configs(cam_configs)
        self.camera_manager.start_all()
        frame_reader_registry.start_all()

        # 4) 违规图片写入
        violation_writer.start()

        # 5) 告警通道
        self._horn_dict = horn_service.load_runtime_instances()
        alarm_dispatcher.configure(
            horn_dict=self._horn_dict,
            wechat=self._wechat,
            violation_writer=violation_writer,
        )

        # 6) 推理 Worker 进程
        inference_manager.initialize_queues()
        inference_manager.start_all()

        # 7) Feature Consumers
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
                    runtime_alert_handler=self._send_system_exception_alert,
                )
                consumer.start()
                self.consumers[name] = consumer
            except Exception:
                logger.exception(f"[Orchestrator] 启动 Consumer {name} 失败")
                self._send_system_exception_alert(
                    target_name=name,
                    target_key=name,
                    event_type="功能启动异常",
                    detail=f"Consumer {name} 启动失败",
                )

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
            if self._camera_update_requires_restart(event):
                self._restart_or_stop_camera(event.camera_name)
            else:
                self._refresh_consumer_camera_config(cam_id)
                logger.info(f"[Orchestrator] 摄像头展示信息已热更新 cam_id={cam_id} shm={event.camera_name}")
            return
        if change == "camera_removed":
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
                consumer = self.consumers.get(fname)
                if consumer is None:
                    return
                if action in ("enabled", "disabled"):
                    consumer.update_status(cam_id, action == "enabled")
                    self._restart_or_stop_camera(event.camera_name)
                else:  # config_updated, alarm_updated, ...
                    consumer.update_config(cam_id)
                return

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

    def _refresh_consumer_camera_config(self, camera_id: int | None):
        if camera_id is None:
            return
        for consumer in self.consumers.values():
            try:
                consumer.update_config(camera_id)
            except Exception as e:
                logger.warning(f"[Orchestrator] 刷新 Consumer 摄像头展示信息失败 cam_id={camera_id}: {e}")

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
        alert_key = (target_key, event_type)
        last = self._last_system_exception_alerts.get(alert_key, 0.0)
        if now - last < self._system_exception_alert_cooldown:
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
            "updated_at": updated_at,
        }

    def runtime_status(self) -> dict:
        running_models = inference_manager.list_running()
        running_model_set = set(running_models)
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
