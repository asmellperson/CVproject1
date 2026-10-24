"""保存检测使用的原图，防止历史坐标叠加到新视频帧。"""
from dataclasses import dataclass

import numpy as np

from .defaults import ANNOTATED_FRAME_FRESH_SECONDS


@dataclass(frozen=True)
class DetectionPreviewFrame:
    """每路只保留最近一次检测原图；sampled_at 是进入推理前的时间。"""

    frame: np.ndarray
    sampled_at: float

    def usable(self, live_frame: np.ndarray, *, now: float, max_age: float) -> bool:
        """分辨率或时效不符时使用实时底图，不能继续展示旧位置。"""
        return (self.frame.shape == live_frame.shape
                and 0 <= now - self.sampled_at <= min(max_age, ANNOTATED_FRAME_FRESH_SECONDS))
