"""识别记录写入与查询；冷却状态留在 Consumer 所属进程内。"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from sqlalchemy import func, select

from AiVision.core.db import get_session, session_scope
from AiVision.core.logger import logger
from AiVision.core.settings import settings
from .orm import FaceRecognitionRecord
from .schema import RecognitionRecordItem, RecognitionRecordPage

RECORD_RETRY_SECONDS = 5.0


class RecognitionRecorder:
    def __init__(self):
        self._recorded_at: dict[tuple[int, int], float] = {}
        self._unknown_recorded_at: dict[int, float] = {}
        self._retry_at = 0.0

    def clear_camera(self, camera_id: int) -> None:
        self._recorded_at = {key: value for key, value in self._recorded_at.items() if key[0] != camera_id}
        self._unknown_recorded_at.pop(camera_id, None)

    def record(self, camera_id: int, detections: list[dict], cooldown_seconds: float, *, frame: np.ndarray) -> int:
        now = time.monotonic()
        if now < self._retry_at:
            return 0
        candidates: dict[tuple[int, int], dict] = {}
        unknowns: list[dict] = []
        unknown_due = now - self._unknown_recorded_at.get(camera_id, float("-inf")) >= cooldown_seconds
        for detection in detections:
            if not detection["matched"]:
                # 未知人员按摄像头整帧限频；允许保存时保留该帧的每一个未知 bbox。
                if unknown_due:
                    unknowns.append(detection)
                continue
            key = (camera_id, detection["person_id"])
            if now - self._recorded_at.get(key, float("-inf")) < cooldown_seconds:
                continue
            if key not in candidates or detection["similarity"] > candidates[key]["similarity"]:
                candidates[key] = detection
        values = [*candidates.values(), *unknowns]
        if not values:
            return 0
        image_path = None
        try:
            captured_at = datetime.now()
            # 沿用 DATA_PATH、OpenCV PNG 编码及毫秒时间戳 + UUID 命名规范。
            directory = Path(settings.storage.data_path).expanduser().resolve() / "recognize_face"
            directory.mkdir(parents=True, exist_ok=True)
            filename = captured_at.strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3] + f"_{uuid4().hex}.png"
            image_path = directory / filename
            if not cv2.imwrite(str(image_path), frame):
                raise OSError("识别截图写入失败")
            with session_scope() as session:
                session.add_all([
                    FaceRecognitionRecord(
                        camera_id=camera_id, person_id=value["person_id"],
                        person_name=value["person_name"], similarity=value["similarity"],
                        image_path=str(image_path), recognized_at=captured_at,
                    ) for value in values
                ])
        except Exception as exc:
            if image_path is not None:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    logger.error(f"[FaceRecognition] 失败截图清理失败：{type(cleanup_error).__name__}")
            self._retry_at = now + RECORD_RETRY_SECONDS
            # 不输出 SQL 参数，避免人员信息进入错误日志。
            logger.error(f"[FaceRecognition] 摄像头 {camera_id} 识别记录写入失败：{type(exc).__name__}")
            return 0
        self._recorded_at.update(dict.fromkeys(candidates, now))
        if unknowns:
            self._unknown_recorded_at[camera_id] = now
        return len(values)


def get_recognition_image(record_id: int) -> Path | None:
    from AiVision.platform.camera.orm import AiCameraConfig

    with get_session() as session:
        image_path = session.scalar(select(FaceRecognitionRecord.image_path).join(
            AiCameraConfig, AiCameraConfig.id == FaceRecognitionRecord.camera_id,
        ).where(
            FaceRecognitionRecord.id == record_id,
            AiCameraConfig.department == "electronics_electrician",
        ))
    if not image_path:
        return None
    path = Path(image_path).resolve()
    root = Path(settings.storage.data_path).expanduser().resolve() / "recognize_face"
    return path if path.is_relative_to(root) and path.is_file() else None


def list_recognition_records(camera_id: int | None, page: int, page_size: int) -> RecognitionRecordPage:
    from AiVision.platform.camera.orm import AiCameraConfig

    filters = [AiCameraConfig.department == "electronics_electrician"]
    if camera_id is not None:
        filters.append(FaceRecognitionRecord.camera_id == camera_id)
    with get_session() as session:
        statement = select(FaceRecognitionRecord).join(
            AiCameraConfig, AiCameraConfig.id == FaceRecognitionRecord.camera_id,
        ).where(*filters)
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        records = session.scalars(statement.order_by(
            FaceRecognitionRecord.recognized_at.desc(), FaceRecognitionRecord.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size)).all()
        return RecognitionRecordPage(
            total=total, page=page, page_size=page_size,
            items=[RecognitionRecordItem.model_validate(record) for record in records],
        )
