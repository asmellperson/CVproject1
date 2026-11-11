"""共享 MySQL 中的用户读写与账号约束。"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from AiVision.core.db import get_session
from AiVision.departments.department_registry import require_department
from auth.orm import AuthUser

ALLOWED_ROLES = {"admin", "department_admin", "viewer"}
PASSWORD_HASH_ITERATIONS = 260_000


class UserStoreError(RuntimeError):
    """账号操作失败。"""


class UserValidationError(UserStoreError):
    """用户提交的数据不合法。"""


class UserConflictError(UserStoreError):
    """操作与现有账号状态冲突。"""


class UserNotFoundError(UserStoreError):
    """目标用户不存在。"""


def _normalize_required(value: object, label: str, max_length: int) -> str:
    """清洗数据"""
    normalized = str(value or "").strip()
    if not normalized:
        raise UserValidationError(f"{label}不能为空")
    if len(normalized) > max_length:
        raise UserValidationError(f"{label}不能超过 {max_length} 个字符")
    return normalized


def _normalize_role_departments(
    role: object,
    departments: object,
) -> tuple[str, list[str]]:
    """统一验证角色，并把部门数据标准化"""
    # role和departments列表
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in ALLOWED_ROLES:
        raise UserValidationError("角色必须是 admin、department_admin 或 viewer")
    if normalized_role == "admin":
        if departments is not None:
            if not isinstance(departments, list):
                raise UserValidationError("事业部必须是数组")
            for department in departments:
                if department != "all":
                    try:
                        require_department(department)
                    except ValueError as exc:
                        raise UserValidationError("必须选择有效事业部") from exc
        return normalized_role, ["all"]

    if isinstance(departments, (list, tuple)):
        raw_departments = list(departments)
    else:
        raise UserValidationError("事业部必须是数组")

    normalized_departments: list[str] = []
    for raw_department in raw_departments:
        try:
            normalized_department = require_department(raw_department)
        except ValueError as exc:
            raise UserValidationError("部门管理员和普通用户必须选择有效事业部") from exc
        # 去重
        if normalized_department not in normalized_departments:
            normalized_departments.append(normalized_department)
    if not normalized_departments:
        raise UserValidationError("部门管理员和普通用户必须至少选择一个有效事业部")
    return normalized_role, normalized_departments


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def hash_password(
    password: str,
    *,
    salt: str | None = None,
    iterations: int = PASSWORD_HASH_ITERATIONS,
) -> str:
    """生成用户数据库使用的 PBKDF2-HMAC-SHA256 密码哈希。"""
    salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${_b64url_encode(digest)}"


def _public_user(row: AuthUser) -> dict[str, Any]:
    return {
        "employee_id": row.employee_id,
        "name": row.name,
        "role": row.role,
        "departments": row.departments,
        "enabled": row.enabled,
        "auth_version": row.auth_version,
    }


def _user_record(row: AuthUser) -> dict[str, Any]:
    return {**_public_user(row), "password_hash": row.password_hash}


class UserStore:
    def __init__(self, session_factory: Callable[[], Session] = get_session):
        self._session_factory = session_factory

    def list_users(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            return [
                _public_user(row)
                for row in session.scalars(
                    select(AuthUser).order_by(AuthUser.employee_id)
                )
            ]

    def get_user_record(self, employee_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            row = session.get(AuthUser, employee_id.strip())
            if row is None:
                raise UserNotFoundError("用户不存在")
            return _user_record(row)

    def find_enabled_user(self, identifier: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(AuthUser)
                .where(
                    AuthUser.enabled.is_(True),
                    or_(
                        AuthUser.employee_id == identifier.strip(),
                        AuthUser.name == identifier.strip(),
                    ),
                )
                .order_by(AuthUser.employee_id)
                .limit(1)
            )
            return _user_record(row) if row is not None else None

    @staticmethod
    def _locked_users(session: Session) -> dict[str, AuthUser]:
        # 账号管理写操作按工号加锁，避免并发降权或删除绕过最后一个管理员约束。
        return {
            row.employee_id: row
            for row in session.scalars(
                select(AuthUser).order_by(AuthUser.employee_id).with_for_update()
            )
        }

    @staticmethod
    def _require_user(users: dict[str, AuthUser], employee_id: str) -> AuthUser:
        if employee_id not in users:
            raise UserNotFoundError("用户不存在")
        return users[employee_id]

    def create_user(
        self,
        *,
        employee_id: str,
        name: str,
        role: str,
        password_hash: str,
        departments: list[str] | None,
    ) -> dict[str, Any]:
        employee_id = _normalize_required(employee_id, "工号", 64)
        name = _normalize_required(name, "姓名", 128)
        role, departments = _normalize_role_departments(role, departments)
        if not password_hash:
            raise UserValidationError("密码哈希不能为空")
        try:
            with self._session_factory() as session, session.begin():
                users = self._locked_users(session)
                if employee_id in users:
                    raise UserConflictError("工号已存在")
                if any(user.name == name for user in users.values()):
                    raise UserConflictError("姓名已存在")
                row = AuthUser(
                    employee_id=employee_id,
                    name=name,
                    role=role,
                    departments=departments,
                    password_hash=password_hash,
                )
                session.add(row)
                session.flush()
                return _public_user(row)
        except IntegrityError as exc:
            raise UserConflictError("工号或姓名已存在") from exc

    def update_user(
        self,
        employee_id: str,
        *,
        actor_employee_id: str,
        name: str,
        role: str,
        enabled: bool,
        departments: list[str] | None,
    ) -> dict[str, Any]:
        employee_id = _normalize_required(employee_id, "工号", 64)
        actor_employee_id = _normalize_required(actor_employee_id, "当前管理员工号", 64)
        name = _normalize_required(name, "姓名", 128)
        role, departments = _normalize_role_departments(role, departments)
        if employee_id == actor_employee_id and not enabled:
            raise UserConflictError("不能禁用当前登录管理员")
        try:
            with self._session_factory() as session, session.begin():
                users = self._locked_users(session)
                row = self._require_user(users, employee_id)
                if any(
                    user.name == name and user.employee_id != employee_id
                    for user in users.values()
                ):
                    raise UserConflictError("姓名已存在")
                if (
                    row.enabled
                    and row.role == "admin"
                    and (not enabled or role != "admin")
                ):
                    if (
                        sum(
                            user.enabled and user.role == "admin"
                            for user in users.values()
                        )
                        <= 1
                    ):
                        raise UserConflictError("不能变更最后一个已启用管理员")
                if row.role != role or row.departments != departments:
                    # 角色或部门变更后使旧会话失效，避免页面保留过期管理入口。
                    row.auth_version += 1
                row.name, row.role, row.departments, row.enabled = (
                    name,
                    role,
                    departments,
                    enabled,
                )
                session.flush()
                return _public_user(row)
        except IntegrityError as exc:
            raise UserConflictError("姓名已存在") from exc

    def update_password_hash(
        self, employee_id: str, password_hash: str
    ) -> dict[str, Any]:
        employee_id = _normalize_required(employee_id, "工号", 64)
        if not password_hash:
            raise UserValidationError("密码哈希不能为空")
        with self._session_factory() as session, session.begin():
            row = session.get(AuthUser, employee_id, with_for_update=True)
            if row is None:
                raise UserNotFoundError("用户不存在")
            row.password_hash = password_hash
            row.auth_version += 1
            session.flush()
            return _public_user(row)

    def delete_user(self, employee_id: str, *, actor_employee_id: str) -> None:
        employee_id = _normalize_required(employee_id, "工号", 64)
        actor_employee_id = _normalize_required(actor_employee_id, "当前管理员工号", 64)
        if employee_id == actor_employee_id:
            raise UserConflictError("不能删除当前登录管理员")
        with self._session_factory() as session, session.begin():
            users = self._locked_users(session)
            row = self._require_user(users, employee_id)
            if row.enabled and row.role == "admin":
                if (
                    sum(
                        user.enabled and user.role == "admin" for user in users.values()
                    )
                    <= 1
                ):
                    raise UserConflictError("不能删除最后一个已启用管理员")
            session.delete(row)
