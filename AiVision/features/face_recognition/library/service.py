"""人员资料查询与整来源快照写入；一次写入使用一个数据库事务。"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select

from AiVision.connectors.hikvision import HikvisionPerson
from AiVision.core.db import get_session, session_scope
from AiVision.features.face_recognition.schema import FacePersonItem, FacePersonPage

from . import HIKVISION_SOURCES, PersonSyncError
from .constants import EMBEDDING_DIM
from .index import encode_embedding, photo_signature
from .orm import FaceEmbedding, FacePerson


@dataclass(frozen=True)
class EmbeddingCandidate:
    person_id: int
    hik_source: str
    pic_uri: str | None = field(repr=False)
    server_index_code: str | None = field(repr=False)
    embedding_model_name: str | None
    embedding_photo_signature: str | None


@dataclass(frozen=True)
class SyncCounts:
    total: int
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


class FaceLibraryService:
    def list_embedding_candidates(self) -> list[EmbeddingCandidate]:
        with get_session() as session:
            rows = session.query(FacePerson, FaceEmbedding).outerjoin(
                FaceEmbedding, FaceEmbedding.person_id == FacePerson.id,
            ).filter(FacePerson.is_active.is_(True)).order_by(FacePerson.id).all()
            return [EmbeddingCandidate(
                person.id, person.hik_source, person.pic_uri, person.server_index_code,
                embedding.model_name if embedding is not None else None,
                embedding.photo_signature if embedding is not None else None,
            ) for person, embedding in rows]

    def save_embedding(self, person_id: int, embedding, *, model_name: str, signature: str) -> None:
        data = encode_embedding(embedding)
        with session_scope() as session:
            person = session.query(FacePerson).filter_by(id=person_id).with_for_update().one()
            if not person.is_active or not person.pic_uri or not person.server_index_code:
                raise PersonSyncError("人员已停用或照片字段已移除，本次特征不写入")
            if photo_signature(person.pic_uri, person.server_index_code) != signature:
                raise PersonSyncError("生成期间人员照片发生变化，本次特征不写入")
            stored = session.query(FaceEmbedding).filter_by(person_id=person_id).one_or_none()
            if stored is None:
                stored = FaceEmbedding(person_id=person_id)
                session.add(stored)
            stored.embedding = data
            stored.embedding_dim = EMBEDDING_DIM
            stored.model_name = model_name
            stored.photo_signature = signature

    @staticmethod
    def _require_source(source: str) -> None:
        if source not in HIKVISION_SOURCES:
            raise ValueError("hik_source must be one or two")

    def get_person(self, source: str, person_id: str) -> FacePerson | None:
        self._require_source(source)
        with get_session() as session:
            return session.query(FacePerson).filter_by(hik_source=source, hik_person_id=person_id).one_or_none()

    def list_persons(
        self, *, page: int = 1, page_size: int = 20, keyword: str | None = None,
        source: str | None = None, is_active: bool | None = None, is_allowed: bool | None = None,
    ) -> FacePersonPage:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("页码必须大于零，每页数量须为 1～100")
        if source is not None:
            self._require_source(source)
        with get_session() as session:
            query = session.query(FacePerson)
            if source is not None:
                query = query.filter_by(hik_source=source)
            if is_active is not None:
                query = query.filter_by(is_active=is_active)
            if is_allowed is not None:
                query = query.filter_by(is_allowed=is_allowed)
            if keyword and keyword.strip():
                query = query.filter(or_(*(column.icontains(keyword.strip(), autoescape=True) for column in (
                    FacePerson.person_name, FacePerson.job_no, FacePerson.person_code,
                    FacePerson.hik_person_id, FacePerson.org_index_code,
                ))))
            total = query.count()
            persons = query.order_by(FacePerson.id).offset((page - 1) * page_size).limit(page_size).all()
            return FacePersonPage(
                total=total, page=page, page_size=page_size,
                items=[FacePersonItem.model_validate(person) for person in persons],
            )

    def update_person_allowed(self, person_id: int, is_allowed: bool) -> FacePersonItem | None:
        with session_scope() as session:
            person = session.get(FacePerson, person_id, with_for_update=True)
            if person is None:
                return None
            person.is_allowed = is_allowed
        # 提交后重新读取数据库状态，响应包含实际保存值和时间戳。
        with get_session() as session:
            person = session.get(FacePerson, person_id)
            return FacePersonItem.model_validate(person) if person is not None else None

    def get_allowed_person_ids(self) -> set[int]:
        with get_session() as session:
            return set(session.scalars(select(FacePerson.id).where(
                FacePerson.is_active.is_(True), FacePerson.is_allowed.is_(True),
            )))

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
                # 同步仅覆盖来源字段；本地 is_allowed 在停用、重新激活和重同步时均保留。
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
