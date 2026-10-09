"""外部接口的系统认证，与人员 Cookie/JWT 完全独立。"""

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from auth.external_schema import ExternalClientInfo, INSPECTION_READ, INSPECTION_WRITE
from auth.external_store import ExternalCredentialError, external_client_store

EXTERNAL_API_PREFIX = "/api/external"
api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="ExternalApiKey",
    auto_error=False,
    description="外部系统凭证，由受控服务端或代理保管，限授权事业部与操作。",
)


def get_external_client_store():
    return external_client_store


def get_external_client(
    request: Request,
    api_key: str | None = Security(api_key_header),
    store=Depends(get_external_client_store),
) -> ExternalClientInfo:
    """只接收单个请求头凭证，不接受 URL 参数或人员登录回退。"""
    if not api_key or len(request.headers.getlist("X-API-Key")) != 1:
        raise HTTPException(401, "请提供有效的 X-API-Key 对接凭证")
    try:
        return store.authenticate(api_key)
    except ExternalCredentialError as exc:
        raise HTTPException(401, str(exc)) from exc


def inspection_reader(
    client: ExternalClientInfo = Depends(get_external_client),
) -> ExternalClientInfo:
    if INSPECTION_READ not in client.scopes:
        raise HTTPException(403, "凭证未获安检读取权限")
    return client


def inspection_writer(
    client: ExternalClientInfo = Depends(inspection_reader),
) -> ExternalClientInfo:
    if INSPECTION_WRITE not in client.scopes:
        raise HTTPException(403, "凭证未获安检配置修改权限")
    return client
