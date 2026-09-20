"""认证、用户管理和访问审计 API，由 AiVision 唯一挂载。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from auth.auth import (
    AuthError,
    UserConflictError,
    UserNotFoundError,
    UserStoreError,
    UserValidationError,
    change_own_password,
    clear_auth_cookie,
    create_auth_user,
    create_token,
    delete_auth_user,
    get_current_user,
    list_auth_users,
    require_admin,
    reset_auth_user_password,
    set_auth_cookie,
    update_auth_user,
    verify_login,
)
from auth.access_audit import (
    DEFAULT_ACCESS_AUDIT_LIMIT,
    MAX_ACCESS_AUDIT_LIMIT,
    access_audit_store,
    add_access_audit_capability,
    require_access_audit_owner,
)
from auth.schema import (
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    AdminUserPasswordResetRequest,
    LoginRequest,
    ChangePasswordRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


def _record_visit(user: dict) -> None:
    try:
        access_audit_store.record_visit(user)
    except (SQLAlchemyError, ValueError) as exc:
        logger.error(
            "记录平台访问失败 employee_id=%s error=%s",
            user["employee_id"],
            type(exc).__name__,
        )


def _raise_user_management_http_error(exc: UserStoreError) -> None:
    if isinstance(exc, UserNotFoundError):
        status_code = 404
    elif isinstance(exc, UserConflictError):
        status_code = 409
    elif isinstance(exc, UserValidationError):
        status_code = 400
    else:
        status_code = 500
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    user = verify_login(payload.employee_id, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid employee_id or password")
    token = create_token(user)
    set_auth_cookie(response, token, request)
    _record_visit(user)
    return {"success": True, "user": add_access_audit_capability(user)}


@router.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    _record_visit(user)
    return {"success": True, "user": add_access_audit_capability(user)}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    clear_auth_cookie(response, request)
    return {"success": True}


@router.post("/api/auth/password")
def change_password(
    payload: ChangePasswordRequest, user: dict = Depends(get_current_user)
):
    try:
        updated_user = change_own_password(
            user.get("employee_id", ""),
            payload.current_password,
            payload.new_password,
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "user": add_access_audit_capability(updated_user),
    }


@router.get("/api/admin/access-audit")
def access_audit(
    limit: int = Query(
        default=DEFAULT_ACCESS_AUDIT_LIMIT,
        ge=1,
        le=MAX_ACCESS_AUDIT_LIMIT,
    ),
    owner: dict = Depends(require_access_audit_owner),
):
    del owner
    return {"items": access_audit_store.list_recent(limit)}


@router.get("/api/admin/users")
def admin_list_users(admin: dict = Depends(require_admin)):
    del admin
    try:
        return {"items": list_auth_users()}
    except UserStoreError as exc:
        _raise_user_management_http_error(exc)


@router.post("/api/admin/users")
def admin_create_user(
    payload: AdminUserCreateRequest,
    admin: dict = Depends(require_admin),
):
    del admin
    try:
        user = create_auth_user(
            employee_id=payload.employee_id,
            name=payload.name,
            role=payload.role,
            password=payload.password,
            departments=payload.departments,
        )
        return {"success": True, "user": user}
    except UserStoreError as exc:
        _raise_user_management_http_error(exc)


@router.patch("/api/admin/users/{employee_id}")
def admin_update_user(
    employee_id: str,
    payload: AdminUserUpdateRequest,
    admin: dict = Depends(require_admin),
):
    try:
        user = update_auth_user(
            employee_id,
            actor_employee_id=str(admin.get("employee_id", "")),
            name=payload.name,
            role=payload.role,
            enabled=payload.enabled,
            departments=payload.departments,
        )
        return {"success": True, "user": user}
    except UserStoreError as exc:
        _raise_user_management_http_error(exc)


@router.post("/api/admin/users/{employee_id}/reset-password")
def admin_reset_user_password(
    employee_id: str,
    payload: AdminUserPasswordResetRequest,
    admin: dict = Depends(require_admin),
):
    del admin
    try:
        user = reset_auth_user_password(
            employee_id,
            new_password=payload.new_password,
        )
        return {"success": True, "user": user}
    except UserStoreError as exc:
        _raise_user_management_http_error(exc)


@router.delete("/api/admin/users/{employee_id}")
def admin_delete_user(
    employee_id: str,
    admin: dict = Depends(require_admin),
):
    try:
        delete_auth_user(
            employee_id,
            actor_employee_id=str(admin.get("employee_id", "")),
        )
        return {"success": True}
    except UserStoreError as exc:
        _raise_user_management_http_error(exc)
