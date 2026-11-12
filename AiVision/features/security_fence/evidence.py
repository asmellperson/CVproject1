"""围栏截图保留检测同帧的完整原图。"""
import numpy as np


def build_alarm_snapshot(frame: np.ndarray) -> tuple[np.ndarray, dict]:
    """保留现场全貌，并复制原图以隔离后续标注和异步写入。"""
    height, width = frame.shape[:2]
    return frame.copy(), {"kind": "full_frame", "bbox": [0, 0, width, height]}
