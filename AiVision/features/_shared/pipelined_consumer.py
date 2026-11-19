"""在多路轮询间交叠单模型请求，按原始输入发布每路结果。"""
from collections import deque
from dataclasses import dataclass
import time
from weakref import ReferenceType, ref

import numpy as np

from .consumer import BaseFunctionConsumer, SubmittedInference
from .defaults import ANNOTATED_FRAME_FRESH_SECONDS


@dataclass
class CameraSample:
    frame: np.ndarray
    region: np.ndarray
    config: dict
    captured_at: float
    request: SubmittedInference | None


class PipelinedConsumer(BaseFunctionConsumer):
    inference_model: str
    max_inflight = 4
    wake_on_inference = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._samples: dict[int, CameraSample] = {}
        self._last_samples: dict[int, tuple[ReferenceType[np.ndarray], float]] = {}
        self._sample_order: deque[int] = deque()

    def _inference_parameters(self, camera_id: int, config: dict) -> dict | None:
        """返回输入参数，未配置的摄像头可以只发布等待配置状态。"""
        return {}

    def _can_sample(self, camera_id: int, config: dict) -> bool:
        """业务有独立时段或启用条件时，同时用于投递和撤销在途帧。"""
        return True

    def _inference_region(self, camera_id: int, frame: np.ndarray) -> np.ndarray:
        return super()._get_roi(camera_id, frame)

    def _before_camera_round(self) -> None:
        with self._camera_state_lock:
            wall_now = time.time()
            for camera_id, sample in tuple(self._samples.items()):
                config = self.config_cache.get(camera_id)
                if (config is not sample.config or not config.get("camera_enable", True)
                        or not self._can_sample(camera_id, config)):
                    self._invalidate_sample(camera_id)
                    continue
                current = self.latest_frames.get(config["shm_name"])
                if (not self.is_camera_active(config["shm_name"]) or current is None
                        or current.shape != sample.frame.shape
                        or wall_now - sample.captured_at > ANNOTATED_FRAME_FRESH_SECONDS):
                    self._invalidate_sample(camera_id)

            camera_ids = set(self.config_cache)
            self._sample_order = deque(camera_id for camera_id in self._sample_order if camera_id in camera_ids)
            queued_ids = set(self._sample_order)
            self._sample_order.extend(camera_id for camera_id in self.config_cache if camera_id not in queued_ids)
            self._fill_samples()

    def _after_process(self, camera_id, result):
        # 结果完成后立即补投下一路，避免等待一轮的剩余摄像头或固定轮询休眠。
        with self._camera_state_lock:
            self._fill_samples()

    def _fill_samples(self) -> None:
        for _ in range(len(self._sample_order)):
            if not self.running or len(self._samples) >= self.max_inflight:
                break
            camera_id = self._sample_order[0]
            self._sample_order.rotate(-1)
            config = self.config_cache.get(camera_id)
            if config is None or camera_id in self._samples or not config.get("camera_enable", True):
                continue
            camera_key = config["shm_name"]
            if not self.is_camera_active(camera_key) or not self._can_sample(camera_id, config):
                continue
            interval = self._processing_interval_seconds(camera_id, config)
            if interval is None:
                continue
            frame, captured_at = super()._processing_frame(camera_id, camera_key)
            if frame is None or not 0 <= time.time() - captured_at <= ANNOTATED_FRAME_FRESH_SECONDS:
                continue
            observed_at = time.monotonic()
            previous = self._last_samples.get(camera_id)
            if previous is not None:
                previous_frame, submitted_at = previous
                if frame is previous_frame() or observed_at - submitted_at < interval:
                    continue
            region = self._inference_region(camera_id, frame)
            parameters = self._inference_parameters(camera_id, config)
            request = (self.submit_inference(camera_id, self.inference_model, region, parameters)
                       if parameters is not None else None)
            self._samples[camera_id] = CameraSample(frame, region, config, captured_at, request)
            self._last_samples[camera_id] = (ref(frame), observed_at)

    def _invalidate_sample(self, camera_id: int) -> None:
        sample = self._samples.pop(camera_id, None)
        if sample is not None and sample.request is not None:
            self.cancel_inference(sample.request)
        self._last_samples.pop(camera_id, None)

    def update_config(self, camera_id: int):
        with self._camera_state_lock:
            self._invalidate_sample(camera_id)
            super().update_config(camera_id)

    def update_status(self, camera_id: int, enabled: bool):
        with self._camera_state_lock:
            self._invalidate_sample(camera_id)
            super().update_status(camera_id, enabled)

    def stop(self):
        super().stop()
        with self._camera_state_lock:
            for camera_id in tuple(self._samples):
                self._invalidate_sample(camera_id)
            self._last_samples.clear()
            self._sample_order.clear()

    def _processing_frame(self, camera_id: int, camera_key: str) -> tuple[np.ndarray | None, float]:
        sample = self._samples.get(camera_id)
        return (sample.frame, sample.captured_at) if sample is not None else (None, 0.0)

    def _should_process_now(self, camera_id, cfg):
        sample = self._samples.get(camera_id)
        if sample is None:
            return False
        if not 0 <= time.time() - sample.captured_at <= ANNOTATED_FRAME_FRESH_SECONDS:
            self._invalidate_sample(camera_id)
            return False
        return sample.request is None or sample.request.ready(time.monotonic())

    def _get_roi(self, camera_id, frame):
        return self._samples[camera_id].region

    def _frame_changed(self, camera_id, roi, threshold=0.005):
        # 这些功能持续处理静态画面，已在投递入口限制频率。
        return True
