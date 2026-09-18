"""消费平台视频帧与人体推理结果，维护逐路安检状态。"""

import math
import time

import cv2
import numpy as np

from AiVision.alarms.dispatcher import AlarmEvidenceRequest, alarm_dispatcher
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.features._shared.roi import roi_to_pixels
from AiVision.features.guard_behavior.tracking import CameraByteTracker
from .runtime import InspectionRuntime, InspectionTask
from .schema import InspectionValue
from .service import InspectionService
from .sessions import PairSessionManager
from .vlm import encode_frames


class InspectionConsumer(BaseFunctionConsumer):
    def __init__(self, **kwargs):
        self._platform_active = kwargs["is_camera_active"]
        kwargs["is_camera_active"] = self._camera_active
        super().__init__(**kwargs)
        self.service = InspectionService()
        self.vlm_runtime = InspectionRuntime(self._complete)
        self._sessions: dict[int, PairSessionManager] = {}
        self._trackers: dict[int, CameraByteTracker] = {}
        self._generations: dict[int, int] = {}
        self._frame_shapes: dict[int, tuple] = {}

    def start(self):
        self.vlm_runtime.start(self.service.get_settings())
        try:
            super().start()
        except Exception:
            self.vlm_runtime.stop()
            raise

    def stop(self):
        super().stop()
        self.vlm_runtime.stop()
        with self._camera_state_lock:
            self._sessions.clear()
            self._trackers.clear()
            self._frame_shapes.clear()

    def _invalidate(self, camera_id: int):
        self._generations[camera_id] = self._generations.get(camera_id, 0) + 1
        self._sessions.pop(camera_id, None)
        self._trackers.pop(camera_id, None)
        self._frame_shapes.pop(camera_id, None)
        self.vlm_runtime.cancel_camera(camera_id)

    def update_config(self, camera_id: int):
        with self._camera_state_lock:
            self._invalidate(camera_id)
            super().update_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        with self._camera_state_lock:
            self._invalidate(camera_id)
            if not enabled:
                self._reset_alarm_cooldown(camera_id)
            super().update_status(camera_id, enabled)

    def _reset_alarm_cooldown(self, camera_id: int):
        cfg = self.config_cache.get(camera_id)
        if cfg is None:
            return
        for roi_name in cfg["staff_rois"]:
            for violation_type in self.spec.alarm_types:
                alarm_dispatcher.reset_subject_cooldown(
                    "security_inspection_roi", f"{camera_id}:{roi_name}", violation_type,
                )

    def _camera_active(self, camera_key: str) -> bool:
        active = self._platform_active(camera_key)
        if not active:
            for camera_id, cfg in self.config_cache.items():
                if cfg["shm_name"] == camera_key and camera_id in self._sessions:
                    self._invalidate(camera_id)
        return active

    def _get_roi(self, camera_id, frame):
        return frame

    def _should_process_now(self, camera_id, cfg):
        return bool(
            cfg["camera_enable"]
            and cfg["staff_rois"]
            and time.time() - self._last_process_at.get(camera_id, 0) >= cfg["cap_interval"]
        )

    def _process_static_frames(self, camera_id, cfg):
        return True

    def _process(self, frame, camera_id):
        cfg = self.config_cache[camera_id]
        if self._frame_shapes.get(camera_id) != frame.shape:
            self._invalidate(camera_id)
            self._frame_shapes[camera_id] = frame.shape
        if camera_id not in self._sessions:
            values = InspectionValue.model_validate({name: cfg[name] for name in InspectionValue.model_fields})
            self._sessions[camera_id] = PairSessionManager(values)
            self._trackers[camera_id] = CameraByteTracker(fps=1 / values.cap_interval)
        result = self.dispatch_inference_sync(
            camera_id, "yolo_human", frame, {name: cfg[name] for name in ("conf", "iou", "imgsz")}
        )
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
        tasks = []
        for session in self._sessions[camera_id].step(frame, tracks, rois, time.time()):
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
        return False, {"tracks": tracks, "tasks": tasks}

    def _after_process(self, camera_id, result):
        for task in result[1]["tasks"]:
            with self._camera_state_lock:
                valid = self._task_is_current(task)
            if valid:
                self.vlm_runtime.submit(task)
            else:
                self._complete(task, None, "摄像头状态或检测配置已变更", None)

    def post_process(self, camera_id, result):
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
        with self._camera_state_lock:
            cfg = self.config_cache[task.camera_id].copy() if self._task_is_current(task) else None
        if cfg is None:
            self.service.record(task, "cancelled", error="摄像头状态或检测配置已变更")
            return
        status = "error" if error else ("compliant" if verdict.compliant else "non_compliant")
        self.service.record(task, status, verdict, error, latency)
        if status != "non_compliant":
            return
        frame = self._evidence_image(task.frames)
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
                    "evidence": AlarmEvidenceRequest(source_key=cfg["shm_name"], mode="snapshot"),
                },
            ),
            frame,
            config=cfg,
        )

    def _alarm_context(self, camera_id, result):
        return {
            **result[1],
            "cooldown_subject_type": "security_inspection_roi",
            "cooldown_subject_id": f"{camera_id}:{result[1]['metadata']['roi_name']}",
        }

    @staticmethod
    def _evidence_image(frames: list[bytes]):
        # 只使用已结束会话的关键帧；不能用千问返回时的实时画面替代现场证据。
        width, height = 480, 360
        image = np.zeros((height * math.ceil(len(frames) / 2), width * 2, 3), dtype=np.uint8)
        for index, raw in enumerate(frames):
            frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            scale = min(width / frame.shape[1], height / frame.shape[0])
            frame = cv2.resize(frame, (max(1, int(frame.shape[1] * scale)), max(1, int(frame.shape[0] * scale))))
            x, y = (index % 2) * width, (index // 2) * height
            image[y : y + frame.shape[0], x : x + frame.shape[1]] = frame
            cv2.putText(image, str(index + 1), (x + 8, y + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return image
