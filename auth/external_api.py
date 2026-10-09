"""平台管理员管理外部系统凭证，外部凭证不能访问管理接口。"""

from contextlib import contextmanager
import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from auth.auth import require_admin
from auth.external import get_external_client_store
from auth.external_schema import (
    ExternalClientCreate,
    ExternalClientEnabled,
    ExternalClientInfo,
    ExternalClientIssued,
    ExternalClientUpdate,
)
from auth.external_store import ExternalClientNotFound

logger = logging.getLogger(__name__)


def no_store(response: Response):
    """凭证管理响应不进入浏览器或代理缓存。"""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/admin/external-clients",
    tags=["external-client-admin"],
    dependencies=[Depends(require_admin), Depends(no_store)],
)


@contextmanager
def client_errors():
    try:
        yield
    except ExternalClientNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("", response_model=list[ExternalClientInfo])
def list_clients(store=Depends(get_external_client_store)):
    """列出授权信息；不返回历史密钥或摘要。"""
    return store.list_clients()


@router.post("", response_model=ExternalClientIssued, status_code=201)
def create_client(
    payload: ExternalClientCreate,
    admin=Depends(require_admin),
    store=Depends(get_external_client_store),
):
    """创建独立对接凭证，明文仅在该响应中提供。"""
    result = store.create(payload, admin["employee_id"])
    logger.info(
        "创建外部凭证 actor=%s client_id=%s", admin["employee_id"], result.client.id
    )
    return result


@router.put("/{client_id}", response_model=ExternalClientInfo)
def update_client(
    client_id: str,
    payload: ExternalClientUpdate,
    admin=Depends(require_admin),
    store=Depends(get_external_client_store),
):
    """全量更新授权范围和有效期。"""
    with client_errors():
        result = store.update(client_id, payload)
    logger.info("修改外部授权 actor=%s client_id=%s", admin["employee_id"], client_id)
    return result


@router.put("/{client_id}/enabled", response_model=ExternalClientInfo)
def enable_client(
    client_id: str,
    payload: ExternalClientEnabled,
    admin=Depends(require_admin),
    store=Depends(get_external_client_store),
):
    """启停凭证不改变密钥和有效期。"""
    with client_errors():
        result = store.set_enabled(client_id, payload.enabled)
    logger.info(
        "切换外部凭证 actor=%s client_id=%s enabled=%s",
        admin["employee_id"],
        client_id,
        payload.enabled,
    )
    return result


@router.post("/{client_id}/rotate", response_model=ExternalClientIssued)
def rotate_client(
    client_id: str,
    admin=Depends(require_admin),
    store=Depends(get_external_client_store),
):
    """更换密钥并立即使旧密钥失效，保留当前授权及停用状态。"""
    with client_errors():
        result = store.rotate(client_id)
    logger.info("轮换外部凭证 actor=%s client_id=%s", admin["employee_id"], client_id)
    return result
