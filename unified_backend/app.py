# 文件说明：定义应用装配的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""统一平台后端入口。

统一后端只做平台级能力和请求转发，不接管各算法子系统的运行逻辑：
- 本地处理登录、当前用户、改密、报警处置状态；
- 转发 Guard Room、AiVision、Security VLM 的业务接口。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from auth.auth import (
    AuthError,
    ChangePasswordRequest,
    LoginRequest,
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
    get_current_user_from_request,
    get_user_store,
    list_auth_users,
    require_admin,
    reset_auth_user_password,
    set_auth_cookie,
    update_auth_user,
    verify_login,
)
from auth.alarm_permissions import DEPARTMENT_EVENT_TYPES, allowed_alarm_event_types
from unified_backend.alarm_dispositions import AlarmDispositionStore, DispositionStoreBusy
from unified_backend.disposition_queries import (
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, DispositionPage, DispositionQueries,
)
from unified_backend.access_audit import (
    DEFAULT_ACCESS_AUDIT_LIMIT,
    MAX_ACCESS_AUDIT_LIMIT,
    AccessAuditStore,
    add_access_audit_capability,
    require_access_audit_owner,
)
from unified_backend.proxy import (
    AsyncProxyClient,
    ProxyRequestError,
    ProxySettings,
    filtered_response_headers,
    stream_response_bytes,
)


logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PLATFORM_STATUS_MAX_WORKERS = 16


# 功能：实现 `_platform_status_max_workers` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`os.getenv`、`str`、`max`、`int`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _platform_status_max_workers() -> int:
    raw_value = os.getenv(
        "UNIFIED_STATUS_MAX_WORKERS",
        str(_DEFAULT_PLATFORM_STATUS_MAX_WORKERS),
    )
    try:
        return max(1, int(raw_value))
    except ValueError:
        return _DEFAULT_PLATFORM_STATUS_MAX_WORKERS


_PLATFORM_STATUS_EXECUTOR = ThreadPoolExecutor(
    max_workers=_platform_status_max_workers(),
    thread_name_prefix="platform-status",
)


# 功能：定义 `AlarmDispositionUpdateRequest` 类，封装应用装配相关的状态、约束与操作
# 参数：
#   - `alarm_id`（str）：`alarm_id` 对应业务对象的唯一标识
#   - `status`（str）：当前或目标状态值
#   - `note`（str）：`note` 对应的业务输入值
# 返回：AlarmDispositionUpdateRequest；返回新建的 `AlarmDispositionUpdateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AlarmDispositionUpdateRequest(BaseModel):
    alarm_id: str
    status: str
    note: str = ""


# 功能：定义 `AdminUserCreateRequest` 类，封装应用装配相关的状态、约束与操作
# 参数：
#   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
#   - `name`（str）：业务对象名称
#   - `role`（str）：`role` 对应的业务输入值
#   - `departments`（list[str] | None）：`departments` 对应的业务输入值
#   - `password`（str）：`password` 对应的业务输入值
# 返回：AdminUserCreateRequest；返回新建的 `AdminUserCreateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AdminUserCreateRequest(BaseModel):
    employee_id: str
    name: str
    role: str
    departments: list[str] | None = None
    password: str


# 功能：定义 `AdminUserUpdateRequest` 类，封装应用装配相关的状态、约束与操作
# 参数：
#   - `name`（str）：业务对象名称
#   - `role`（str）：`role` 对应的业务输入值
#   - `departments`（list[str] | None）：`departments` 对应的业务输入值
#   - `enabled`（bool）：是否启用相应能力
# 返回：AdminUserUpdateRequest；返回新建的 `AdminUserUpdateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AdminUserUpdateRequest(BaseModel):
    name: str
    role: str
    departments: list[str] | None = None
    enabled: bool


# 功能：定义 `AdminUserPasswordResetRequest` 类，封装应用装配相关的状态、约束与操作
# 参数：
#   - `new_password`（str）：`new_password` 对应的业务输入值
# 返回：AdminUserPasswordResetRequest；返回新建的 `AdminUserPasswordResetRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AdminUserPasswordResetRequest(BaseModel):
    new_password: str


# 功能：实现 `_raise_user_management_http_error` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `exc`（UserStoreError）：`exc` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::admin_list_users` 调用本符号；`unified_backend/app.py` 的 `create_app::admin_create_user`
#         调用本符号；`unified_backend/app.py` 的 `create_app::admin_update_user` 调用本符号；`unified_backend/app.py` 的
#         `create_app::admin_reset_user_password` 调用本符号；另有 1 处静态调用
#   - 内部调用：`isinstance`、`HTTPException`、`str`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


ALARM_TYPE_META: dict[str, dict[str, str]] = {
    "blocks": {"name": "区域入侵"},
    "detect_door": {"name": "大门开关"},
    "detect_phone": {"name": "手机检测"},
    "detect_face": {"name": "人脸逗留检测"},
    "detect_human": {"name": "人员违规逗留检测"},
    "detect_logistics_single_person": {"name": "物流通道单人检测"},
    "guard_absent": {"name": "保安离岗"},
    "guard_phone_use": {"name": "保安玩手机"},
    "guard_prone_sleep": {"name": "保安趴睡"},
    "security_vlm_non_compliant": {"name": "安检流程不规范"},
    "security_vlm_error": {"name": "安检判定错误"},
}




GUARD_EVENT_META: dict[str, dict[str, str]] = {
    "absent": {"event_type": "guard_absent", "event_label": "保安离岗"},
    "phone_use": {"event_type": "guard_phone_use", "event_label": "保安玩手机"},
    "prone_sleep": {"event_type": "guard_prone_sleep", "event_label": "保安趴睡"},
}


SECURITY_VLM_DEPARTMENTS = (
    "general_electric",
    "electronics_electrician",
    "electrical_components",
    "precious_metal_recycling",
)

_MAX_AIVISION_CAMERA_ID = 2**31 - 1  # AiCameraConfig.id 使用有符号 SQL Integer。

DEPARTMENT_ALIASES = {
    "ge": "general_electric",
    "general-electric": "general_electric",
    "general electric": "general_electric",
    "electronics-electrician": "electronics_electrician",
    "electronics electrician": "electronics_electrician",
    "electrical-components": "electrical_components",
    "electrical components": "electrical_components",
    "precious-metal-recycling": "precious_metal_recycling",
    "precious metal recycling": "precious_metal_recycling",
    "weida": "precious_metal_recycling",
    "weida_company": "precious_metal_recycling",
    "weida-company": "precious_metal_recycling",
    "weida company": "precious_metal_recycling",
    "伟达": "precious_metal_recycling",
    "伟达公司": "precious_metal_recycling",
    "贵金属回收": "precious_metal_recycling",
    "haoda": "haoda_company",
    "haoda-company": "haoda_company",
    "haoda company": "haoda_company",
    "皓达": "haoda_company",
    "皓达公司": "haoda_company",
}


# 功能：实现 `_now` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_get_json` 调用本符号；`unified_backend/app.py` 的 `_normalize_security_vlm_alarm`
#         调用本符号；`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：`time.time`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _now() -> float:
    return time.time()


# 功能：实现 `_env_url` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `default`（str）：`default` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app` 调用本符号
#   - 内部调用：`os.getenv(name, default).rstrip`、`os.getenv`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _env_url(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


# 功能：实现 `_visual_service_url` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `aivision_url`（str）：`aivision_url` 对应的业务输入值
#   - `service`（str）：`service` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app` 调用本符号
#   - 内部调用：`ValueError`、`aivision_url.rstrip`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _visual_service_url(aivision_url: str, service: str) -> str:
    if service not in {"guard-room", "security-vlm"}:
        raise ValueError(f"unknown visual service: {service}")
    return (
        f"{aivision_url.rstrip('/')}"
        f"/api/integrations/{service}"
    )


def _is_guard_room_api_path(path: str) -> bool:
    """判断统一 `/api` 请求是否属于保安行为规范站点接口。"""
    normalized = str(path or "").strip("/")
    return normalized == "sites" or normalized.startswith("sites/")


# 功能：转换或规范化 `_normalize_department` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`str(value or '').strip`、`str`、`DEPARTMENT_ALIASES.get`、`department.lower`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _normalize_department(value: object) -> str:
    department = str(value or "").strip()
    if not department:
        return ""
    return DEPARTMENT_ALIASES.get(department, DEPARTMENT_ALIASES.get(department.lower(), department))


# 功能：实现 `_departments_for_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
# 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_allowed_event_types_for_user` 调用本符号；`unified_backend/app.py` 的 `_guard_departments_for_user`
#         调用本符号；`unified_backend/app.py` 的 `_security_vlm_departments_for_user` 调用本符号；`unified_backend/app.py` 的
#         `_can_access_security_vlm` 调用本符号
#   - 内部调用：`user.get`、`isinstance`、`_normalize_department`、`departments.append`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _departments_for_user(user: dict[str, Any]) -> list[str]:
    raw_departments = user.get("departments")
    candidates = raw_departments if isinstance(raw_departments, list) else []
    departments: list[str] = []
    for candidate in candidates:
        department = _normalize_department(candidate)
        if department and department not in departments:
            departments.append(department)
    return departments


# 功能：实现 `_cors_origins` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`os.getenv`、`item.strip`、`raw.split`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _cors_origins() -> list[str]:
    raw = os.getenv(
        "AUTH_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://aicv.fudar.com",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


# 功能：实现 `_request_headers` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `request`（Request）：当前 HTTP 请求及上下文
# 返回：dict[str, str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_get_json` 调用本符号；`unified_backend/app.py` 的 `_get_upstream_json`
#         调用本符号；`unified_backend/app.py` 的 `_proxy` 调用本符号
#   - 内部调用：`request.headers.items`、`key.lower`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _request_headers(request: Request) -> dict[str, str]:
    excluded = {"host", "content-length", "connection", "transfer-encoding"}
    return {key: value for key, value in request.headers.items() if key.lower() not in excluded}


# 功能：读取或查询 `_get_json` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `base_url`（str）：`base_url` 对应的业务输入值
#   - `path`（str）：目标路径
#   - `timeout`（float）：允许操作等待的最长秒数；默认值为 `2.0`
#   - `request`（Request | None）：当前 HTTP 请求及上下文；默认值为 `None`
# 返回：tuple[bool, dict | list | None, float | None, str | None]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_now`、`_request_headers`、`requests.get`、`urljoin`、`path.lstrip`、`round`、`response.json`、`str`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
def _get_json(
    base_url: str,
    path: str,
    *,
    timeout: float = 2.0,
    request: Request | None = None,
) -> tuple[bool, dict | list | None, float | None, str | None]:
    started_at = _now()
    try:
        kwargs: dict[str, Any] = {}
        if request is not None:
            kwargs = {
                "headers": _request_headers(request),
                "cookies": request.cookies,
            }
        response = requests.get(
            urljoin(f"{base_url}/", path.lstrip("/")),
            timeout=timeout,
            **kwargs,
        )
        latency_ms = round((_now() - started_at) * 1000, 1)
        if not response.ok:
            return False, None, latency_ms, f"{response.status_code} {response.reason}"
        return True, response.json(), latency_ms, None
    except Exception as exc:
        return False, None, None, str(exc)


# 功能：在平台状态专属的有界线程池中并发执行多个同步上游探测；输入与输出详见下方说明
# 参数：
#   - `calls`（dict[str, tuple[str, str, Request | None]]）：`calls` 对应的业务输入值
# 返回：dict[str, tuple[bool, dict | list | None, float | None, str | None]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：`list`、`_PLATFORM_STATUS_EXECUTOR.submit`、`future.result`、`dict`、`zip`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _get_json_concurrently(
    calls: dict[str, tuple[str, str, Request | None]],
) -> dict[str, tuple[bool, dict | list | None, float | None, str | None]]:
    """在平台状态专属的有界线程池中并发执行多个同步上游探测。"""
    keys = list(calls)
    futures = [
        _PLATFORM_STATUS_EXECUTOR.submit(
            _get_json,
            calls[key][0],
            calls[key][1],
            request=calls[key][2],
        )
        for key in keys
    ]
    results = [future.result() for future in futures]
    return dict(zip(keys, results, strict=True))


# 功能：读取或查询 `_get_upstream_json` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `base_url`（str）：`base_url` 对应的业务输入值
#   - `path`（str）：目标路径
#   - `request`（Request）：当前 HTTP 请求及上下文
#   - `timeout`（float）：允许操作等待的最长秒数；默认值为 `3.0`
# 返回：dict | list | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`requests.get`、`urljoin`、`path.lstrip`、`_request_headers`、`response.json`。
# 副作用/注意事项：可能发起网络请求或发送外部消息。
def _get_upstream_json(base_url: str, path: str, request: Request, *, timeout: float = 3.0) -> dict | list | None:
    try:
        response = requests.get(
            urljoin(f"{base_url}/", path.lstrip("/")),
            headers=_request_headers(request),
            cookies=request.cookies,
            timeout=timeout,
        )
        if not response.ok:
            return None
        return response.json()
    except Exception:
        return None


# 功能：转换或规范化 `_parse_iso_ts` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
# 返回：float | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：`isinstance`、`datetime.fromisoformat(value).timestamp`、`datetime.fromisoformat`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _parse_iso_ts(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


# 功能：转换或规范化 `_parse_alarm_datetime` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
# 返回：datetime | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_alarm_sort_key` 调用本符号；`unified_backend/app.py` 的 `_build_alarm_statistics` 调用本符号
#   - 内部调用：`isinstance`、`value.replace`、`datetime.fromisoformat`、`parsed.astimezone().replace`、`parsed.astimezone`、`datetime.strptime`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _parse_alarm_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


# 功能：实现 `_alarm_sort_key` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm`（dict[str, Any]）：`alarm` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_parse_alarm_datetime`、`alarm.get`、`created.timestamp`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _alarm_sort_key(alarm: dict[str, Any]) -> float:
    created = _parse_alarm_datetime(alarm.get("created_at"))
    return created.timestamp() if created else 0.0


# 功能：实现 `_items_from_payload` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（object）：接口或事件携带的业务数据
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`isinstance`、`payload.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _items_from_payload(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("items") or payload.get("alarms") or []
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


# 功能：转换或规范化 `_normalize_guard_alarm` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm`（dict[str, Any]）：`alarm` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`str`、`alarm.get`、`str(alarm.get('site_name') or '').strip`、`GUARD_EVENT_META.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _normalize_guard_alarm(alarm: dict[str, Any]) -> dict[str, Any]:
    source_id = str(alarm.get("id") or "")
    site_id = alarm.get("site_id")
    site_name = str(alarm.get("site_name") or "").strip()
    raw_type = str(alarm.get("event_type") or "")
    meta = GUARD_EVENT_META.get(raw_type) or {
        "event_type": f"guard_{raw_type}" if raw_type else "guard_alarm",
        "event_label": "保安行为",
    }
    camera_name = site_name or str(alarm.get("camera_name") or "保安行为规范检测")
    normalized_id = f"guard:{site_id}:{source_id}" if site_id is not None else f"guard:{source_id}"
    image_url = f"/api/alarms/{source_id}/image"
    video_url = f"/api/alarms/{source_id}/video" if alarm.get("video_status") == "ready" else None
    if site_id is not None:
        image_url = f"/api/sites/{site_id}/alarms/{source_id}/image"
        video_url = f"/api/sites/{site_id}/alarms/{source_id}/video" if alarm.get("video_status") == "ready" else None
    return {
        **alarm,
        "id": normalized_id,
        "source": "guard_room",
        "source_id": source_id,
        "site_id": site_id,
        "site_name": site_name or None,
        "event_type": meta["event_type"],
        "event_label": meta["event_label"],
        "subject_type": "guard_room_site",
        "subject_id": str(site_id) if site_id is not None else source_id,
        "subject_name": camera_name,
        "camera_no": alarm.get("camera_no"),
        "camera_name": alarm.get("camera_name"),
        "image_url": image_url,
        "video_url": video_url,
    }


# 功能：转换或规范化 `_normalize_aivision_alarm` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm`（dict[str, Any]）：`alarm` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`str`、`alarm.get`、`isinstance`、`dict`、`metadata.get`、`raw_states.items`、`raw_counts.items`、`_normalize_alarm_id_list`、`explicit_names.items`、`camera_states.items`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _normalize_aivision_alarm(alarm: dict[str, Any]) -> dict[str, Any]:
    source_id = str(alarm.get("id") or "")
    raw_metadata = alarm.get("metadata", alarm.get("event_metadata"))
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    subject_type = str(alarm.get("subject_type") or "camera")
    is_channel = subject_type == "logistics_channel"
    raw_event_type = str(alarm.get("event_type") or "unknown")
    violation_type = alarm.get("violation_type")
    feature_name = alarm.get("feature_name")
    event_type = raw_event_type
    department = alarm.get("department")

    channel_id_value = alarm.get("channel_id") or alarm.get("subject_id") or metadata.get("channel_id")
    channel_id = str(channel_id_value) if is_channel and channel_id_value is not None else None
    channel_name = None
    if is_channel:
        channel_name = str(
            alarm.get("channel_name")
            or alarm.get("subject_name")
            or metadata.get("channel_name")
            or alarm.get("camera_name")
            or "物流通道"
        )

    raw_states = metadata.get("camera_states")
    camera_states = {
        str(key): dict(value)
        for key, value in raw_states.items()
        if isinstance(value, dict)
    } if isinstance(raw_states, dict) else {}
    raw_counts = metadata.get("camera_counts")
    camera_counts = {
        str(key): value
        for key, value in raw_counts.items()
        if value is None or (
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
        )
    } if isinstance(raw_counts, dict) else {}
    camera_ids = metadata.get("camera_ids")
    camera_ids = _normalize_alarm_id_list(camera_ids)
    offending_ids = metadata.get("offending_camera_ids")
    offending_ids = _normalize_alarm_id_list(offending_ids)
    explicit_names = metadata.get("camera_names")
    camera_names = {
        str(key): str(value)
        for key, value in explicit_names.items()
        if value is not None
    } if isinstance(explicit_names, dict) else {}
    for key, state in camera_states.items():
        if isinstance(state, dict) and state.get("camera_name") is not None:
            camera_names.setdefault(str(key), str(state["camera_name"]))

    camera_no = alarm.get("camera_no") if not is_channel else None
    camera_name = alarm.get("camera_name") if not is_channel else None
    if is_channel:
        normalized_subject_id = channel_id
        normalized_subject_name = channel_name
    else:
        normalized_subject_id = alarm.get("subject_id") or camera_no
        normalized_subject_name = alarm.get("subject_name") or camera_name or camera_no
    reason = alarm.get("reason") or metadata.get("reason")
    return {
        **alarm,
        "id": f"aivision:{source_id}",
        "source": "aivision",
        "source_id": source_id,
        "event_type": event_type,
        "feature_name": feature_name,
        "violation_type": violation_type,
        "department": department,
        "subject_type": subject_type,
        "subject_id": str(normalized_subject_id) if normalized_subject_id is not None else None,
        "subject_name": normalized_subject_name,
        "camera_no": camera_no,
        "camera_name": camera_name,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "reason": reason,
        "status": alarm.get("status") or (reason if is_channel else None),
        "camera_ids": camera_ids,
        "camera_names": camera_names,
        "camera_counts": camera_counts,
        "camera_states": camera_states,
        "offending_camera_ids": offending_ids,
        "evidence_error": alarm.get("evidence_error") or metadata.get("evidence_error"),
        "metadata": metadata,
        "image_url": alarm.get("image_url") or f"/api/alarms/{source_id}/image",
        "video_url": (
            alarm.get("video_url")
            or (
                f"/api/alarms/{source_id}/video"
                if alarm.get("video_status") == "ready"
                else None
            )
        ),
    }


# 功能：读取或查询 `_normalize_alarm_id_list` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
# 返回：list[int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_normalize_aivision_alarm` 调用本符号
#   - 内部调用：`isinstance`、`set`、`item.strip`、`any`、`int`、`seen.add`、`normalized.append`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _normalize_alarm_id_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    normalized: list[int] = []
    seen: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            camera_id = item
        elif isinstance(item, str):
            raw_camera_id = item.strip()
            if not raw_camera_id or any(char not in "0123456789" for char in raw_camera_id):
                continue
            try:
                camera_id = int(raw_camera_id)
            except (ValueError, OverflowError):
                continue
        else:
            continue
        if not 1 <= camera_id <= _MAX_AIVISION_CAMERA_ID or camera_id in seen:
            continue
        seen.add(camera_id)
        normalized.append(camera_id)
    return normalized


# 功能：转换或规范化 `_normalize_security_vlm_alarm` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `item`（dict[str, Any]）：`item` 对应的业务输入值
#   - `department`（str）：业务部门名称或标识
# 返回：dict[str, Any] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`str`、`item.get`、`int`、`_now`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _normalize_security_vlm_alarm(
    item: dict[str, Any],
    department: str,
) -> dict[str, Any] | None:
    status = str(item.get("status") or "")
    if status not in {"non_compliant", "error"}:
        return None
    source_id = str(item.get("session_id") or f"{item.get('roi_name') or 'security_vlm'}:{item.get('time') or int(_now())}")
    event_type = "security_vlm_error" if status == "error" else "security_vlm_non_compliant"
    return {
        "id": f"security_vlm:{department}:{source_id}",
        "source": "security_vlm",
        "source_id": source_id,
        "department": department,
        "event_type": event_type,
        "event_label": "安检判定错误" if status == "error" else "安检流程不规范",
        "subject_type": "camera",
        "subject_id": str(item.get("camera_id") or item.get("roi_name") or "security_vlm"),
        "subject_name": item.get("camera_name") or item.get("roi_name") or "安检流程规范检测",
        "camera_no": item.get("camera_id") or item.get("roi_name") or "security_vlm",
        "camera_name": item.get("camera_name") or item.get("roi_name") or "安检流程规范检测",
        "reason": item.get("error") or item.get("reason") or "安检流程规范检测判定异常",
        "confidence": 1,
        "created_at": item.get("time"),
        "image_url": None,
        "video_url": None,
        "video_status": None,
    }


# 功能：实现 `_allowed_event_types_for_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
# 返回：set[str] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_filter_alarms` 调用本符号
#   - 内部调用：`str(user.get('role') or '').strip().lower`、`str(user.get('role') or
#          '').strip`、`str`、`user.get`、`set`、`_departments_for_user`、`DEPARTMENT_EVENT_TYPES.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _allowed_event_types_for_user(user: dict[str, Any]) -> set[str] | None:
    return allowed_alarm_event_types(user, _departments_for_user(user))


# 功能：实现 `_guard_departments_for_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
# 返回：list[str] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`str(user.get('role') or '').strip().lower`、`str(user.get('role') or
#          '').strip`、`str`、`user.get`、`_departments_for_user`、`guard_event_types.isdisjoint`、`DEPARTMENT_EVENT_TYPES.get`、`set`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _guard_departments_for_user(user: dict[str, Any]) -> list[str] | None:
    role = str(user.get("role") or "").strip().lower()
    if role == "admin":
        return None
    if role != "viewer":
        return []
    departments = _departments_for_user(user)
    if "all" in departments:
        return None
    guard_event_types = {"guard_absent", "guard_phone_use", "guard_prone_sleep"}
    return [
        department
        for department in departments
        if not guard_event_types.isdisjoint(
            DEPARTMENT_EVENT_TYPES.get(department, set())
        )
    ]


# 功能：检查或判断 `_can_mutate_security_vlm` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
#   - `method`（str）：`method` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_can_access_security_vlm` 调用本符号
#   - 内部调用：`str(method).upper`、`str`、`str(user.get('role') or '').strip().lower`、`str(user.get('role') or '').strip`、`user.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _can_mutate_security_vlm(user: dict[str, Any], method: str) -> bool:
    if str(method).upper() in {"GET", "HEAD", "OPTIONS"}:
        return True
    return str(user.get("role") or "").strip().lower() == "admin"


# 功能：实现 `_security_vlm_departments_for_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
# 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`str(user.get('role') or '').strip().lower`、`str(user.get('role') or
#          '').strip`、`str`、`user.get`、`_departments_for_user`、`list`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _security_vlm_departments_for_user(
    user: dict[str, Any],
) -> list[str]:
    role = str(user.get("role") or "").strip().lower()
    departments = _departments_for_user(user)
    if role == "admin" or "all" in departments:
        return list(SECURITY_VLM_DEPARTMENTS)
    if role == "viewer":
        return [
            department
            for department in SECURITY_VLM_DEPARTMENTS
            if department in departments
        ]
    return []


# 功能：检查或判断 `_can_access_security_vlm` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
#   - `method`（str）：`method` 对应的业务输入值
#   - `path`（str）：目标路径
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::auth_middleware` 调用本符号
#   - 内部调用：`str(user.get('role') or '').strip().lower`、`str(user.get('role') or
#          '').strip`、`str`、`user.get`、`str(path).rstrip`、`normalized_path.endswith`、`_can_mutate_security_vlm`、`_departments_for_user`、`normalized_path.startswith`、`normalized_path[len(prefix):].split`
#          等共 11 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def _can_access_security_vlm(
    user: dict[str, Any],
    method: str,
    path: str,
) -> bool:
    role = str(user.get("role") or "").strip().lower()
    normalized_path = str(path).rstrip("/")
    if normalized_path.endswith("/credentials"):
        return role == "admin"
    if not _can_mutate_security_vlm(user, method):
        return False
    if role == "admin":
        return True
    if role != "viewer":
        return False

    departments = _departments_for_user(user)
    if "all" in departments:
        return True
    prefix = "/security-vlm/api/departments/"
    if normalized_path.startswith(prefix):
        requested = normalized_path[len(prefix):].split("/", 1)[0]
        return requested in departments and requested in SECURITY_VLM_DEPARTMENTS

    # 旧接口只代表通用电气，保留通用电气 viewer 的只读兼容。
    return "general_electric" in departments


# 功能：转换或规范化 `_parse_event_types` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `raw`（str | None）：`raw` 对应的业务输入值
# 返回：set[str] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::unified_alarms` 调用本符号；`unified_backend/app.py` 的 `create_app::unified_statistics`
#         调用本符号
#   - 内部调用：`item.strip`、`raw.split`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _parse_event_types(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    values = {item.strip() for item in raw.split(",") if item.strip()}
    return values or None


# 功能：实现 `_filter_alarms` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarms`（list[dict[str, Any]]）：`alarms` 对应的业务输入值
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
#   - `event_types`（set[str] | None）：`event_types` 对应的业务输入值；默认值为 `None`
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`_allowed_event_types_for_user`、`alarm.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _filter_alarms(
    alarms: list[dict[str, Any]],
    *,
    user: dict[str, Any],
    event_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = _allowed_event_types_for_user(user)
    if allowed is not None:
        alarms = [alarm for alarm in alarms if alarm.get("event_type") in allowed]
    role = str(user.get("role") or "").strip().lower()
    departments = set(_departments_for_user(user))
    if role == "viewer" and "all" not in departments:
        alarms = [
            alarm
            for alarm in alarms
            if (not alarm.get("department") and alarm.get("event_type") != "detect_human")
            or _normalize_department(alarm.get("department")) in departments
        ]
    if event_types is not None:
        alarms = [
            alarm
            for alarm in alarms
            if alarm.get("event_type") in event_types
            or alarm.get("feature_name") in event_types
        ]
    return alarms


# 功能：实现 `_with_disposition` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm`（dict[str, Any]）：`alarm` 对应的业务输入值
#   - `dispositions`（dict[str, dict[str, Any]]）：`dispositions` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`dispositions.get`、`str`、`alarm.get`、`disposition.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _with_disposition(alarm: dict[str, Any], dispositions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    disposition = dispositions.get(str(alarm.get("id") or ""))
    return {
        **alarm,
        "disposition_status": disposition.get("status", "pending") if disposition else "pending",
        "disposition_note": disposition.get("note", "") if disposition else "",
        "disposition_updated_at": disposition.get("updated_at") if disposition else None,
        "disposition_updated_by": disposition.get("updated_by") if disposition else None,
    }


# 功能：实现 `_collect_alarms` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `request`（Request）：当前 HTTP 请求及上下文
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
#   - `guard_room_url`（str）：`guard_room_url` 对应的业务输入值
#   - `aivision_url`（str）：`aivision_url` 对应的业务输入值
#   - `security_vlm_url`（str）：`security_vlm_url` 对应的业务输入值
#   - `disposition_store`（AlarmDispositionStore）：`disposition_store` 对应的业务输入值
#   - `limit`（int）：返回或处理的最大记录数
#   - `event_types`（set[str] | None）：`event_types` 对应的业务输入值；默认值为 `None`
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::unified_alarms` 调用本符号；`unified_backend/app.py` 的 `create_app::unified_statistics`
#         调用本符号
#   - 内部调用：`max`、`_get_upstream_json`、`alarms.extend`、`_normalize_aivision_alarm`、`_items_from_payload`、`_guard_departments_for_user`、`_guard_alarm_paths`、`_normalize_guard_alarm`、`_security_vlm_departments_for_user`、`isinstance`
#          等共 19 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _collect_alarms(
    *,
    request: Request,
    user: dict[str, Any],
    guard_room_url: str,
    aivision_url: str,
    security_vlm_url: str,
    disposition_store: AlarmDispositionStore,
    limit: int,
    event_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    upstream_limit = max(limit, 100)
    alarms: list[dict[str, Any]] = []

    ai_payload = _get_upstream_json(aivision_url, f"/api/alarms?limit={upstream_limit}", request)
    alarms.extend(_normalize_aivision_alarm(item) for item in _items_from_payload(ai_payload))

    guard_departments = _guard_departments_for_user(user)
    if guard_departments is None:
        guard_sites_payload = _get_upstream_json(
            guard_room_url,
            "/api/sites",
            request,
        )
        guard_paths = _guard_alarm_paths(guard_sites_payload, upstream_limit)
        if guard_paths:
            for path in guard_paths:
                guard_payload = _get_upstream_json(guard_room_url, path, request)
                alarms.extend(
                    _normalize_guard_alarm(item)
                    for item in _items_from_payload(guard_payload)
                )
        else:
            guard_payload = _get_upstream_json(
                guard_room_url,
                f"/api/alarms?limit={upstream_limit}",
                request,
            )
            alarms.extend(
                _normalize_guard_alarm(item)
                for item in _items_from_payload(guard_payload)
            )
    else:
        for guard_department in guard_departments:
            guard_sites_payload = _get_upstream_json(
                guard_room_url,
                f"/api/sites?department={guard_department}",
                request,
            )
            for path in _guard_alarm_paths(
                guard_sites_payload,
                upstream_limit,
                department=guard_department,
            ):
                guard_payload = _get_upstream_json(guard_room_url, path, request)
                alarms.extend(
                    _normalize_guard_alarm(item)
                    for item in _items_from_payload(guard_payload)
                )

    for department in _security_vlm_departments_for_user(user):
        vlm_path = (
            f"/api/departments/{department}/history"
            f"?limit={upstream_limit}"
        )
        vlm_payload = _get_upstream_json(
            security_vlm_url,
            vlm_path,
            request,
        )
        if isinstance(vlm_payload, dict):
            for item in _items_from_payload(vlm_payload.get("history")):
                alarm = _normalize_security_vlm_alarm(item, department)
                if alarm:
                    alarms.append(alarm)

    scoped = _filter_alarms(alarms, user=user, event_types=event_types)
    selected = sorted(scoped, key=_alarm_sort_key, reverse=True)[:limit]
    try:
        disposition_map = disposition_store.get_many(str(alarm["id"]) for alarm in selected)
    except DispositionStoreBusy as exc:
        raise HTTPException(status_code=503, detail="disposition store busy; retry") from exc
    return [_with_disposition(alarm, disposition_map) for alarm in selected]


# 功能：创建或构建 `_build_alarm_statistics` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarms`（list[dict[str, Any]]）：`alarms` 对应的业务输入值
#   - `days`（int）：`days` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::unified_statistics` 调用本符号
#   - 内部调用：`datetime.now`、`now.replace`、`timedelta`、`_parse_alarm_datetime`、`alarm.get`、`in_range.append`、`Counter`、`defaultdict`、`str`、`ALARM_TYPE_META.get`
#          等共 31 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def _build_alarm_statistics(alarms: list[dict[str, Any]], *, days: int) -> dict[str, Any]:
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = today_start - timedelta(days=days - 1)

    in_range: list[tuple[dict[str, Any], datetime]] = []
    for alarm in alarms:
        created = _parse_alarm_datetime(alarm.get("created_at"))
        if created and created >= range_start:
            in_range.append((alarm, created))

    by_type: dict[str, dict[str, Any]] = {}
    by_subject: Counter[tuple[str, str]] = Counter()
    subject_names: dict[tuple[str, str], str] = {}
    daily_counts: dict[str, Counter[str]] = defaultdict(Counter)
    hourly_counts: dict[int, Counter[str]] = defaultdict(Counter)

    for alarm, created in in_range:
        event_type = str(alarm.get("event_type") or "unknown")
        meta = ALARM_TYPE_META.get(event_type, {"name": event_type})
        row = by_type.setdefault(
            event_type,
            {
                "event_type": event_type,
                "name": alarm.get("event_label") or meta["name"],
                "value": 0,
            },
        )
        row["value"] += 1

        subject_type = str(alarm.get("subject_type") or "unknown")
        subject_id = str(
            alarm.get("subject_id")
            or alarm.get("subject_name")
            or alarm.get("camera_no")
            or "unknown"
        )
        subject_key = (subject_type, subject_id)
        by_subject[subject_key] += 1
        subject_names[subject_key] = str(
            alarm.get("subject_name")
            or alarm.get("camera_name")
            or subject_id
        )
        daily_counts[created.strftime("%m-%d")][event_type] += 1
        hourly_counts[created.hour][event_type] += 1

    daily = []
    for offset in range(days):
        day = range_start + timedelta(days=offset)
        key = day.strftime("%m-%d")
        bucket = daily_counts.get(key, Counter())
        daily.append({"day": key, "total": sum(bucket.values()), **dict(bucket)})

    hourly = []
    for hour in range(24):
        bucket = hourly_counts.get(hour, Counter())
        hourly.append({"time": f"{hour:02d}:00", "total": sum(bucket.values()), **dict(bucket)})

    peak = max(hourly, key=lambda item: int(item.get("total") or 0), default={"time": "-"})
    return {
        "summary": {
            "total": len(in_range),
            "today": sum(1 for _alarm, created in in_range if created >= today_start),
            "avg_per_day": round(len(in_range) / days, 2),
            "active_subjects": len(by_subject),
            "peak_hour": peak.get("time") if peak.get("total") else "-",
        },
        "by_type": list(by_type.values()),
        "by_subject": [
            {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "subject_name": subject_names.get((subject_type, subject_id), subject_id),
                "value": value,
            }
            for (subject_type, subject_id), value in by_subject.most_common(8)
        ],
        "daily": daily,
        "hourly": hourly,
        "recent": alarms[:8],
    }


# 功能：实现 `_count_guard_cameras` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `config`（object）：运行配置对象
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`isinstance`、`config.get`、`sum`、`str(video.get(key) or '').strip`、`str`、`video.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _count_guard_cameras(config: object) -> int:
    if not isinstance(config, dict):
        return 0
    video = config.get("video")
    if not isinstance(video, dict):
        return 0
    return sum(
        1
        for key in ("source_cam1", "source_cam2", "source_cam3")
        if str(video.get(key) or "").strip()
    )


# 功能：实现 `_guard_site_items` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（object）：接口或事件携带的业务数据
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_count_guard_site_cameras` 调用本符号；`unified_backend/app.py` 的 `_guard_site_runtime_summary`
#         调用本符号；`unified_backend/app.py` 的 `_guard_alarm_paths` 调用本符号；`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：`isinstance`、`payload.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _guard_site_items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("items") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


# 功能：实现 `_count_guard_site_cameras` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（object）：接口或事件携带的业务数据
# 返回：tuple[int, int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_guard_site_runtime_summary` 调用本符号；`unified_backend/app.py` 的 `create_app::platform_status`
#         调用本符号
#   - 内部调用：`_guard_site_items`、`site.get`、`isinstance`、`len`、`int`、`sum`、`camera.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _count_guard_site_cameras(payload: object) -> tuple[int, int]:
    camera_count = 0
    enabled_camera_count = 0
    for site in _guard_site_items(payload):
        cameras = site.get("cameras")
        if isinstance(cameras, list):
            camera_count += len([camera for camera in cameras if isinstance(camera, dict)])
            if site.get("enabled_camera_count") is not None:
                enabled_camera_count += int(site.get("enabled_camera_count") or 0)
            else:
                enabled_camera_count += sum(1 for camera in cameras if isinstance(camera, dict) and camera.get("enabled", True))
            continue
        camera_count += int(site.get("camera_count") or 0)
        enabled_camera_count += int(site.get("enabled_camera_count") or 0)
    return camera_count, enabled_camera_count


# 功能：转换或规范化 `_format_guard_site_status_error` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `status_errors`（dict[int, str]）：`status_errors` 对应的业务输入值
# 返回：str | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_guard_site_runtime_summary` 调用本符号
#   - 内部调用：`', '.join`、`sorted`、`status_errors.items`、`len`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def _format_guard_site_status_error(status_errors: dict[int, str]) -> str | None:
    if not status_errors:
        return None
    details = ", ".join(f"{site_id}: {error}" for site_id, error in sorted(status_errors.items()))
    return f"{len(status_errors)} 个保安室运行状态获取失败: {details}"


# 功能：实现 `_guard_site_runtime_summary` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `sites_payload`（object）：`sites_payload` 对应的业务输入值
#   - `statuses`（dict[int, dict[str, Any]]）：`statuses` 对应的业务输入值
#   - `status_errors`（dict[int, str] | None）：`status_errors` 对应的业务输入值；默认值为 `None`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：`_guard_site_items`、`int`、`site.get`、`statuses.get`、`bool`、`status.get`、`running_sites.append`、`fps_values.append`、`float`、`isinstance`
#          等共 15 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _guard_site_runtime_summary(
    sites_payload: object,
    statuses: dict[int, dict[str, Any]],
    *,
    status_errors: dict[int, str] | None = None,
) -> dict[str, Any]:
    items = _guard_site_items(sites_payload)
    running_sites: list[int] = []
    online_camera_count = 0
    frame_count = 0
    fps_values: list[float] = []
    updated_at_values: list[str] = []
    pose_enabled = False

    for site in items:
        try:
            site_id = int(site.get("id"))
        except (TypeError, ValueError):
            continue
        status = statuses.get(site_id) or {}
        if not bool(status.get("running")):
            continue
        running_sites.append(site_id)
        online_camera_count += int(site.get("enabled_camera_count") or 0)
        frame_count += int(status.get("frame_count") or 0)
        if status.get("fps") is not None:
            fps_values.append(float(status.get("fps") or 0))
        if isinstance(status.get("updated_at"), str):
            updated_at_values.append(status["updated_at"])
        pose_enabled = pose_enabled or bool(status.get("pose_enabled"))

    _camera_count, enabled_camera_count = _count_guard_site_cameras(sites_payload)
    status_errors = status_errors or {}
    return {
        "running": bool(running_sites),
        "running_sites": running_sites,
        "online_camera_count": online_camera_count,
        "offline_camera_count": max(0, enabled_camera_count - online_camera_count),
        "fps": round(max(fps_values), 2) if fps_values else None,
        "frame_count": frame_count,
        "updated_at": max(updated_at_values) if updated_at_values else None,
        "pose_enabled": pose_enabled,
        "status_errors": status_errors,
        "status_error": _format_guard_site_status_error(status_errors),
    }


# 功能：实现 `_guard_alarm_paths` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `sites_payload`（object）：`sites_payload` 对应的业务输入值
#   - `limit`（int）：返回或处理的最大记录数
#   - `department`（str | None）：业务部门名称或标识；默认值为 `None`
# 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_collect_alarms` 调用本符号
#   - 内部调用：`_guard_site_items`、`int`、`site.get`、`paths.append`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _guard_alarm_paths(sites_payload: object, limit: int, department: str | None = None) -> list[str]:
    paths: list[str] = []
    for site in _guard_site_items(sites_payload):
        try:
            site_id = int(site.get("id"))
        except (TypeError, ValueError):
            continue
        path = f"/api/sites/{site_id}/alarms?limit={limit}"
        if department:
            path = f"{path}&department={department}"
        paths.append(path)
    return paths


# 功能：实现 `_camera_functions_enabled` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `camera`（dict）：摄像头配置或实体
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：`camera.get`、`isinstance`、`any`、`bool`、`functions.values`、`len`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _camera_functions_enabled(camera: dict) -> bool:
    functions = camera.get("functions")
    if isinstance(functions, dict):
        return any(bool(value) for value in functions.values())
    if isinstance(functions, list):
        return len(functions) > 0
    return False


# 功能：实现 `_camera_feature_enabled` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `camera`（dict）：摄像头配置或实体
#   - `feature`（str）：`feature` 对应的业务输入值
# 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_aivision_feature_status` 调用本符号
#   - 内部调用：`camera.get`、`isinstance`、`bool`、`functions.get`、`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _camera_feature_enabled(camera: dict, feature: str) -> bool:
    functions = camera.get("functions")
    if isinstance(functions, dict):
        return bool(functions.get(feature))
    if isinstance(functions, list):
        return feature in {str(item) for item in functions}
    return False


# 功能：实现 `_aivision_feature_status` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `cameras`（list[dict]）：`cameras` 对应的业务输入值
#   - `running_cameras`（list）：`running_cameras` 对应的业务输入值
# 返回：dict[str, dict[str, int]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：`str`、`_camera_feature_enabled`、`camera.get`、`sum`、`len`、`max`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _aivision_feature_status(cameras: list[dict], running_cameras: list) -> dict[str, dict[str, int]]:
    running_camera_names = {str(item) for item in running_cameras}
    feature_names = ("blocks", "detect_door", "detect_face", "detect_human", "detect_phone")
    status: dict[str, dict[str, int]] = {}
    for feature in feature_names:
        configured_cameras = [
            camera
            for camera in cameras
            if _camera_feature_enabled(camera, feature)
        ]
        enabled_cameras = [
            camera
            for camera in configured_cameras
            if camera.get("enabled")
        ]
        online_count = sum(
            1
            for camera in enabled_cameras
            if str(camera.get("shm_name") or camera.get("camera_no") or camera.get("name") or "") in running_camera_names
        )
        status[feature] = {
            "camera_count": len(configured_cameras),
            "enabled_camera_count": len(enabled_cameras),
            "online_camera_count": online_count,
            "offline_camera_count": max(0, len(configured_cameras) - online_count),
        }
    return status


# 功能：实现 `_service_status` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `url`（str）：目标接口、媒体流或页面地址
#   - `online`（bool）：`online` 对应的业务输入值
#   - `latency_ms`（float | None）：`latency_ms` 对应的时间间隔或时长
#   - `error`（str | None）：待报告、转换或判断的异常对象
#   - `extra`（dict）：`extra` 对应的业务输入值
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::platform_status` 调用本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _service_status(name: str, url: str, online: bool, latency_ms: float | None, error: str | None, extra: dict) -> dict:
    return {
        "name": name,
        "url": url,
        "online": online,
        "latency_ms": latency_ms,
        "error": error,
        **extra,
    }

# 读取请求体以及发送上游HTTP，都属于I/O操作，因此使用异步函数来处理请求转发，避免阻塞事件循环，提高并发性能。
# 功能：实现 `_proxy` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `request`（Request）：当前 HTTP 请求及上下文
#   - `base_url`（str）：`base_url` 对应的业务输入值
#   - `upstream_path`（str）：`upstream_path` 对应的业务输入值
# 返回：Response；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::proxy_aivision_root_api` 调用本符号；另有 3 处静态调用
#   - 内部调用：`urljoin`、`upstream_path.lstrip`、`request.body`、`request.app.state.proxy_client.send`、`_request_headers`、`HTTPException`、`StreamingResponse`、`stream_response_bytes`、`filtered_response_headers`、`BackgroundTask`。
# 副作用/注意事项：可能发起网络请求或发送外部消息；校验或执行失败时会主动抛出异常。
async def _proxy(request: Request, base_url: str, upstream_path: str) -> Response:
    query = f"?{request.url.query}" if request.url.query else ""
    url = urljoin(f"{base_url}/", upstream_path.lstrip("/")) + query
    body = await request.body()
    try:
        upstream = await request.app.state.proxy_client.send(
            method=request.method,      #前端发送的method
            url=url,
            body=body,                  
            headers=_request_headers(request),
        )
    except ProxyRequestError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc

    return StreamingResponse(
        stream_response_bytes(upstream),
        status_code=upstream.status_code,
        headers=filtered_response_headers(upstream.headers),
        background=BackgroundTask(upstream.aclose),
    )


# 功能：创建或构建 `create_app` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：FastAPI；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_env_url`、`_visual_service_url`、`os.getenv`、`str`、`AlarmDispositionStore`、`Path`、`AccessAuditStore`、`FastAPI`、`app.add_middleware`、`_cors_origins`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def create_app() -> FastAPI:
    aivision_url = _env_url("UNIFIED_AIVISION_URL", "http://127.0.0.1:7862")
    guard_room_url = _visual_service_url(aivision_url, "guard-room")
    security_vlm_url = _visual_service_url(aivision_url, "security-vlm")
    data_dir = os.getenv("UNIFIED_BACKEND_DATA_DIR", str(_REPO_ROOT / "unified_backend" / "data"))
    disposition_store = AlarmDispositionStore(data_dir)
    access_audit_database = os.getenv(
        "UNIFIED_ACCESS_AUDIT_DB",
        str(Path(data_dir) / "access_audit.db"),
    )
    access_audit_store = AccessAuditStore(access_audit_database)

    # 功能：实现 `lifespan` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `app`（FastAPI）：`app` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`get_user_store().initialize`、`get_user_store`、`access_audit_store.initialize`、`AsyncProxyClient`、`ProxySettings.from_env`、`proxy_client.close`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        get_user_store().initialize()
        access_audit_store.initialize()
        proxy_client = AsyncProxyClient(ProxySettings.from_env())
        app.state.proxy_client = proxy_client
        try:
            disposition_queries = DispositionQueries(aivision_url)
            app.state.disposition_queries = disposition_queries
            try:
                yield
            finally:
                await disposition_queries.close()
        finally:
            await proxy_client.close()

    app = FastAPI(
        title="Fuda Unified Backend",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.access_audit_store = access_audit_store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 功能：实现 `auth_middleware` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `call_next`（未显式标注）：`call_next` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`path.startswith`、`call_next`、`get_current_user_from_request`、`JSONResponse`、`str`、`_can_access_security_vlm`、`app.middleware`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        public_paths = {"/", "/api/health", "/api/auth/login", "/api/auth/logout"}
        if request.method == "OPTIONS" or path in public_paths or path.startswith("/api/public/"):
            return await call_next(request)
        protected = path.startswith("/api/") or path.startswith("/security-vlm") or path.startswith("/aivision")
        if protected:
            try:
                request.state.user = get_current_user_from_request(request)
            except AuthError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
            if (
                path.startswith("/security-vlm")
                and not _can_access_security_vlm(
                    request.state.user,
                    request.method,
                    path,
                )
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "仅管理员可以修改安检模块配置"
                            "或读取摄像头连接信息"
                        )
                    },
                )
        return await call_next(request)

    # 功能：实现 `root` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/")
    def root():
        return {
            "name": "fuda-unified-backend",
            "ok": True,
            "guard_room": guard_room_url,
            "aivision": aivision_url,
            "security_vlm": security_vlm_url,
        }

    # 功能：实现 `health` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/health')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`int`、`os.getenv`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "unified_backend", "port": int(os.getenv("UNIFIED_BACKEND_PORT", "5000"))}

    # 功能：实现 `platform_status` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/platform/status')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`_now`、`_get_json_concurrently`、`_count_guard_site_cameras`、`_guard_site_items`、`int`、`site.get`、`site_ids.append`、`str`、`isinstance`、`_guard_site_runtime_summary`
    #          等共 31 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/platform/status")
    def platform_status(request: Request):
        now = _now()

        upstream = _get_json_concurrently(
            {
                "guard_health": (guard_room_url, "/api/health", request),
                "guard_status": (guard_room_url, "/api/status", request),
                "guard_sites": (guard_room_url, "/api/sites", request),
                "ai_health": (aivision_url, "/api/runtime/health", None),
                "ai_status": (aivision_url, "/api/runtime/status", request),
                "ai_cameras": (aivision_url, "/api/cameras", request),
                "vlm_health": (security_vlm_url, "/health", request),
            }
        )
        guard_health_ok, _guard_health, guard_latency, guard_health_error = upstream["guard_health"]
        _guard_status_ok, guard_status, _guard_status_latency, guard_status_error = upstream["guard_status"]
        guard_sites_ok, guard_sites, _guard_sites_latency, _guard_sites_error = upstream["guard_sites"]
        guard_camera_count, guard_enabled_camera_count = _count_guard_site_cameras(guard_sites) if guard_sites_ok else (0, 0)
        guard_site_statuses: dict[int, dict[str, Any]] = {}
        guard_site_status_errors: dict[int, str] = {}
        if guard_sites_ok:
            site_ids: list[int] = []
            for site in _guard_site_items(guard_sites):
                try:
                    site_id = int(site.get("id"))
                except (TypeError, ValueError):
                    continue
                site_ids.append(site_id)
            site_results = _get_json_concurrently({
                str(site_id): (
                    guard_room_url,
                    f"/api/sites/{site_id}/status",
                    request,
                )
                for site_id in site_ids
            })
            for site_id in site_ids:
                _ok, site_status, _latency, _error = site_results[str(site_id)]
                if _ok and isinstance(site_status, dict):
                    guard_site_statuses[site_id] = site_status
                else:
                    guard_site_status_errors[site_id] = _error or "invalid response"
        guard_runtime = (
            _guard_site_runtime_summary(guard_sites, guard_site_statuses, status_errors=guard_site_status_errors)
            if guard_sites_ok
            else {}
        )
        guard_last_frame_ts = _parse_iso_ts(guard_runtime.get("updated_at"))
        guard_running = bool(guard_runtime.get("running")) if guard_sites_ok else (bool(guard_status.get("running")) if isinstance(guard_status, dict) else False)
        guard_service_error = (
            guard_health_error
            if not guard_health_ok
            else (
                guard_status_error
                if guard_status_error and guard_status_error != "401 Unauthorized"
                else (_guard_sites_error or guard_runtime.get("status_error"))
            )
        )

        ai_health_ok, ai_health, ai_latency, ai_health_error = upstream["ai_health"]
        _ai_status_ok, ai_status, _ai_status_latency, ai_status_error = upstream["ai_status"]
        _ai_cam_ok, ai_cameras, _ai_cam_latency, _ai_cam_error = upstream["ai_cameras"]
        if not isinstance(ai_status, dict) and isinstance(ai_health, dict):
            ai_status = ai_health
        ai_running_cameras = ai_status.get("running_cameras", []) if isinstance(ai_status, dict) else []
        ai_running_models = ai_status.get("running_models", []) if isinstance(ai_status, dict) else []
        ai_running_consumers = ai_status.get("running_consumers", []) if isinstance(ai_status, dict) else []
        ai_camera_items = ai_cameras if isinstance(ai_cameras, list) else []
        ai_enabled_camera_count = sum(1 for camera in ai_camera_items if camera.get("enabled") and _camera_functions_enabled(camera))
        ai_feature_status = _aivision_feature_status(ai_camera_items, ai_running_cameras)

        vlm_ok, vlm_health, vlm_latency, vlm_error = upstream["vlm_health"]
        vlm_running = bool(vlm_health.get("running")) if isinstance(vlm_health, dict) else False
        vlm_capture = vlm_health.get("capture", {}) if isinstance(vlm_health, dict) else {}
        vlm_detector = vlm_health.get("detector", {}) if isinstance(vlm_health, dict) else {}
        vlm_session = vlm_health.get("session", {}) if isinstance(vlm_health, dict) else {}
        vlm_worker = vlm_health.get("vlm", {}) if isinstance(vlm_health, dict) else {}
        vlm_stats = vlm_health.get("stats", {}) if isinstance(vlm_health, dict) else {}
        vlm_frame_ts = float(vlm_capture.get("ts", 0) or 0) if isinstance(vlm_capture, dict) else 0

        services = {
            "guard_room": _service_status(
                "Guard Room",
                guard_room_url,
                guard_health_ok,
                guard_latency,
                guard_service_error,
                {
                    "running": guard_running,
                    "camera_count": guard_camera_count,
                    "enabled_camera_count": guard_enabled_camera_count,
                    "online_camera_count": int(guard_runtime.get("online_camera_count") or 0) if guard_sites_ok else (guard_enabled_camera_count if guard_running else 0),
                    "offline_camera_count": int(guard_runtime.get("offline_camera_count") or 0) if guard_sites_ok else (0 if guard_running else guard_enabled_camera_count),
                    "fps": guard_runtime.get("fps") if guard_sites_ok else (guard_status.get("fps") if isinstance(guard_status, dict) else None),
                    "frame_count": guard_runtime.get("frame_count") if guard_sites_ok else (guard_status.get("frame_count") if isinstance(guard_status, dict) else None),
                    "running_sites": guard_runtime.get("running_sites", []),
                    "last_frame_age_sec": round(now - guard_last_frame_ts, 1) if guard_last_frame_ts else None,
                    "model_status": {
                        "pose_enabled": bool(guard_runtime.get("pose_enabled")) if guard_sites_ok else (bool(guard_status.get("pose_enabled")) if isinstance(guard_status, dict) else False),
                        "loaded": guard_health_ok,
                    },
                },
            ),
            "aivision": _service_status(
                "AiVision",
                aivision_url,
                ai_health_ok,
                ai_latency,
                ai_health_error if not ai_health_ok else (ai_status_error if ai_status_error and ai_status_error != "401 Unauthorized" else None),
                {
                    "running": bool(ai_status.get("started")) if isinstance(ai_status, dict) else False,
                    "camera_count": len(ai_camera_items),
                    "enabled_camera_count": ai_enabled_camera_count,
                    "online_camera_count": len(ai_running_cameras),
                    "offline_camera_count": max(0, ai_enabled_camera_count - len(ai_running_cameras)),
                    "running_cameras": ai_running_cameras,
                    "running_models": ai_running_models,
                    "running_consumers": ai_running_consumers,
                    "feature_status": ai_feature_status,
                    "model_status": {
                        "loaded": len(ai_running_models) > 0,
                        "running_count": len(ai_running_models),
                    },
                },
            ),
            "security_vlm": _service_status(
                "Security VLM",
                security_vlm_url,
                vlm_ok,
                vlm_latency,
                vlm_error,
                {
                    "running": vlm_running,
                    "camera_count": 1,
                    "online_camera_count": 1 if vlm_running and isinstance(vlm_capture, dict) and vlm_capture.get("ok") else 0,
                    "offline_camera_count": 0 if vlm_running and isinstance(vlm_capture, dict) and vlm_capture.get("ok") else 1,
                    "last_frame_age_sec": round(now - vlm_frame_ts, 1) if vlm_frame_ts else None,
                    "worker_status": {
                        "capture": vlm_capture,
                        "detector": vlm_detector,
                        "session": vlm_session,
                        "vlm": vlm_worker,
                    },
                    "model_status": {
                        "loaded": bool(isinstance(vlm_detector, dict) and vlm_detector.get("ok")),
                        "vlm_ok": bool(isinstance(vlm_worker, dict) and vlm_worker.get("ok")),
                    },
                    "stats": vlm_stats,
                },
            ),
        }

        camera_total = sum(int(service.get("camera_count") or 0) for service in services.values())
        camera_online = sum(int(service.get("online_camera_count") or 0) for service in services.values())
        online_services = sum(1 for service in services.values() if service.get("online"))
        running_services = sum(1 for service in services.values() if service.get("running"))
        all_services_online = online_services == len(services)

        if all_services_online and camera_online == camera_total and running_services == len(services):
            level = "healthy"
        elif online_services > 0:
            level = "degraded"
        else:
            level = "down"

        return {
            "ok": all_services_online,
            "level": level,
            "generated_at": now,
            "summary": {
                "service_total": len(services),
                "service_online": online_services,
                "service_running": running_services,
                "camera_total": camera_total,
                "camera_online": camera_online,
                "camera_offline": max(0, camera_total - camera_online),
                "model_loaded": {
                    "guard_room": services["guard_room"]["model_status"]["loaded"],
                    "aivision": services["aivision"]["model_status"]["loaded"],
                    "security_vlm": services["security_vlm"]["model_status"]["loaded"],
                },
            },
            "services": services,
        }

    # 功能：实现 `login` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `payload`（LoginRequest）：接口或事件携带的业务数据
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `response`（Response）：待读取或更新的 HTTP 响应
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/auth/login')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`verify_login`、`HTTPException`、`create_token`、`set_auth_cookie`、`access_audit_store.record_visit`、`logger.exception`、`user.get`、`add_access_audit_capability`、`app.post`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response):
        user = verify_login(payload.employee_id, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid employee_id or password")
        token = create_token(user)
        set_auth_cookie(response, token, request)
        try:
            access_audit_store.record_visit(user)
        except (OSError, sqlite3.Error, ValueError):
            logger.exception("记录平台访问失败 employee_id=%s", user.get("employee_id"))
        return {"success": True, "user": add_access_audit_capability(user)}

    # 功能：实现 `me` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/auth/me')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`access_audit_store.record_visit`、`logger.exception`、`user.get`、`add_access_audit_capability`、`app.get`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    @app.get("/api/auth/me")
    def me(user: dict = Depends(get_current_user)):
        try:
            access_audit_store.record_visit(user)
        except (OSError, sqlite3.Error, ValueError):
            logger.exception("记录平台访问失败 employee_id=%s", user.get("employee_id"))
        return {"success": True, "user": add_access_audit_capability(user)}

    # 功能：实现 `logout` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `response`（Response）：待读取或更新的 HTTP 响应
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/auth/logout')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`clear_auth_cookie`、`app.post`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        clear_auth_cookie(response, request)
        return {"success": True}

    # 功能：实现 `change_password` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `payload`（ChangePasswordRequest）：接口或事件携带的业务数据
    #   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/auth/password')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`change_own_password`、`user.get`、`HTTPException`、`str`、`add_access_audit_capability`、`app.post`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @app.post("/api/auth/password")
    def change_password(payload: ChangePasswordRequest, user: dict = Depends(get_current_user)):
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

    # 功能：实现 `access_audit` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `Query(default=DEFAULT_ACCESS_AUDIT_LIMIT, ge=1, le=MAX_ACCESS_AUDIT_LIMIT)`
    #   - `owner`（dict）：`owner` 对应的业务输入值；默认值为 `Depends(require_access_audit_owner)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/admin/access-audit')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Query`、`Depends`、`access_audit_store.list_recent`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/admin/access-audit")
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

    # 功能：读取或查询 `admin_list_users` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `admin`（dict）：`admin` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/admin/users')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`list_auth_users`、`_raise_user_management_http_error`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/admin/users")
    def admin_list_users(admin: dict = Depends(require_admin)):
        del admin
        try:
            return {"items": list_auth_users()}
        except UserStoreError as exc:
            _raise_user_management_http_error(exc)

    # 功能：创建或构建 `admin_create_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `payload`（AdminUserCreateRequest）：接口或事件携带的业务数据
    #   - `admin`（dict）：`admin` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/admin/users')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`create_auth_user`、`_raise_user_management_http_error`、`app.post`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.post("/api/admin/users")
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

    # 功能：更新或保存 `admin_update_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    #   - `payload`（AdminUserUpdateRequest）：接口或事件携带的业务数据
    #   - `admin`（dict）：`admin` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.patch('/api/admin/users/{employee_id}')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`update_auth_user`、`str`、`admin.get`、`_raise_user_management_http_error`、`app.patch`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.patch("/api/admin/users/{employee_id}")
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

    # 功能：实现 `admin_reset_user_password` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    #   - `payload`（AdminUserPasswordResetRequest）：接口或事件携带的业务数据
    #   - `admin`（dict）：`admin` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.post('/api/admin/users/{employee_id}/reset-password')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`reset_auth_user_password`、`_raise_user_management_http_error`、`app.post`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.post("/api/admin/users/{employee_id}/reset-password")
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

    # 功能：删除或清理 `admin_delete_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `employee_id`（str）：`employee_id` 对应业务对象的唯一标识
    #   - `admin`（dict）：`admin` 对应的业务输入值；默认值为 `Depends(require_admin)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.delete('/api/admin/users/{employee_id}')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Depends`、`delete_auth_user`、`str`、`admin.get`、`_raise_user_management_http_error`、`app.delete`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.delete("/api/admin/users/{employee_id}")
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

    @app.get("/api/alarm-dispositions", response_model=DispositionPage)
    async def get_alarm_dispositions(
        request: Request,
        limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(None, min_length=1, max_length=128),
        user: dict = Depends(get_current_user),
    ):
        return await app.state.disposition_queries.page(
            disposition_store, request, user, limit=limit, cursor=cursor,
        )

    @app.get("/api/alarm-dispositions/{alarm_id}")
    async def get_alarm_disposition(alarm_id: str, request: Request, user: dict = Depends(get_current_user)):
        await app.state.disposition_queries.require_access(alarm_id, request, user)
        try:
            item = disposition_store.get_many([alarm_id]).get(alarm_id)
        except DispositionStoreBusy as exc:
            raise HTTPException(status_code=503, detail="disposition store busy; retry") from exc
        if item is None:
            raise HTTPException(status_code=404, detail="disposition not found")
        return {"item": item}

    @app.post("/api/alarm-dispositions")
    async def update_alarm_disposition(payload: AlarmDispositionUpdateRequest, request: Request, user: dict = Depends(get_current_user)):
        await app.state.disposition_queries.require_access(payload.alarm_id.strip(), request, user)
        try:
            item = await run_in_threadpool(
                disposition_store.update,
                alarm_id=payload.alarm_id, status=payload.status, note=payload.note, user=user,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "item": item}

    # 功能：实现 `unified_alarms` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `limit`（int）：返回或处理的最大记录数；默认值为 `Query(200, ge=1, le=1000)`
    #   - `event_types`（str | None）：`event_types` 对应的业务输入值；默认值为 `Query(None)`
    #   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/alarms')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Query`、`Depends`、`_collect_alarms`、`_parse_event_types`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/alarms")
    def unified_alarms(
        request: Request,
        limit: int = Query(200, ge=1, le=1000),
        event_types: str | None = Query(None),
        user: dict = Depends(get_current_user),
    ):
        return {
            "items": _collect_alarms(
                request=request,
                user=user,
                guard_room_url=guard_room_url,
                aivision_url=aivision_url,
                security_vlm_url=security_vlm_url,
                disposition_store=disposition_store,
                limit=limit,
                event_types=_parse_event_types(event_types),
            )
        }

    # 功能：实现 `unified_statistics` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `request`（Request）：当前 HTTP 请求及上下文
    #   - `days`（int）：`days` 对应的业务输入值；默认值为 `Query(7, ge=1, le=90)`
    #   - `event_types`（str | None）：`event_types` 对应的业务输入值；默认值为 `Query(None)`
    #   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：由 FastAPI 按 `app.get('/api/statistics')` 注册，并在请求到达时调用以生成接口响应
    #   - 内部调用：`Query`、`Depends`、`_collect_alarms`、`_parse_event_types`、`_build_alarm_statistics`、`app.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.get("/api/statistics")
    def unified_statistics(
        request: Request,
        days: int = Query(7, ge=1, le=90),
        event_types: str | None = Query(None),
        user: dict = Depends(get_current_user),
    ):
        alarms = _collect_alarms(
            request=request,
            user=user,
            guard_room_url=guard_room_url,
            aivision_url=aivision_url,
            security_vlm_url=security_vlm_url,
            disposition_store=disposition_store,
            limit=1000,
            event_types=_parse_event_types(event_types),
        )
        return _build_alarm_statistics(alarms, days=days)

    # 后面不管跟什么路径，我全接住（统一后端没有做处理手机的配置，只做(收到请求->原样转发->AiVision）
    # 功能：实现 `proxy_aivision_root_api` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `path`（str）：目标路径
    #   - `request`（Request）：当前 HTTP 请求及上下文
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`_proxy`、`app.api_route`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_aivision_root_api(path: str, request: Request):
        if _is_guard_room_api_path(path):
            return await _proxy(request, guard_room_url, f"/api/{path}")
        return await _proxy(request, aivision_url, f"/api/{path}")

    # 功能：实现 `proxy_aivision_root` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `path`（str）：目标路径
    #   - `request`（Request）：当前 HTTP 请求及上下文
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`_proxy`、`app.api_route`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.api_route("/aivision/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_aivision_root(path: str, request: Request):
        return await _proxy(request, aivision_url, f"/{path}")

    # 功能：实现 `proxy_security_vlm` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `path`（str）：目标路径
    #   - `request`（Request）：当前 HTTP 请求及上下文
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`_proxy`、`app.api_route`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @app.api_route("/security-vlm/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_security_vlm(path: str, request: Request):
        return await _proxy(request, security_vlm_url, f"/{path}")

    return app
