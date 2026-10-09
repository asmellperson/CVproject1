"""外部凭证的持久化和摘要校验，不依赖人员账号。"""

import hashlib
import hmac
import re
import secrets
from datetime import timezone
from uuid import uuid4

from sqlalchemy import select

from AiVision.core.db import get_session
from auth.external_schema import (
    ExternalClientCreate,
    ExternalClientInfo,
    ExternalClientIssued,
    ExternalClientUpdate,
)
from auth.orm import ExternalClient, utc_now

KEY_PREFIX = "aicv_ext_"
KEY_PATTERN = re.compile(r"aicv_ext_([a-f0-9]{32})\.([A-Za-z0-9_-]{43})")


class ExternalCredentialError(ValueError):
    """凭证缺失、无效、停用或过期，统一返回不含密钥的错误。"""


class ExternalClientNotFound(ValueError):
    """指定外部系统不存在。"""


def _info(row: ExternalClient) -> ExternalClientInfo:
    """数据库按 UTC 存储无时区时间，对外显式补充 UTC 标记。"""
    return ExternalClientInfo(
        id=row.id,
        name=row.name,
        departments=row.departments,
        scopes=row.scopes,
        enabled=row.enabled,
        expires_at=row.expires_at.replace(tzinfo=timezone.utc),
        created_by=row.created_by,
        created_at=row.created_at.replace(tzinfo=timezone.utc),
        updated_at=row.updated_at.replace(tzinfo=timezone.utc),
    )


def _new_key(client_id: str) -> tuple[str, str]:
    """高熵随机密钥无需可逆存储，摘要比较使用常量时间函数。"""
    key = f"{KEY_PREFIX}{client_id}.{secrets.token_urlsafe(32)}"
    return key, hashlib.sha256(key.encode("ascii")).hexdigest()


class ExternalClientStore:
    """每次认证重新读取授权记录，使撤销与轮换不依赖缓存过期。"""

    def __init__(self, session_factory=get_session):
        self._session_factory = session_factory

    def list_clients(self) -> list[ExternalClientInfo]:
        with self._session_factory() as session:
            return [
                _info(row)
                for row in session.scalars(
                    select(ExternalClient).order_by(
                        ExternalClient.created_at.desc(), ExternalClient.id
                    )
                )
            ]

    def create(self, payload: ExternalClientCreate, actor: str) -> ExternalClientIssued:
        client_id = uuid4().hex
        key, digest = _new_key(client_id)
        with self._session_factory() as session, session.begin():
            row = ExternalClient(
                id=client_id,
                name=payload.name,
                key_digest=digest,
                departments=payload.departments,
                scopes=payload.scopes,
                enabled=True,
                expires_at=payload.expires_at.replace(tzinfo=None),
                created_by=actor,
            )
            session.add(row)
            session.flush()
            result = ExternalClientIssued(client=_info(row), api_key=key)
        return result

    @staticmethod
    def _locked(session, client_id: str) -> ExternalClient:
        row = session.get(ExternalClient, client_id, with_for_update=True)
        if row is None:
            raise ExternalClientNotFound("外部系统不存在")
        return row

    def update(
        self, client_id: str, payload: ExternalClientUpdate
    ) -> ExternalClientInfo:
        with self._session_factory() as session, session.begin():
            row = self._locked(session, client_id)
            for field in ("name", "departments", "scopes", "enabled"):
                setattr(row, field, getattr(payload, field))
            row.expires_at = payload.expires_at.replace(tzinfo=None)
            session.flush()
            result = _info(row)
        return result

    def set_enabled(self, client_id: str, enabled: bool) -> ExternalClientInfo:
        with self._session_factory() as session, session.begin():
            row = self._locked(session, client_id)
            row.enabled = enabled
            session.flush()
            result = _info(row)
        return result

    def rotate(self, client_id: str) -> ExternalClientIssued:
        with self._session_factory() as session, session.begin():
            row = self._locked(session, client_id)
            key, digest = _new_key(row.id)
            row.key_digest = digest
            session.flush()
            result = ExternalClientIssued(client=_info(row), api_key=key)
        return result

    def authenticate(self, api_key: str) -> ExternalClientInfo:
        match = KEY_PATTERN.fullmatch(api_key)
        if match is None:
            raise ExternalCredentialError("外部凭证无效或已失效")
        with self._session_factory() as session:
            row = session.get(ExternalClient, match.group(1))
            if (
                row is None
                or not row.enabled
                or row.expires_at <= utc_now()
                or not hmac.compare_digest(
                    row.key_digest, hashlib.sha256(api_key.encode("ascii")).hexdigest()
                )
            ):
                raise ExternalCredentialError("外部凭证无效或已失效")
            return _info(row)


external_client_store = ExternalClientStore()
