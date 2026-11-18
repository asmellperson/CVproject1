"""人员资料查询与整来源快照写入；一次写入使用一个数据库事务。"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, or_, select

from AiVision.connectors.hikvision import HikvisionPerson
from AiVision.core.db import get_session, session_scope
from AiVision.departments.department_registry import require_department
from AiVision.features.face_recognition.schema import FacePersonItem, FacePersonPage

from . import HIKVISION_SOURCES, PersonSyncError
from .constants import EMBEDDING_DIM
from .index import encode_embedding, photo_signature
from .orm import FaceEmbedding, FacePerson, FacePersonAuthorization


@dataclass(frozen=True)
class EmbeddingCandidate:
    """生成特征所需的人员与照片元数据，照片定位信息不参与 repr 输出。"""
    person_id: int
    hik_source: str
    pic_uri: str | None = field(repr=False)
    server_index_code: str | None = field(repr=False)
    embedding_model_name: str | None
    embedding_photo_signature: str | None


@dataclass(frozen=True)
class SyncCounts:
    """完整来源快照写入后的新增、更新、未变化和停用计数。"""
    total: int
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


class FaceLibraryService:
    """管理人员资料、通行授权及特征写入，保持数据库事务边界。"""
    def __init__(self, *, authorization_model=FacePersonAuthorization,
                 authorization_scope: Literal["department", "camera_id"] = "department"):
        # 共享人员资料及事务逻辑，功能各自提供授权表，避免不同功能的允许状态互相影响。
        self.authorization_model = authorization_model
        self.authorization_scope = authorization_scope

    def _scope(self, *, department: str | None = None, camera_id: int | None = None) -> dict:
        """按功能声明限定授权范围，禁止摄像头授权回退到事业部。"""
        if self.authorization_scope == "camera_id":
            if department is not None or type(camera_id) is not int or camera_id < 1:
                raise ValueError("围栏授权必须指定有效的摄像头 ID")
            return {"camera_id": camera_id}
        if camera_id is not None:
            raise ValueError("人脸身份识别授权必须指定事业部")
        require_department(department)
        return {"department": department}

    def list_embedding_candidates(self) -> list[EmbeddingCandidate]:
        """列出在用人员及现有特征元数据，由生成任务判断是否需要重建。"""
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
        """锁定人员并重新核对照片签名，防止把旧照片生成的特征写回新资料。"""
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
        """限制查询和写入使用已支持的海康来源标识。"""
        if source not in HIKVISION_SOURCES:
            raise ValueError("hik_source must be one or two")

    def get_person(self, source: str, person_id: str) -> FacePerson | None:
        """按来源复合身份查询人员，避免不同平台的相同人员 ID 冲突。"""
        self._require_source(source)
        with get_session() as session:
            return session.query(FacePerson).filter_by(hik_source=source, hik_person_id=person_id).one_or_none()

    def _person_query(self, session, scope: dict):
        """人员资料共享，允许状态只由当前授权范围内的授权行决定。"""
        authorization = self.authorization_model
        return session.query(
            *FacePerson.__table__.columns,
            authorization.person_id.is_not(None).label("is_allowed"),
        ).select_from(FacePerson).outerjoin(
            authorization,
            (authorization.person_id == FacePerson.id)
            & (getattr(authorization, self.authorization_scope) == scope[self.authorization_scope]),
        )

    def list_persons(
        self, *, department: str | None = None, camera_id: int | None = None,
        page: int = 1, page_size: int = 20, keyword: str | None = None,
        source: str | None = None, is_active: bool | None = None, is_allowed: bool | None = None,
    ) -> FacePersonPage:
        """按来源、当前范围授权及关键字筛选人员，分页计数沿用相同条件。"""
        scope = self._scope(department=department, camera_id=camera_id)
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("页码必须大于零，每页数量须为 1～100")
        if source is not None:
            self._require_source(source)
        with get_session() as session:
            query = self._person_query(session, scope)
            if source is not None:
                query = query.filter(FacePerson.hik_source == source)
            if is_active is not None:
                query = query.filter(FacePerson.is_active.is_(is_active))
            if is_allowed is not None:
                query = query.filter(self.authorization_model.person_id.is_not(None) if is_allowed
                                     else self.authorization_model.person_id.is_(None))
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

    def update_person_allowed(self, person_id: int, is_allowed: bool, *, department: str | None = None,
                              camera_id: int | None = None) -> FacePersonItem | None:
        """只增删指定范围的授权，锁定人员以串行化并发增删，提交后回读结果。"""
        scope = self._scope(department=department, camera_id=camera_id)
        with session_scope() as session:
            person = session.get(FacePerson, person_id, with_for_update=True)
            if person is None:
                return None
            authorization = session.get(self.authorization_model, {**scope, "person_id": person_id})
            if is_allowed and authorization is None:
                session.add(self.authorization_model(**scope, person_id=person_id))
            elif not is_allowed and authorization is not None:
                session.delete(authorization)
        # 提交后重新读取数据库状态，响应包含实际保存值和时间戳。
        with get_session() as session:
            person = self._person_query(session, scope).filter(FacePerson.id == person_id).one_or_none()
            return FacePersonItem.model_validate(person) if person is not None else None

    def get_allowed_person_ids(self, department: str | None = None, *, camera_id: int | None = None) -> set[int]:
        """仅返回当前范围内仍在用且获准通行的人员 ID。"""
        scope = self._scope(department=department, camera_id=camera_id)
        with get_session() as session:
            return set(session.scalars(select(FacePerson.id).join(self.authorization_model).where(
                FacePerson.is_active.is_(True),
                getattr(self.authorization_model, self.authorization_scope) == scope[self.authorization_scope],
            )))

    def get_allowed_person_ids_by_camera(self, camera_ids: Sequence[int]) -> dict[int, set[int]]:
        """一条查询读取本轮摄像头白名单，空名单也保留独立的摄像头条目。"""
        if self.authorization_scope != "camera_id":
            raise ValueError("批量摄像头白名单必须使用摄像头授权范围")
        allowed = {self._scope(camera_id=camera_id)["camera_id"]: set() for camera_id in camera_ids}
        if not allowed:
            return allowed
        authorization = self.authorization_model
        with get_session() as session:
            rows = session.execute(select(authorization.camera_id, FacePerson.id).join(
                FacePerson, authorization.person_id == FacePerson.id,
            ).where(FacePerson.is_active.is_(True), authorization.camera_id.in_(allowed)))
            for camera_id, person_id in rows:
                allowed[camera_id].add(person_id)
        return allowed

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
                # 同步仅覆盖来源字段，事业部通行授权独立保存，不受重同步和停用影响。
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
