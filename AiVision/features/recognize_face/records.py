"""识别记录写入与查询；冷却状态留在 Consumer 所属进程内。"""
from __future__ import annotations

import time

from sqlalchemy import func, select

from AiVision.core.db import get_session, session_scope
from AiVision.core.logger import logger
from .orm import FaceRecognitionRecord
from .schema import RecognitionRecordItem, RecognitionRecordPage

RECORD_RETRY_SECONDS = 5.0


class RecognitionRecorder:
    def __init__(self):
        self._recorded_at: dict[tuple[int, int | None], float] = {}
        self._retry_at = 0.0

    def clear_camera(self, camera_id: int) -> None:
        self._recorded_at = {key: value for key, value in self._recorded_at.items() if key[0] != camera_id}

    def record(self, camera_id: int, detections: list[dict], cooldown_seconds: float) -> int:
        now = time.monotonic()
        if now < self._retry_at:
            return 0
        candidates: dict[tuple[int, int | None], dict] = {}
        for detection in detections:
            key = (camera_id, detection["person_id"])
            if now - self._recorded_at.get(key, float("-inf")) < cooldown_seconds:
                continue
            if key not in candidates or detection["similarity"] > candidates[key]["similarity"]:
                candidates[key] = detection
        if not candidates:
            return 0
        try:
            with session_scope() as session:
                session.add_all([
                    FaceRecognitionRecord(
                        camera_id=camera_id, person_id=value["person_id"],
                        person_name=value["person_name"], similarity=value["similarity"],
                    ) for value in candidates.values()
                ])
        except Exception as exc:
            self._retry_at = now + RECORD_RETRY_SECONDS
            # 不输出 SQL 参数，避免人员信息进入错误日志。
            logger.error(f"[FaceRecognition] 摄像头 {camera_id} 识别记录写入失败：{type(exc).__name__}")
            return 0
        self._recorded_at.update(dict.fromkeys(candidates, now))
        return len(candidates)


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
