"""短时显示匹配的检测原图，慢推理时让监控及时回到实时视频。"""
from dataclasses import dataclass

import numpy as np

from .defaults import PREVIEW_FRAME_MAX_AGE_SECONDS


@dataclass(frozen=True)
class DetectionPreviewFrame:
    """检测画面与采样时间成对保存；sampled_at 不使用推理完成时间。"""

    frame: np.ndarray
    sampled_at: float

    def usable(self, live_frame: np.ndarray, *, now: float, max_age: float) -> bool:
        """分辨率或时效不符时使用实时底图，不能继续展示旧位置。"""
        return (self.frame.shape == live_frame.shape
                and 0 <= now - self.sampled_at <= min(max_age, PREVIEW_FRAME_MAX_AGE_SECONDS))


@dataclass(frozen=True)
class AnnotatedPreviewFrame(DetectionPreviewFrame):
    """原子发布标注图、采样时间和配置引用，不额外保留原图像素。"""

    config: dict
