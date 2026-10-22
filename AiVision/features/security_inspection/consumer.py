"""消费平台视频帧与人体推理结果，维护逐路安检状态。"""

import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from AiVision.alarms.dispatcher import AlarmEvidenceRequest, alarm_dispatcher
from AiVision.core.settings import settings
from AiVision.features._shared.consumer import BaseFunctionConsumer, SubmittedInference
from AiVision.features._shared.roi import roi_to_pixels
from AiVision.features.guard_behavior.tracking import CameraByteTracker
from .evidence import InspectionSessionEvidence, build_evidence_image, encode_evidence_image
from .runtime import InspectionRuntime, InspectionTask
from .schema import InspectionValue
from .service import InspectionService
from .sessions import PairSessionManager
from .vlm import encode_frames


@dataclass
class CameraInference:
    """保留请求对应的原图和配置代次，避免把旧检测框绘制到新画面。"""

    frame: np.ndarray
    request: SubmittedInference
    generation: int
    captured_at: float


class InspectionConsumer(BaseFunctionConsumer):
    """跟踪安检区域内的双人交互，将已结束会话提交异步视觉语言判定。"""
    def __init__(self, **kwargs):
        """接入平台在线状态，建立逐摄像头会话、跟踪器及配置代次。"""
        self._platform_active = kwargs["is_camera_active"]
        kwargs["is_camera_active"] = self._camera_active
        super().__init__(**kwargs)
        self.service = InspectionService()
        self.vlm_runtime = InspectionRuntime(self._complete)
        self._session_evidence = InspectionSessionEvidence()
        self._sessions: dict[int, PairSessionManager] = {}
        self._trackers: dict[int, CameraByteTracker] = {}
        self._generations: dict[int, int] = {}
        self._frame_shapes: dict[int, tuple] = {}
        self._pending_inferences: dict[int, CameraInference] = {}
        self._prefetch_camera_ids: deque[int] = deque()

    def start(self):
        """先启动异步判定服务，检测启动失败时回收其后台线程。"""
        self.vlm_runtime.start(self.service.get_settings())
        try:
            super().start()
        except Exception:
            self.vlm_runtime.stop()
            raise

    def stop(self):
        """停止检测与异步判定后清空会话及跟踪缓存。"""
        super().stop()
        self.vlm_runtime.stop()
        with self._camera_state_lock:
            for pending in self._pending_inferences.values():
                self.cancel_inference(pending.request)
            self._pending_inferences.clear()
            self._prefetch_camera_ids.clear()
            self._sessions.clear()
            self._trackers.clear()
            self._frame_shapes.clear()
            self._session_evidence.clear()

    def _invalidate(self, camera_id: int):
        """递增配置代次并取消待判定任务，使旧帧和旧结果失效。"""
        self._generations[camera_id] = self._generations.get(camera_id, 0) + 1
        self._session_evidence.cancel_camera(camera_id)
        pending = self._pending_inferences.pop(camera_id, None)
        if pending is not None:
            self.cancel_inference(pending.request)
        self._sessions.pop(camera_id, None)
        self._trackers.pop(camera_id, None)
        self._frame_shapes.pop(camera_id, None)
        self.vlm_runtime.cancel_camera(camera_id)

    def update_config(self, camera_id: int):
        """配置刷新前清空正在累计的交互证据。"""
        with self._camera_state_lock:
            self._invalidate(camera_id)
            super().update_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        """开关变化时使旧任务失效，关闭时同时重置各 ROI 告警冷却。"""
        with self._camera_state_lock:
            self._invalidate(camera_id)
            if not enabled:
                self._reset_alarm_cooldown(camera_id)
            super().update_status(camera_id, enabled)

    def _reset_alarm_cooldown(self, camera_id: int):
        """按摄像头与 ROI 组合身份清理冷却，避免不同区域互相抑制告警。"""
        cfg = self.config_cache.get(camera_id)
        if cfg is None:
            return
        for roi_name in cfg["staff_rois"]:
            for violation_type in self.spec.alarm_types:
                alarm_dispatcher.reset_subject_cooldown(
                    "security_inspection_roi", f"{camera_id}:{roi_name}", violation_type,
                )

    def _camera_active(self, camera_key: str) -> bool:
        """沿用平台视频在线判断，离线时销毁该路尚在进行的交互状态。"""
        with self._camera_state_lock:
            active = self._platform_active(camera_key)
            if not active:
                for camera_id, cfg in self.config_cache.items():
                    if cfg["shm_name"] == camera_key and camera_id in self._sessions:
                        self._invalidate(camera_id)
            return active

    def _get_roi(self, camera_id, frame):
        """使用提前投递时的完整帧，保持跟踪、关键帧和标注与模型输入一致。"""
        pending = self._pending_inferences.get(camera_id)
        if pending is not None:
            self.frame_cache[camera_id] = pending.frame
            return pending.frame
        return frame

    def _before_camera_round(self) -> None:
        """按当前轮询顺序提前投递少量请求，每台摄像头最多保留一个。"""
        with self._camera_state_lock:
            self._prefetch_camera_ids = deque(self.config_cache)
            self._fill_pending_inferences()

    def _fill_pending_inferences(self) -> None:
        """持有摄像头状态锁；一台完成后补投后续摄像头，避免逐路累计等待。"""
        while (
            self.running
            and self._prefetch_camera_ids
            and len(self._pending_inferences) < settings.runtime.security_inspection_inflight
        ):
            camera_id = self._prefetch_camera_ids.popleft()
            if camera_id in self._pending_inferences:
                continue
            cfg = self.config_cache.get(camera_id)
            if cfg is None or not self._should_process_now(camera_id, cfg):
                continue
            if not self.is_camera_active(cfg["shm_name"]):
                continue
            frame = self.latest_frames.get(cfg["shm_name"])
            if frame is None:
                continue
            self._prepare_tracking_state(frame, camera_id)
            captured_at = time.time()
            request = self.submit_inference(
                camera_id, "yolo_human", frame, {name: cfg[name] for name in ("conf", "iou", "imgsz")},
            )
            self._pending_inferences[camera_id] = CameraInference(
                frame, request, self._generations[camera_id], captured_at,
            )

    def _should_process_now(self, camera_id, cfg):
        """仅对启用且配置了安检区域的摄像头按采样周期处理。"""
        return bool(
            cfg["camera_enable"]
            and cfg["staff_rois"]
            and time.time() - self._last_process_at.get(camera_id, 0) >= cfg["cap_interval"]
        )

    def _process_static_frames(self, camera_id, cfg):
        """允许静止帧参与交互保持、结束及超时判断。"""
        return True

    def _prepare_tracking_state(self, frame, camera_id):
        """投递前建立相同分辨率下的跟踪状态，避免收到结果时使自身请求失效。"""
        cfg = self.config_cache[camera_id]
        if self._frame_shapes.get(camera_id) != frame.shape:
            self._invalidate(camera_id)
            self._frame_shapes[camera_id] = frame.shape
        if camera_id not in self._sessions or camera_id not in self._trackers:
            values = InspectionValue.model_validate({name: cfg[name] for name in InspectionValue.model_fields})
            # 两个对象全部构造成功后才发布，初始化失败不能留下半套摄像头状态。
            tracker = CameraByteTracker(fps=1 / values.cap_interval)
            session = PairSessionManager(values)
            self._sessions[camera_id], self._trackers[camera_id] = session, tracker

    def _process(self, frame, camera_id):
        """接收对应原图的结果后推进会话；推理失败或配置代次变化不沿用旧证据。"""
        cfg = self.config_cache[camera_id]
        pending = self._pending_inferences.pop(camera_id, None)
        if pending is None:
            self._prepare_tracking_state(frame, camera_id)
            captured_at = time.time()
            result = self.dispatch_inference_sync(
                camera_id, "yolo_human", frame, {name: cfg[name] for name in ("conf", "iou", "imgsz")},
            )
        else:
            if pending.generation != self._generations.get(camera_id):
                self.cancel_inference(pending.request)
                return False, {"tracks": [], "tasks": []}
            frame = self.frame_cache[camera_id] = pending.frame
            captured_at = pending.captured_at
            result = self.resolve_inference(pending.request)
        if result["status"] != "ok":
            self._invalidate(camera_id)
            return False, {"tracks": [], "tasks": []}
        people = self._trackers[camera_id].update(result["detections"], frame.shape)
        tracks = [
            {
                "track_id": person.track_id,
                "x1": person.bbox[0],
                "y1": person.bbox[1],
                "x2": person.bbox[2],
                "y2": person.bbox[3],
            }
            for person in people
            if person.track_id is not None
        ]
        rois = {
            name: roi_to_pixels(points, frame.shape).astype(float).tolist()
            for name, points in cfg["staff_rois"].items()
        }
        manager = self._sessions[camera_id]
        completed = manager.step(frame, tracks, rois, captured_at)
        # 只为可能持久化报警的会话预留录像，其他渠道不占用公共取证容量。
        active = {state.active.session_id for state in manager.roi_states.values() if state.active is not None}
        if not (cfg.get("sql_enable") or cfg.get("wechat_enable")):
            active.clear()
        self._session_evidence.sync(camera_id, cfg["shm_name"], frame, active,
                                    {session.session_id for session in completed})
        tasks = []
        try:
            for session in completed:
                tasks.append(
                    InspectionTask(
                        session_id=session.session_id,
                        camera_id=camera_id,
                        camera_name=cfg["name"],
                        camera_key=cfg["shm_name"],
                        department=cfg["department"],
                        roi_name=session.roi_name,
                        start_ts=session.start_ts,
                        end_ts=session.end_ts,
                        generation=self._generations[camera_id],
                        frames=encode_frames(session.keyframes, self.vlm_runtime.settings),
                        queued_at=time.monotonic(),
                    )
                )
        except Exception:
            for session in completed:
                self._session_evidence.cancel_session(session.session_id)
            raise
        return False, {"tracks": tracks, "tasks": tasks}

    def _after_process(self, camera_id, result):
        """再次确认任务属于当前配置后提交异步判定，否则记录取消结果。"""
        for task in result[1]["tasks"]:
            with self._camera_state_lock:
                valid = self._task_is_current(task)
            if valid:
                self.vlm_runtime.submit(task)
            else:
                self._complete(task, None, "摄像头状态或检测配置已变更", None)
        with self._camera_state_lock:
            self._fill_pending_inferences()

    def post_process(self, camera_id, result):
        """在原帧副本上绘制安检 ROI 和稳定人体轨迹。"""
        frame = self.frame_cache[camera_id].copy()
        for points in self.config_cache[camera_id]["staff_rois"].values():
            cv2.polylines(frame, [roi_to_pixels(points, frame.shape)], True, self.ROI_COLOR, 2)
        for track in result[1]["tracks"]:
            start = (int(track["x1"]), int(track["y1"]))
            cv2.rectangle(frame, start, (int(track["x2"]), int(track["y2"])), (80, 220, 80), 2)
            cv2.putText(frame, str(track["track_id"]), start, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 220, 80), 2)
        return frame

    def _task_is_current(self, task) -> bool:
        """调用方持有状态锁；检查异步结果是否仍属于当前摄像头配置。"""
        cfg = self.config_cache.get(task.camera_id)
        return bool(
            self.running
            and cfg is not None
            and cfg["camera_enable"]
            and cfg["enable"]
            and task.generation == self._generations.get(task.camera_id)
            and self._platform_active(task.camera_key)
        )

    def _complete(self, task, verdict, error, latency):
        """记录有效判定历史，结束后回收未被告警分发器接收的会话录像。"""
        try:
            self._record_verdict(task, verdict, error, latency)
        finally:
            self._session_evidence.cancel_session(task.session_id)

    def _record_verdict(self, task, verdict, error, latency):
        """不合格告警使用本会话关键帧和已封存录像，判定延迟不追加现场画面。

        回调到达时与告警前均核对配置代次，过期结果记录为取消而不触发告警。
        """
        with self._camera_state_lock:
            cfg = self.config_cache[task.camera_id].copy() if self._task_is_current(task) else None
        if cfg is None:
            self.service.record(task, "cancelled", error="摄像头状态或检测配置已变更")
            return
        status = "error" if error else ("compliant" if verdict.compliant else "non_compliant")
        frame = build_evidence_image(task.frames) if status == "non_compliant" else None
        image_data = encode_evidence_image(frame) if frame is not None else None
        # 会话和证据先原子入库，后续渠道关闭或冷却不会丢掉这次不合规的图片。
        self.service.record(task, status, verdict, error, latency, image_data=image_data)
        if status != "non_compliant":
            return
        with self._camera_state_lock:
            if not self._task_is_current(task):
                return
        self._handle_alarm(
            task.camera_id,
            (
                True,
                {
                    "reason": "安检流程不规范",
                    "metadata": {
                        "session_id": task.session_id,
                        "roi_name": task.roi_name,
                        "started_at": task.start_ts,
                        "ended_at": task.end_ts,
                        "verdict": verdict.model_dump(),
                    },
                    "evidence": AlarmEvidenceRequest(
                        source_key=cfg["shm_name"], mode="episode",
                        episode_token=self._session_evidence.token_for(task.session_id),
                    ),
                },
            ),
            frame,
            config=cfg,
        )

    def _alarm_context(self, camera_id, result):
        """以摄像头和 ROI 作为告警冷却主体，保留会话判定详情。"""
        return {
            **result[1],
            "cooldown_subject_type": "security_inspection_roi",
            "cooldown_subject_id": f"{camera_id}:{result[1]['metadata']['roi_name']}",
        }
