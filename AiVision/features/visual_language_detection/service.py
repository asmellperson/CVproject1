"""视觉理解事件持久化；摄像头参数由公共 FeatureConfigManager 管理。"""

from AiVision.core.db import get_session, session_scope
from .orm import VisualLanguageEventORM
from .schema import VisualLanguageEvent, VisualLanguageHistory


class VisualLanguageService:
    def record(self, *, camera_id, department, kind, text, question, captured_at, latency_seconds):
        with session_scope() as session:
            session.add(VisualLanguageEventORM(
                camera_id=camera_id, department=department, kind=kind, text=text,
                question=question, captured_at=captured_at, latency_seconds=latency_seconds,
            ))

    def history(self, camera_id: int, department: str, limit: int, before_id: int | None):
        with get_session() as session:
            query = session.query(VisualLanguageEventORM).filter_by(camera_id=camera_id, department=department)
            if before_id is not None:
                query = query.filter(VisualLanguageEventORM.id < before_id)
            rows = query.order_by(VisualLanguageEventORM.id.desc()).limit(limit).all()
            return VisualLanguageHistory(items=[VisualLanguageEvent.model_validate(row) for row in rows])
