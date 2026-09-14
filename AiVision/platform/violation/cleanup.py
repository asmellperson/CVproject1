"""报警媒体引用：AiAlarmEvent 事务由此处理，媒体策略复用通用清理器。"""
from __future__ import annotations

from AiVision.core.db import session_scope
from AiVision.core.media_cleanup import CLEANUP_BATCH_SIZE, MediaCleaner, MediaRecord
from .orm import AiAlarmEvent

ALARM_MEDIA_DIRECTORIES = tuple(str(value) for value in range(1, 11)) + ("alarm_clips",)


class ViolationMediaCleaner(MediaCleaner):
    media_directories = ALARM_MEDIA_DIRECTORIES

    def __init__(self, data_path, *, retention_days: int, max_bytes: int,
                 session_scope_factory=session_scope):
        self._session_scope = session_scope_factory
        super().__init__(data_path, retention_days=retention_days, max_bytes=max_bytes, references=(self,))

    def iter_records(self, before):
        cursor = None
        while True:
            with self._session_scope() as session:
                query = session.query(AiAlarmEvent.id, AiAlarmEvent.create_time,
                                      AiAlarmEvent.image_path, AiAlarmEvent.video_path).filter(
                    AiAlarmEvent.create_time < before,
                )
                if cursor is not None:
                    timestamp, record_id = cursor
                    query = query.filter(
                        (AiAlarmEvent.create_time > timestamp)
                        | ((AiAlarmEvent.create_time == timestamp) & (AiAlarmEvent.id > record_id))
                    )
                rows = query.order_by(AiAlarmEvent.create_time, AiAlarmEvent.id).limit(CLEANUP_BATCH_SIZE).all()
            if not rows:
                return
            cursor = (rows[-1].create_time, rows[-1].id)
            for row in rows:
                yield MediaRecord(row.id, row.create_time, tuple(path for path in (row.image_path, row.video_path) if path))

    def delete_record(self, record, remove_file):
        with self._session_scope() as session:
            row = session.get(AiAlarmEvent, record.id)
            if row is None or row.create_time != record.created_at:
                return 0
            # 重新读取视频状态，避免扫描之后完成的视频被遗留。
            image_removed = remove_file(row.image_path)
            video_removed = not row.video_path or remove_file(row.video_path)
            if not image_removed or not video_removed:
                return 0
            session.delete(row)
        return 1

    def referenced_paths(self, paths):
        raw_paths = [str(path) for path in paths]
        with self._session_scope() as session:
            image_paths = {str(path) for (path,) in session.query(AiAlarmEvent.image_path).filter(
                AiAlarmEvent.image_path.in_(raw_paths),
            ).all()}
            video_paths = {str(path) for (path,) in session.query(AiAlarmEvent.video_path).filter(
                AiAlarmEvent.video_path.in_(raw_paths),
            ).all() if path}
        return image_paths | video_paths
