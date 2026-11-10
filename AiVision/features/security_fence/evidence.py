"""围栏截图使用对应人员的同帧原图，录像仍使用完整画面。"""
from math import ceil, floor, isfinite

import numpy as np


# 每侧保留人脸宽高的 30%，避免紧贴五官的局部图在展示时被过度放大。
FACE_SNAPSHOT_PADDING_RATIO = 0.3


def crop_alarm_snapshot(
    frame: np.ndarray, person_box: list[float], face_box: list[float] | None,
) -> tuple[np.ndarray, dict]:
    """优先裁剪唯一关联的人脸并留边；没有有效人脸框时保留人体局部。"""
    height, width = frame.shape[:2]
    for kind, box in (("face", face_box), ("person", person_box)):
        if (box is None or len(box) != 4 or not all(isfinite(value) for value in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            continue
        x1, y1 = max(0, floor(box[0])), max(0, floor(box[1]))
        x2, y2 = min(width, ceil(box[2])), min(height, ceil(box[3]))
        if x1 >= x2 or y1 >= y2:
            continue
        if kind == "face":
            # 先确认原框与画面相交，再外扩，不能把画面外的无效人脸框扩成截图。
            pad_x = (box[2] - box[0]) * FACE_SNAPSHOT_PADDING_RATIO
            pad_y = (box[3] - box[1]) * FACE_SNAPSHOT_PADDING_RATIO
            x1, y1 = max(0, floor(box[0] - pad_x)), max(0, floor(box[1] - pad_y))
            x2, y2 = min(width, ceil(box[2] + pad_x)), min(height, ceil(box[3] + pad_y))
        # 复制局部区域，后续异步写图不能修改采集帧或把裁剪图送入录像缓存。
        return frame[y1:y2, x1:x2].copy(), {"kind": kind, "bbox": [x1, y1, x2, y2]}
    raise ValueError("围栏报警缺少有效的人脸或人体截图区域")
