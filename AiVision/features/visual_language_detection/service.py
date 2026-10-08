"""视觉理解事件持久化；摄像头参数由公共 FeatureConfigManager 管理。"""

from AiVision.core.db import get_session, session_scope
from .orm import VisualLanguageEventORM
from .schema import VisualLanguageEvent, VisualLanguageHistory


class VisualLanguageService:
    """保存和查询按摄像头及事业部隔离的视频理解事件。"""
    def record(self, *, camera_id, department, kind, text, question, captured_at, latency_seconds):
        """在独立事务中保存一次观察、问题回答或错误事件。"""
        with session_scope() as session:
            session.add(VisualLanguageEventORM(
                camera_id=camera_id, department=department, kind=kind, text=text,
                question=question, captured_at=captured_at, latency_seconds=latency_seconds,
            ))

    def history(self, camera_id: int, department: str, limit: int, before_id: int | None):
        """按事件 ID 倒序读取历史，可用 before_id 继续向前分页。"""
        with get_session() as session:
            query = session.query(VisualLanguageEventORM).filter_by(camera_id=camera_id, department=department)
            if before_id is not None:
                query = query.filter(VisualLanguageEventORM.id < before_id)
            rows = query.order_by(VisualLanguageEventORM.id.desc()).limit(limit).all()
            return VisualLanguageHistory(items=[VisualLanguageEvent.model_validate(row) for row in rows])
