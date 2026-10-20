"""复用人体及身份推理队列，围栏独立管理状态和告警事件。"""
import time
from datetime import datetime, timezone

from AiVision.alarms.dispatcher import alarm_dispatcher
from AiVision.core.settings import settings
from AiVision.features._shared.consumer import BaseFunctionConsumer

from .runtime import FenceRuntime, current_mode
from .preview import FencePreview, draw_fence_detections
from .schema import FORBIDDEN_ALARM, UNAUTHORIZED_ALARM, FencePerson, FenceValue


class FenceConsumer(BaseFunctionConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtimes: dict[int, FenceRuntime] = {}
        self.preview = FencePreview(self.ROI_COLOR)
        self.processed_frames: dict[int, object] = {}
        self.alarm_subjects: dict[int, set[str]] = {}
        self.unidentified_subjects: dict[int, set[str]] = {}
        self.unidentified_slots: dict[int, dict[int, int]] = {}

    def _load_initial_configs(self):
        super()._load_initial_configs()
        for camera_id, config in self.config_cache.items():
            self.preview.configure(camera_id, config)

    def stop(self):
        super().stop()
        with self._camera_state_lock:
            for camera_id, config in self.config_cache.items():
                self._clear_camera_state(camera_id, config.get("shm_name"))

    def update_config(self, camera_id):
        with self._camera_state_lock:
            super().update_config(camera_id)
            if camera_id not in self.config_cache:
                return
            self.runtimes.pop(camera_id, None)
            self.processed_frames.pop(camera_id, None)
            self.preview.configure(camera_id, self.config_cache[camera_id])

    def _clear_camera_state(self, camera_id, shm_name):
        super()._clear_camera_state(camera_id, shm_name)
        self.runtimes.pop(camera_id, None)
        self.processed_frames.pop(camera_id, None)
        self.preview.configure(camera_id, None)
        self._reset_alarm_cooldown(camera_id)

    def _reset_alarm_cooldown(self, camera_id):
        super()._reset_alarm_cooldown(camera_id)
        self.unidentified_slots.pop(camera_id, None)
        for subject in self.alarm_subjects.pop(camera_id, set()):
            self._release_subject(subject)
        for subject in self.unidentified_subjects.pop(camera_id, set()):
            for kind in self.spec.alarm_types:
                alarm_dispatcher.reset_subject_cooldown("fence_unidentified", subject, kind)

    def _release_subject(self, subject):
        for kind in self.spec.alarm_types:
            alarm_dispatcher.reset_subject_cooldown("fence_event", subject, kind)

    def update_status(self, camera_id, enabled):
        with self._camera_state_lock:
            key = self.config_cache.get(camera_id, {}).get("shm_name")
            super().update_status(camera_id, enabled)
            if camera_id not in self.config_cache:
                self._clear_camera_state(camera_id, key)
            else:
                self.preview.configure(camera_id, self.config_cache[camera_id])

    def _get_roi(self, camera_id, frame):
        # 在全画面建立身份，进入警戒 ROI 后再执行准入规则，避免裁掉入口正脸。
        return frame

    def _process_static_frames(self, camera_id, cfg):
        return True

    def _should_process_now(self, camera_id, cfg):
        frame = self.latest_frames.get(cfg["shm_name"])
        return (frame is not self.processed_frames.get(camera_id)
                and time.time() - self._last_process_at.get(camera_id, 0) >= cfg["cap_interval"])

    def _process(self, roi, camera_id):
        cfg = self.config_cache[camera_id]
        runtime = self.runtimes.get(camera_id)
        if runtime is None:
            value = FenceValue.model_validate({key: cfg[key] for key in FenceValue.model_fields})
            runtime = self.runtimes[camera_id] = FenceRuntime(value)
        self.processed_frames[camera_id] = roi
        now = datetime.now(timezone.utc)
        mode = current_mode(runtime.config, now)
        people = self.dispatch_inference_sync(camera_id, "yolo_human", roi, task_meta={"conf": cfg["threshold"]})
        # 人脸识别独立执行，避免近景只检测到人脸时被人体检测结果短路。
        # 白名单仅用于匹配后的准入判断，单个人员缺少特征不阻塞整路识别。
        response = self.dispatch_inference_sync(camera_id, "insightface", roi, task_meta={
            "conf": cfg["detection_threshold"], "similarity_threshold": cfg["similarity_threshold"],
            "include_face_quality": True,
        }, timeout=settings.runtime.fence_inference_timeout_seconds)
        errors = []
        faces = response["detections"] if response["status"] == "ok" else []
        if response["status"] != "ok":
            # 推理或人员底库异常时撤销身份，禁止沿用旧的白名单结论。
            runtime.identities.clear()
            errors.append(f"人脸身份识别失败（{response['status']}）：{response.get('error_message') or response.get('error_code') or '未返回失败原因'}")
        if people["status"] != "ok":
            # 暂时没有可靠观测时撤销身份，不把同一报警事件当成新事件。
            runtime.identities.clear()
            persons = []
            errors.append("人体检测暂不可用")
        else:
            persons = runtime.update(people["detections"], faces, roi.shape, now=now, monotonic=time.monotonic())
        detail = {
            "mode": mode, "persons": [person.model_dump() for person in persons], "faces": faces,
            "count": sum(person.in_roi for person in persons) if people["status"] == "ok" else None,
            "pending_count": sum(person.in_roi and person.identity == "pending" for person in persons) if people["status"] == "ok" else None,
            "alarm": any(person.alarm for person in persons), "error": "；".join(errors) or None,
            "frame_width": roi.shape[1], "frame_height": roi.shape[0], "updated_at_s": time.time(),
        }
        return detail["alarm"], detail

    def post_process(self, camera_id, result):
        frame = self._annotated_frame(camera_id)
        detail = result[1]
        self.preview.publish(camera_id, detail)
        if frame is not None:
            draw_fence_detections(frame, detail)
        return frame

    def _handle_alarm(self, camera_id, result, frame, *, config=None):
        runtime = self.runtimes[camera_id]
        unidentified = sorted(
            (person for person in result[1]["persons"] if person["alarm"] and person["person_id"] is None),
            key=lambda person: person["bbox"][0],
        )
        self.unidentified_slots[camera_id] = {person["track_id"]: slot for slot, person in enumerate(unidentified)}
        current = {f"{camera_id}:{event.key}" for event in runtime.events.values()}
        subjects = self.alarm_subjects.setdefault(camera_id, set())
        for subject in subjects - current:
            self._release_subject(subject)
        subjects.intersection_update(current)
        for person in result[1]["persons"]:
            if not person["alarm"]:
                continue
            event = runtime.events[person["track_id"]]
            if event.dispatched:
                self._complete_alarm_identity(camera_id, event, person, config=config)
                continue
            if super()._handle_alarm(camera_id, (True, person), frame, config=config):
                event.dispatched = True
                event.person = FencePerson.model_validate(person)
                subjects.add(f"{camera_id}:{event.key}")

    def _complete_alarm_identity(self, camera_id, event, person, *, config=None):
        """补全原报警的身份，不重新触发喇叭、截图或新增报警记录。"""
        if person["identity"] == "pending":
            return
        if event.person.identity != "pending" and not (event.person.person_id is None and person["person_id"] is not None):
            return
        cfg = self.config_cache[camera_id] if config is None else config
        writer = alarm_dispatcher.violation_writer
        if writer is None or not (cfg.get("sql_enable") or cfg.get("wechat_enable")):
            return
        # 保留首次违规的位置、原因和截图，只补充后续确认的身份字段。
        identified = event.person.model_copy(update={key: person[key] for key in (
            "identity", "person_id", "person_name", "job_no", "org_index_code", "similarity",
        )})
        if writer.enqueue_metadata_patch(
            event_key=event.key, feature_name=self.feature_name, department=cfg["department"],
            camera_no=cfg["shm_name"], metadata={"person": identified.model_dump()},
        ):
            event.person = identified

    def _alarm_violation_type(self, camera_id, result, cfg):
        return FORBIDDEN_ALARM if result[1]["reason"] == "forbidden_time" else UNAUTHORIZED_ALARM

    def _alarm_context(self, camera_id, result):
        cfg, person = self.config_cache[camera_id], result[1]
        runtime = self.runtimes[camera_id]
        event = runtime.events[person["track_id"]]
        subject_type, subject_id = "fence_event", f"{camera_id}:{event.key}"
        if person["person_id"] is None:
            # 无身份依据时不能把新轨迹视为新人；按当前可见违规人数共享冷却，保留多人分别报警。
            subject_type = "fence_unidentified"
            subject_id = f"{camera_id}:{self.unidentified_slots[camera_id][person['track_id']]}"
            self.unidentified_subjects.setdefault(camera_id, set()).add(subject_id)
        return {
            "cooldown_subject_type": subject_type,
            "cooldown_subject_id": subject_id,
            "subject_type": "camera", "subject_id": cfg["shm_name"], "subject_name": cfg["name"],
            "reason": person["reason"],
            "metadata": {"camera_name": cfg["name"], "person": person,
                         "event_key": event.key},
        }

    def get_monitor_status(self, camera_key):
        return self.preview.status(camera_key)

    def get_live_preview(self, camera_key, frame, *, now):
        """实时画面与模型完成频率分离，过期身份不继续叠加到画面。"""
        return self.preview.render(camera_key, frame, now=now)
