"""管理安检会话录像与关键帧拼图，供异步判定和业务告警复用。"""

import math
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from AiVision.alarms.evidence.evidence_recorder import AlarmEvidenceRecorder, alarm_evidence_recorder
from AiVision.core.logger import logger

EVIDENCE_CELL_WIDTH = 480
EVIDENCE_CELL_HEIGHT = 360
EVIDENCE_JPEG_QUALITY = 85
EVIDENCE_MAX_BYTES = 16 * 1024 * 1024 - 1


@dataclass
class _SessionRecording:
    """隔离摄像头、会话及录像令牌，封存后不再接收现场新帧。"""
    camera_id: int
    token: str | None
    sealed: bool = False


class InspectionSessionEvidence:
    """会话开始时录制、结束时封存，由告警分发器决定最终视频归属。"""

    def __init__(self, recorder: AlarmEvidenceRecorder = alarm_evidence_recorder):
        self.recorder = recorder
        self._recordings: dict[str, _SessionRecording] = {}
        self._lock = threading.RLock()

    def sync(self, camera_id: int, source_key: str, frame: np.ndarray,
             active: set[str], completed: set[str]) -> None:
        """同步会话边界；无有效判定关键帧的结束会话直接回收，不生成短片替代。"""
        with self._lock:
            for session_id in active:
                if session_id in self._recordings:
                    continue
                token = self.recorder.begin_episode(source_key, frame)
                self._recordings[session_id] = _SessionRecording(camera_id, token)
                if token is None and self.recorder.enabled:
                    logger.warning(f"[security_inspection] 无法开始会话录像 camera_id={camera_id} session={session_id}")
            for session_id, recording in tuple(self._recordings.items()):
                if recording.camera_id != camera_id or recording.sealed or session_id in active:
                    continue
                if session_id in completed and recording.token and self.recorder.seal_episode(recording.token):
                    recording.sealed = True
                else:
                    self.cancel_session(session_id)

    def token_for(self, session_id: str) -> str | None:
        """只有已封存的本会话录像可以交给延迟返回的报警结果。"""
        with self._lock:
            recording = self._recordings.get(session_id)
            return recording.token if recording and recording.sealed else None

    def cancel_session(self, session_id: str) -> None:
        """未被分发器接收的录像均释放临时文件及容量，已提交的令牌取消无副作用。"""
        with self._lock:
            recording = self._recordings.pop(session_id, None)
            if recording and recording.token:
                self.recorder.cancel_episode(recording.token)

    def cancel_camera(self, camera_id: int) -> None:
        """配置、离线或启停变化立即回收该摄像头正在采集和等待判定的录像。"""
        with self._lock:
            for session_id, recording in tuple(self._recordings.items()):
                if recording.camera_id == camera_id:
                    self.cancel_session(session_id)

    def clear(self) -> None:
        """检测停止时回收所有尚未提交的会话录像。"""
        with self._lock:
            for session_id in tuple(self._recordings):
                self.cancel_session(session_id)


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
