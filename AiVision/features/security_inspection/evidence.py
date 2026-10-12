"""将会话关键帧组成同一份证据，供数据库保存和业务告警复用。"""

import math

import cv2
import numpy as np

EVIDENCE_CELL_WIDTH = 480
EVIDENCE_CELL_HEIGHT = 360
EVIDENCE_JPEG_QUALITY = 85
EVIDENCE_MAX_BYTES = 16 * 1024 * 1024 - 1


def build_evidence_image(frames: list[bytes]) -> np.ndarray:
    """只使用被模型判定的关键帧；缺失或损坏时拒绝生成虚假的现场证据。"""
    if not frames:
        raise ValueError("安检证据缺少关键帧")
    width, height = EVIDENCE_CELL_WIDTH, EVIDENCE_CELL_HEIGHT
    image = np.zeros((height * math.ceil(len(frames) / 2), width * 2, 3), dtype=np.uint8)
    for index, raw in enumerate(frames):
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"安检关键帧解码失败：第 {index + 1} 帧")
        scale = min(width / frame.shape[1], height / frame.shape[0])
        frame = cv2.resize(frame, (max(1, int(frame.shape[1] * scale)), max(1, int(frame.shape[0] * scale))))
        x, y = (index % 2) * width, (index // 2) * height
        image[y:y + frame.shape[0], x:x + frame.shape[1]] = frame
        cv2.putText(image, str(index + 1), (x + 8, y + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return image


def encode_evidence_image(frame: np.ndarray) -> bytes:
    """用 JPEG 控制数据库证据体积，并在事务前检查编码结果与列容量。"""
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, EVIDENCE_JPEG_QUALITY])
    if not ok or not encoded.size or encoded.size > EVIDENCE_MAX_BYTES:
        raise ValueError("安检证据编码失败或超过数据库图片容量")
    return encoded.tobytes()
