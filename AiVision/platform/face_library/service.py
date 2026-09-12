"""人员资料查询与整来源快照写入；一次写入使用一个数据库事务。"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select

from AiVision.connectors.hikvision import HikvisionPerson
from AiVision.core.db import get_session, session_scope

from . import HIKVISION_SOURCES, PersonSyncError
from .orm import FacePerson


@dataclass(frozen=True)
class SyncCounts:
    total: int
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


class FaceLibraryService:
    @staticmethod
    def _require_source(source: str) -> None:
        if source not in HIKVISION_SOURCES:
            raise ValueError("hik_source must be one or two")

    def get_person(self, source: str, person_id: str) -> FacePerson | None:
        self._require_source(source)
        with get_session() as session:
            return session.query(FacePerson).filter_by(hik_source=source, hik_person_id=person_id).one_or_none()

    def list_persons(self, source: str, *, is_active: bool | None = None) -> list[FacePerson]:
        self._require_source(source)
        with get_session() as session:
            query = session.query(FacePerson).filter_by(hik_source=source)
            if is_active is not None:
                query = query.filter_by(is_active=is_active)
            return query.order_by(FacePerson.id).all()

    def apply_snapshot(self, source: str, persons: Sequence[HikvisionPerson]) -> SyncCounts:
        """调用方必须已完整获取该来源所有页；异常时整批回滚。

        完全相同的记录不发出 UPDATE，所有时间戳保持不变。
        last_synced_at 记录最近一次实际写入（包括重新启用和停用）的同步时间。
        """
        self._require_source(source)
        person_ids = {person.person_id for person in persons}
        if len(person_ids) != len(persons):
            raise ValueError("Snapshot contains duplicate personId values")

        inserted = updated = unchanged = deactivated = 0
        with session_scope() as session:
            existing = {
                person.hik_person_id: person
                for person in session.query(FacePerson).filter_by(hik_source=source).with_for_update().all()
            }
            if not persons and any(person.is_active for person in existing.values()):
                raise PersonSyncError(f"{source} 完整分页总数为 0，但数据库仍有 active 人员，已拒绝本次同步")
            synced_at = session.scalar(select(func.current_timestamp()))
            for person in persons:
                photo = person.person_photo
                values = {
                    "person_name": person.person_name,
                    "person_code": person.person_code,
                    "job_no": person.job_no,
                    "org_index_code": person.org_index_code,
                    "pic_uri": photo.pic_uri if photo is not None else None,
                    "server_index_code": photo.server_index_code if photo is not None else None,
                    "is_active": True,
                }
                stored = existing.get(person.person_id)
                if stored is None:
                    session.add(FacePerson(
                        hik_source=source, hik_person_id=person.person_id,
                        **values, last_synced_at=synced_at,
                    ))
                    inserted += 1
                elif any(getattr(stored, key) != value for key, value in values.items()):
                    for key, value in values.items():
                        setattr(stored, key, value)
                    stored.last_synced_at = synced_at
                    updated += 1
                else:
                    unchanged += 1

            for person_id, stored in existing.items():
                if person_id not in person_ids and stored.is_active:
                    stored.is_active = False
                    stored.last_synced_at = synced_at
                    deactivated += 1
        return SyncCounts(len(persons), inserted, updated, unchanged, deactivated)
