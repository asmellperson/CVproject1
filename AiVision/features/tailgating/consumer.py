"""摄像头独立跟踪与事件报警；预览、状态读取使用独立短锁。"""
from copy import deepcopy
from threading import Lock

from AiVision.alarms.dispatcher import alarm_dispatcher
from AiVision.features._shared.pipelined_consumer import PipelinedConsumer
from .preview import PreviewState, annotate_frame, render_preview
from .runtime import TailgatingRuntime
from .schema import ALARM_TYPE, TailgatingValue


class TailgatingConsumer(PipelinedConsumer):
    inference_model = "yolo_human"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtimes: dict[int, TailgatingRuntime] = {}
        self._preview_lock = Lock()
        self._previews: dict[int, PreviewState] = {}
        self._alarm_subjects: dict[int, set[str]] = {}

    def _configure_camera(self, camera_id):
        config = self.config_cache[camera_id]
        if not config.get("camera_enable", True):
            self._clear_camera_state(camera_id, config["shm_name"])
            return
        value = TailgatingValue.model_validate({key: config[key] for key in TailgatingValue.model_fields})
        self.runtimes[camera_id] = TailgatingRuntime(value)
        with self._preview_lock:
            self._previews[camera_id] = PreviewState(config["shm_name"], value)

    def _load_initial_configs(self):
        super()._load_initial_configs()
        for camera_id in self.config_cache:
            self._configure_camera(camera_id)

    def update_config(self, camera_id):
        with self._camera_state_lock:
            super().update_config(camera_id)
            if camera_id in self.config_cache:
                self._configure_camera(camera_id)

    def update_status(self, camera_id, enabled):
        with self._camera_state_lock:
            key = self.config_cache.get(camera_id, {}).get("shm_name")
            super().update_status(camera_id, enabled)
            if camera_id in self.config_cache:
                self._configure_camera(camera_id)
            else:
                self._clear_camera_state(camera_id, key)

    def _clear_camera_state(self, camera_id, shm_name):
        super()._clear_camera_state(camera_id, shm_name)
        self.runtimes.pop(camera_id, None)
        with self._preview_lock:
            self._previews.pop(camera_id, None)
        self._reset_alarm_cooldown(camera_id)

    def _reset_alarm_cooldown(self, camera_id):
        super()._reset_alarm_cooldown(camera_id)
        for subject in self._alarm_subjects.pop(camera_id, set()):
            alarm_dispatcher.reset_subject_cooldown("tailgating_event", subject, ALARM_TYPE)

    def stop(self):
        super().stop()
        with self._camera_state_lock:
            for camera_id, config in self.config_cache.items():
                self._clear_camera_state(camera_id, config["shm_name"])

    def _inference_region(self, camera_id, frame):
        # 保留通道前后的人员轨迹；只有 ROI 内的共同出现才参与报警。
        return frame

    def _inference_parameters(self, camera_id, config):
        runtime = self.runtimes[camera_id]
        return {"conf": runtime.config.threshold} if runtime.config.configured else None

    def _process(self, frame, camera_id):
        sample = self._samples.pop(camera_id)
        runtime = self.runtimes[camera_id]
        detail = {"persons": [], "events": [], "count": None, "alarm": False,
                  "reason": "unconfigured", "sample_interval_seconds": None, "error": None}
        if sample.request is not None:
            outcome = self.resolve_inference(sample.request)
            if outcome["status"] == "ok":
                # 通行轨迹以画面采集间隔为准，投递和领取结果的时间只用于推理诊断。
                detail.update(runtime.update(outcome["detections"], frame.shape, now=sample.captured_at))
                if detail["reason"] == "sampling_gap":
                    detail["error"] = "实际检测间隔过大，已清除旧通行状态，请检查模型负载及采集帧率。"
            else:
                runtime.clear()
                detail.update(reason="inference_error", error=outcome.get("error_message") or f'人体检测失败：{outcome["status"]}')
        detail.update(frame_width=frame.shape[1], frame_height=frame.shape[0], updated_at_s=sample.captured_at)
        active_subjects = {f'{camera_id}:{event["id"]}' for event in detail["events"]}
        for subject in self._alarm_subjects.get(camera_id, set()) - active_subjects:
            alarm_dispatcher.reset_subject_cooldown("tailgating_event", subject, ALARM_TYPE)
        self._alarm_subjects[camera_id] = active_subjects
        return detail["alarm"], detail

    def post_process(self, camera_id, result):
        detail = deepcopy(result[1])
        with self._preview_lock:
            entry = self._previews[camera_id]
            state = PreviewState(entry.camera_key, entry.value, detail, self._preview_source(camera_id))
            self._previews[camera_id] = state
        # 普通画面由预览请求按需标注。只有报警证据需要在检测线程绘制当次原图。
        if detail["events"]:
            return annotate_frame(self.frame_cache[camera_id], state.value, detail)
        return None

    def _preview(self, camera_key):
        with self._preview_lock:
            return next((value for value in self._previews.values() if value.camera_key == camera_key), None)

    def get_monitor_status(self, camera_key):
        entry = self._preview(camera_key)
        return deepcopy(entry.detail) if entry else None

    def get_live_preview(self, camera_key, frame, *, now):
        entry = self._preview(camera_key)
        if entry is None:
            return None
        annotated = render_preview(frame, entry, now=now)
        current = self._preview(camera_key)
        return annotated if current is not None and current.value is entry.value else None

    def _handle_alarm(self, camera_id, result, frame, *, config=None):
        for event in result[1]["events"]:
            pairs = [pair for pair in self.runtimes[camera_id].pairs.values() if pair.event_id == event["id"]]
            if not any(pair.dispatched for pair in pairs) and super()._handle_alarm(camera_id, (True, event), frame, config=config):
                for pair in pairs:
                    pair.dispatched = True

    def _alarm_context(self, camera_id, result):
        event = result[1]
        return {"cooldown_subject_type": "tailgating_event", "cooldown_subject_id": f'{camera_id}:{event["id"]}',
                "reason": "过闸判定线检测到多人同向通行且在闸机区域内共同出现",
                "metadata": {"tailgating": event}}
