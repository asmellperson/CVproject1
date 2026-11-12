"""复用人体及身份推理队列，围栏独立管理状态和告警事件。"""
import time
from collections import deque
from concurrent.futures import Future
from datetime import datetime, timezone

from AiVision.alarms.dispatcher import alarm_dispatcher
from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.features.face_recognition.library.constants import AUTHORIZATION_REFRESH_SECONDS

from .runtime import FenceRuntime, current_mode
from .evidence import build_alarm_snapshot
from .inference import FenceInference, inference_ready
from .preview import FencePreview, draw_fence_detections
from .schema import FORBIDDEN_ALARM, UNAUTHORIZED_ALARM, STALE_SECONDS, FencePerson, FenceValue
from .service import person_library


class FenceConsumer(BaseFunctionConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtimes: dict[int, FenceRuntime] = {}
        self.preview = FencePreview(self.ROI_COLOR)
        self.processed_frames: dict[int, object] = {}
        self.alarm_subjects: dict[int, set[str]] = {}
        self.unidentified_subjects: dict[int, set[str]] = {}
        self.unidentified_slots: dict[int, dict[int, int]] = {}
        self.library = person_library
        self._allowed_person_ids: dict[int, set[int]] = {}
        self._authorization_refresh_at: dict[int, float] = {}
        self._pending_inferences: dict[int, FenceInference] = {}
        self._submission_order: deque[int] = deque()
        self._submitted_at: dict[int, float] = {}

    def _load_initial_configs(self):
        super()._load_initial_configs()
        for camera_id, config in self.config_cache.items():
            self.preview.configure(camera_id, config)

    def stop(self):
        super().stop()
        with self._camera_state_lock:
            for camera_id, config in self.config_cache.items():
                self._clear_camera_state(camera_id, config.get("shm_name"))
            self._allowed_person_ids.clear()
            self._authorization_refresh_at.clear()
            self._submission_order.clear()

    def _cancel_pending(self, camera_id):
        pending = self._pending_inferences.pop(camera_id, None)
        if pending is not None:
            self.cancel_inference(pending.people)
            if pending.face is not None:
                self.cancel_inference(pending.face)

    def update_config(self, camera_id):
        with self._camera_state_lock:
            self._cancel_pending(camera_id)
            super().update_config(camera_id)
            if camera_id not in self.config_cache:
                return
            self.runtimes.pop(camera_id, None)
            self.processed_frames.pop(camera_id, None)
            self.preview.configure(camera_id, self.config_cache[camera_id])

    def _clear_camera_state(self, camera_id, shm_name):
        self._cancel_pending(camera_id)
        self._allowed_person_ids.pop(camera_id, None)
        self._authorization_refresh_at.pop(camera_id, None)
        self._submitted_at.pop(camera_id, None)
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
            self._cancel_pending(camera_id)
            key = self.config_cache.get(camera_id, {}).get("shm_name")
            super().update_status(camera_id, enabled)
            if camera_id not in self.config_cache:
                self._clear_camera_state(camera_id, key)
            else:
                self.preview.configure(camera_id, self.config_cache[camera_id])

    def _get_roi(self, camera_id, frame):
        # 在全画面建立身份，进入警戒 ROI 后再执行准入规则，避免裁掉入口正脸。
        pending = self._pending_inferences[camera_id]
        self.frame_cache[camera_id] = pending.frame
        self._frame_sampled_at[camera_id] = pending.captured_at
        return pending.frame

    def _before_camera_round(self):
        """沿用安检的提前投递方式，以轮转和有界在途请求避免慢路阻塞其他摄像头。"""
        with self._camera_state_lock:
            now = datetime.now(timezone.utc)
            for camera_id, pending in list(self._pending_inferences.items()):
                cfg = self.config_cache.get(camera_id)
                frame = self.latest_frames.get(pending.config["shm_name"])
                if (cfg is not pending.config or not cfg.get("enable", True) or not cfg.get("camera_enable", True)
                        or not self.is_camera_active(cfg["shm_name"])
                        or current_mode(FenceValue.model_validate({
                            key: cfg[key] for key in FenceValue.model_fields
                        }), now) != pending.mode
                        or frame is None or frame.shape != pending.frame.shape):
                    self._cancel_pending(camera_id)
                elif pending.people_result is None and inference_ready(pending.people, time.monotonic()):
                    pending.people_result = self.resolve_inference(pending.people)

            current_ids = set(self.config_cache)
            self._submission_order = deque(cam for cam in self._submission_order if cam in current_ids)
            self._submission_order.extend(cam for cam in self.config_cache if cam not in self._submission_order)
            people_inflight = sum(job.people_result is None for job in self._pending_inferences.values())
            for _ in range(len(self._submission_order)):
                if not self.running or people_inflight >= settings.runtime.fence_inflight:
                    break
                camera_id = self._submission_order[0]
                self._submission_order.rotate(-1)
                cfg = self.config_cache[camera_id]
                if (camera_id in self._pending_inferences or not cfg.get("enable", True)
                        or not cfg.get("camera_enable", True)):
                    continue
                if not self.is_camera_active(cfg["shm_name"]):
                    continue
                frame = self.latest_frames.get(cfg["shm_name"])
                sampled_at = self.latest_frame_times.get(cfg["shm_name"], time.time())
                if (frame is None or frame is self.processed_frames.get(camera_id)
                        or time.monotonic() - self._submitted_at.get(camera_id, float("-inf")) < cfg["cap_interval"]):
                    continue
                value = FenceValue.model_validate({key: cfg[key] for key in FenceValue.model_fields})
                observed_at = time.monotonic()
                people = self.submit_inference(camera_id, "yolo_human", frame, {"conf": cfg["threshold"]})
                self._pending_inferences[camera_id] = FenceInference(
                    frame, cfg, sampled_at, observed_at, current_mode(value, now), people,
                )
                people_inflight += 1
                self.processed_frames[camera_id] = frame
                self._submitted_at[camera_id] = observed_at

            face_inflight = sum(job.face is not None for job in self._pending_inferences.values())
            for camera_id, pending in list(self._pending_inferences.items()):
                if not self.running or face_inflight >= settings.runtime.fence_inflight:
                    break
                if pending.face is not None or (pending.mode == "forbidden" and not pending.early_published):
                    continue
                cfg = pending.config
                try:
                    pending.face = self.submit_inference(camera_id, "insightface", pending.frame, {
                        "conf": cfg["detection_threshold"], "similarity_threshold": cfg["similarity_threshold"],
                        "include_face_quality": True,
                    }, timeout=settings.runtime.fence_inference_timeout_seconds)
                except Exception:
                    self._cancel_pending(camera_id)
                    raise
                face_inflight += 1

    def _process_static_frames(self, camera_id, cfg):
        return True

    def _should_process_now(self, camera_id, cfg):
        pending = self._pending_inferences.get(camera_id)
        return pending is not None and pending.ready(time.monotonic())

    def _processing_interval_seconds(self, camera_id, cfg):
        # 采样间隔在投递时控制；已就绪的结果和身份补全不能再等一个采样周期。
        return 0.0

    def _process(self, roi, camera_id):
        cfg = self.config_cache[camera_id]
        runtime = self.runtimes.get(camera_id)
        if runtime is None:
            value = FenceValue.model_validate({key: cfg[key] for key in FenceValue.model_fields})
            runtime = self.runtimes[camera_id] = FenceRuntime(value)
        pending = self._pending_inferences[camera_id]
        now = datetime.now(timezone.utc)
        mode = current_mode(runtime.config, now)
        if pending.people_result is None:
            pending.people_result = self.resolve_inference(pending.people)
        people = pending.people_result
        response = None
        if pending.face is not None and inference_ready(pending.face, time.monotonic()):
            response = self.resolve_inference(pending.face)
            self._pending_inferences.pop(camera_id)
        identity_only = pending.early_published
        pending.early_published = True
        errors = []
        faces = response["detections"] if response is not None and response["status"] == "ok" else []
        try:
            # 禁入规则不依赖白名单，首次人体报警不能等待数据库或身份识别。
            allowed = (self._allowed_person_ids.get(camera_id, set()) if mode == "forbidden"
                       else self._camera_allowed_people(camera_id))
        except Exception as exc:
            # 读取失败时撤销旧权限和身份；禁入时段仍按人体观测报警，不误用旧名单放行。
            self._allowed_person_ids.pop(camera_id, None)
            self._authorization_refresh_at.pop(camera_id, None)
            runtime.identities.clear()
            faces = []
            allowed = set()
            errors.append("摄像头围栏白名单读取失败")
            logger.warning(f"[security_fence] 摄像头围栏白名单读取失败 camera_id={camera_id} error={type(exc).__name__}")
        if response is not None and response["status"] != "ok":
            # 推理或人员底库异常时撤销身份，禁止沿用旧的白名单结论。
            runtime.identities.clear()
            errors.append(f"人脸身份识别失败（{response['status']}）：{response.get('error_message') or response.get('error_code') or '未返回失败原因'}")
        if people["status"] != "ok":
            # 暂时没有可靠观测时撤销身份，不把同一报警事件当成新事件。
            runtime.identities.clear()
            persons = []
            errors.append("人体检测暂不可用")
        else:
            persons = runtime.update(people["detections"], faces, roi.shape, now=now,
                                     monotonic=pending.observed_at, allowed_person_ids=allowed)
        detail = {
            "mode": mode, "persons": [person.model_dump() for person in persons],
            "faces": [face for face in faces if runtime.usable_face(face)],
            "count": sum(person.in_roi for person in persons) if people["status"] == "ok" else None,
            "pending_count": sum(person.in_roi and person.identity == "pending" for person in persons) if people["status"] == "ok" else None,
            "alarm": any(person.alarm for person in persons), "error": "；".join(errors) or None,
            "frame_width": roi.shape[1], "frame_height": roi.shape[0], "updated_at_s": pending.captured_at,
            "identity_only": identity_only,
        }
        if mode == "forbidden" and response is None and not detail["alarm"]:
            # 无违规时继续采样人体，避免无人的旧帧占着身份等待而漏掉随后进入的人。
            self._cancel_pending(camera_id)
        return detail["alarm"], detail

    def _camera_allowed_people(self, camera_id: int) -> set[int]:
        """逐摄像头缓存授权，刷新周期与人脸身份识别保持一致。"""
        if time.monotonic() >= self._authorization_refresh_at.get(camera_id, 0.0):
            self._allowed_person_ids[camera_id] = self.library.get_allowed_person_ids(camera_id=camera_id)
            self._authorization_refresh_at[camera_id] = time.monotonic() + AUTHORIZATION_REFRESH_SECONDS
        return self._allowed_person_ids[camera_id]

    def post_process(self, camera_id, result):
        frame = self._annotated_frame(camera_id)
        detail = result[1]
        self.preview.publish(camera_id, detail, source=self._preview_source(camera_id))
        if frame is not None:
            draw_fence_detections(frame, detail)
        return frame

    def _handle_alarm(self, camera_id, result, frame, *, config=None):
        runtime = self.runtimes[camera_id]
        if result[1].get("identity_only"):
            # 人脸晚到只补齐原记录，不能用旧帧重播喇叭或发出新的通知。
            for person in result[1]["persons"]:
                event = runtime.events.get(person["track_id"])
                if event is not None and event.record_dispatched:
                    self._complete_alarm_identity(camera_id, event, person, config=config)
            return
        if time.time() - result[1]["updated_at_s"] > STALE_SECONDS:
            # 排队过久的结果可显示为过期，但不能对旧画面发出新的现场报警。
            return
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
            first_dispatch = not event.dispatched
            if event.record_dispatched:
                self._complete_alarm_identity(camera_id, event, person, config=config)
            cfg = self.config_cache[camera_id] if config is None else config
            # 各通道独立等待到期；喇叭已播放不能让仍在冷却的记录或企微永远失去机会。
            channels = set()
            if cfg.get("sql_enable") and not event.record_dispatched:
                channels.add("sql")
            if cfg.get("wechat_enable") and not event.wechat_dispatched:
                channels.add("wechat")
            completion = self._horn_attempt(event, cfg)
            if completion is not None:
                channels.add("horn")
            if not channels:
                continue
            if super()._handle_alarm(camera_id, (True, person), frame, config=config,
                                     channels=channels, on_horn_complete=completion):
                event.dispatched = True
                if first_dispatch and not event.record_dispatched:
                    event.person = FencePerson.model_validate(person)
                subjects.add(f"{camera_id}:{event.key}")

    def _horn_attempt(self, event, config):
        """仅当前可见违规会走到这里；旧任务只完成自己的 Future，不主动重播。"""
        now = time.monotonic()
        future = event.horn_future
        if future is not None:
            if not future.done():
                return None
            success, completed_at = future.result()
            event.horn_future = None
            if not success:
                event.horn_next_at = completed_at + settings.runtime.fence_horn_retry_seconds
        if not config.get("horn_enable") or now < event.horn_next_at:
            return None
        interval = config.get("horn_interval")
        interval = config["alarm_interval"] if interval is None else interval
        # 音频播放耗时计入间隔；0 秒只等待上一次实际播放完成，不额外等一轮冷却。
        event.horn_next_at = now + interval
        future = event.horn_future = Future()

        def completed(success):
            # 只捕获轻量 Future；事件已消失或配置已替换时不会操作新的运行状态。
            future.set_result((bool(success), time.monotonic()))

        return completed

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
        snapshot, snapshot_region = build_alarm_snapshot(self.frame_cache[camera_id])
        subject_type, subject_id = "fence_event", f"{camera_id}:{event.key}"
        if person["person_id"] is None:
            # 无身份依据时不能把新轨迹视为新人；按当前可见违规人数共享冷却，保留多人分别报警。
            subject_type = "fence_unidentified"
            subject_id = f"{camera_id}:{self.unidentified_slots[camera_id][person['track_id']]}"
            self.unidentified_subjects.setdefault(camera_id, set()).add(subject_id)

        def notification_enqueued(channel):
            if channel == "sql":
                event.record_dispatched = True
                # 身份补全以真正提交的这张记录为准，不使用较早的喇叭触发位置。
                event.person = FencePerson.model_validate(person)
            elif channel == "wechat":
                event.wechat_dispatched = True

        return {
            "cooldown_subject_type": subject_type,
            "cooldown_subject_id": subject_id,
            "notification_cooldown_subject": (
                "fence_camera", f"{cfg['department']}:{self.feature_name}:{camera_id}",
            ),
            "on_notification_enqueued": notification_enqueued,
            "subject_type": "camera", "subject_id": cfg["shm_name"], "subject_name": cfg["name"],
            "reason": person["reason"],
            "snapshot_frame": snapshot,
            "metadata": {"camera_name": cfg["name"], "person": person,
                         "event_key": event.key, "snapshot": snapshot_region},
        }

    def get_monitor_status(self, camera_key):
        return self.preview.status(camera_key)

    def get_live_preview(self, camera_key, frame, *, now):
        """短时显示对应检测原图，检测延迟过大时继续显示实时底图与 ROI。"""
        return self.preview.render(camera_key, frame, now=now)
