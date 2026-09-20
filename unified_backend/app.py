# 文件说明：定义应用装配的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""统一平台后端入口。

统一后端只做平台级能力和请求转发，不接管各算法子系统的运行逻辑：
- 本地处理平台总览、报警聚合和报警处置状态；
- 转发 AiVision 原生检测与管理接口。
"""
from __future__ import annotations

import logging
import os
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

from auth.auth import AuthError, get_current_user, get_current_user_from_request
from auth.alarm_permissions import allowed_alarm_event_types
from AiVision.departments.department_registry import DEPARTMENT_SPECS, require_department
from unified_backend.overview import OverviewStatus, build_overview
from unified_backend.alarm_dispositions import AlarmDispositionStore, DispositionStoreBusy
from unified_backend.disposition_queries import (
    DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, DispositionPage, DispositionQueries,
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
_DEFAULT_OVERVIEW_MAX_WORKERS = 16


# 功能：实现 `_overview_max_workers` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`os.getenv`、`str`、`max`、`int`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _overview_max_workers() -> int:
    raw_value = os.getenv(
        "UNIFIED_OVERVIEW_MAX_WORKERS",
        str(_DEFAULT_OVERVIEW_MAX_WORKERS),
    )
    try:
        return max(1, int(raw_value))
    except ValueError:
        return _DEFAULT_OVERVIEW_MAX_WORKERS


_OVERVIEW_EXECUTOR = ThreadPoolExecutor(
    max_workers=_overview_max_workers(),
    thread_name_prefix="overview",
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


def _departments_for_user(user: dict[str, Any]) -> list[str]:
    """只读取账号明确授权的正式事业部编码。"""
    raw_departments = user.get("departments")
    candidates = raw_departments if isinstance(raw_departments, list) else []
    return list(dict.fromkeys(
        department for department in candidates
        if isinstance(department, str) and department in DEPARTMENT_SPECS
    ))


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


def _get_json(
    base_url: str,
    path: str,
    *,
    timeout: float = 2.0,
    request: Request | None = None,
) -> tuple[bool, dict | list | None, float | None, str | None]:
    started_at = time.perf_counter()
    try:
        payload = _get_upstream_json(base_url, path, request, timeout=timeout)
    except HTTPException as exc:
        return False, None, None, str(exc.detail)
    return True, payload, round((time.perf_counter() - started_at) * 1000, 1), None


# 功能：在平台状态专属的有界线程池中并发执行多个同步上游探测；输入与输出详见下方说明
# 参数：
#   - `calls`（dict[str, tuple[str, str, Request | None]]）：`calls` 对应的业务输入值
# 返回：dict[str, tuple[bool, dict | list | None, float | None, str | None]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `create_app::overview` 调用本符号
#   - 内部调用：`list`、`_OVERVIEW_EXECUTOR.submit`、`future.result`、`dict`、`zip`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _get_json_concurrently(
    calls: dict[str, tuple[str, str, Request | None]],
) -> dict[str, tuple[bool, dict | list | None, float | None, str | None]]:
    """在平台状态专属的有界线程池中并发执行多个同步上游探测。"""
    keys = list(calls)
    futures = [
        _OVERVIEW_EXECUTOR.submit(
            _get_json,
            calls[key][0],
            calls[key][1],
            request=calls[key][2],
        )
        for key in keys
    ]
    results = [future.result() for future in futures]
    return dict(zip(keys, results, strict=True))


def _get_upstream_json(
    base_url: str, path: str, request: Request | None, *, timeout: float = 3.0,
) -> dict | list:
    try:
        with requests.get(
            urljoin(f"{base_url}/", path.lstrip("/")),
            headers=_request_headers(request) if request is not None else {},
            timeout=timeout,
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                logger.error("AiVision HTTP 请求失败 path=%s status=%s", path, response.status_code)
                status = response.status_code if response.status_code in (401, 403) else 502
                raise HTTPException(status, f"AiVision HTTP {response.status_code}")
            payload = response.json()
    except requests.Timeout as exc:
        logger.warning("AiVision 请求超时 path=%s", path)
        raise HTTPException(504, "AiVision request timed out") from exc
    except requests.exceptions.JSONDecodeError as exc:
        logger.error("AiVision JSON 解析失败 path=%s", path)
        raise HTTPException(502, "invalid AiVision JSON response") from exc
    except requests.RequestException as exc:
        logger.error("AiVision 请求失败 path=%s error=%s", path, type(exc).__name__)
        raise HTTPException(502, "AiVision upstream unavailable") from exc
    if not isinstance(payload, (dict, list)):
        raise HTTPException(502, "invalid AiVision response structure")
    return payload


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


def _items_from_payload(payload: object) -> list[dict[str, Any]]:
    required = {"id", "event_type", "event_label", "subject_type", "subject_id", "subject_name", "created_at", "video_status"}
    if (not isinstance(payload, dict) or not isinstance(payload.get("items"), list)
            or any(not isinstance(row, dict) or not required.issubset(row) for row in payload["items"])):
        logger.error("AiVision 报警列表字段不符合当前接口协议")
        raise HTTPException(502, "invalid AiVision alarm list response")
    return payload["items"]


def _normalize_aivision_alarm(alarm: dict[str, Any]) -> dict[str, Any]:
    """保留 AiVision 报警字段，只添加平台记录标识与视频访问地址。"""
    source_id = alarm["id"]
    return {
        **alarm,
        "id": f"aivision:{source_id}",
        "source": "aivision",
        "source_id": source_id,
        "video_url": f"/api/alarms/{source_id}/video" if alarm["video_status"] == "ready" else None,
    }


# 功能：实现 `_allowed_event_types_for_user` 对应的应用装配逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict[str, Any]）：当前用户或待处理用户对象
# 返回：set[str] | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/app.py` 的 `_filter_alarms` 调用本符号
#   - 内部调用：`str(user.get('role') or '').strip().lower`、`str(user.get('role') or
#          '').strip`、`str`、`user.get`、`set`、`_departments_for_user`、`DEPARTMENT_SPECS`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _allowed_event_types_for_user(user: dict[str, Any]) -> set[str] | None:
    return allowed_alarm_event_types(user, _departments_for_user(user))


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
    if role == "viewer":
        departments = departments.intersection(DEPARTMENT_SPECS)
        alarms = [
            alarm
            for alarm in alarms
            if alarm.get("department") in departments
        ]
    if event_types is not None:
        alarms = [
            alarm
            for alarm in alarms
            if alarm.get("event_type") in event_types
            or alarm.get("feature_name") in event_types
        ]
    return alarms


def _with_disposition(alarm: dict[str, Any], dispositions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    disposition = dispositions.get(alarm["id"])
    return {
        **alarm,
        "disposition_status": disposition["status"] if disposition else "pending",
        "disposition_note": disposition["note"] if disposition else "",
        "disposition_updated_at": disposition["updated_at"] if disposition else None,
        "disposition_updated_by": disposition["updated_by"] if disposition else None,
    }


def _collect_alarms(
    *,
    request: Request,
    user: dict[str, Any],
    aivision_url: str,
    disposition_store: AlarmDispositionStore,
    limit: int,
    event_types: set[str] | None = None,
    department: str | None = None,
) -> list[dict[str, Any]]:
    if department is not None:
        try:
            department = require_department(department)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if user.get("role") != "admin" and department not in _departments_for_user(user):
            raise HTTPException(status_code=403, detail="department permission required")
    upstream_limit = max(limit, 100)
    ai_path = f"/api/alarms?limit={upstream_limit}"
    if department is not None:
        ai_path += f"&department={department}"
    ai_payload = _get_upstream_json(aivision_url, ai_path, request)
    alarms = [_normalize_aivision_alarm(item) for item in _items_from_payload(ai_payload)]

    scoped = _filter_alarms(alarms, user=user, event_types=event_types)
    if department is not None:
        scoped = [alarm for alarm in scoped if alarm.get("department") == department]
    selected = sorted(scoped, key=_alarm_sort_key, reverse=True)[:limit]
    try:
        disposition_map = disposition_store.get_many(str(alarm["id"]) for alarm in selected)
    except DispositionStoreBusy as exc:
        raise HTTPException(status_code=503, detail="disposition store busy; retry") from exc
    return [_with_disposition(alarm, disposition_map) for alarm in selected]


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
        event_type = alarm["event_type"]
        row = by_type.setdefault(
            event_type,
            {
                "event_type": event_type,
                "name": alarm["event_label"],
                "value": 0,
            },
        )
        row["value"] += 1

        subject_type = alarm["subject_type"]
        subject_id = alarm["subject_id"] or "unknown"
        subject_key = (subject_type, subject_id)
        by_subject[subject_key] += 1
        subject_names[subject_key] = alarm["subject_name"] or subject_id
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

def create_app() -> FastAPI:
    aivision_url = _env_url("UNIFIED_AIVISION_URL", "http://127.0.0.1:7862")
    data_dir = os.getenv("UNIFIED_BACKEND_DATA_DIR", str(_REPO_ROOT / "unified_backend" / "data"))
    disposition_store = AlarmDispositionStore(data_dir)
    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        public_paths = {"/", "/api/health", "/api/auth/login", "/api/auth/logout"}
        if request.method == "OPTIONS" or path in public_paths or path.startswith("/api/public/"):
            return await call_next(request)
        protected = path.startswith("/api/")
        if protected:
            try:
                request.state.user = await run_in_threadpool(get_current_user_from_request, request)
            except AuthError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
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
            "aivision": aivision_url,
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

    @app.get("/api/overview", response_model=OverviewStatus)
    def overview(request: Request):
        user = request.state.user
        departments = list(DEPARTMENT_SPECS) if user.get("role") == "admin" else _departments_for_user(user)
        return build_overview(request, departments, aivision_url,
                              _get_json_concurrently)

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
        department: str | None = None,
    ):
        return {
            "items": _collect_alarms(
                request=request,
                user=user,
                aivision_url=aivision_url,
                disposition_store=disposition_store,
                limit=limit,
                event_types=_parse_event_types(event_types),
                department=department,
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
            aivision_url=aivision_url,
            disposition_store=disposition_store,
            limit=1000,
            event_types=_parse_event_types(event_types),
        )
        return _build_alarm_statistics(alarms, days=days)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_aivision_root_api(path: str, request: Request):
        # 仅发布正式资源，内部集成入口和已移除的路径不对浏览器开放。
        if path.split("/", 1)[0] not in {
            "auth", "admin", "departments", "cameras", "features", "models", "face-recognition",
            "logistics-channels", "guard-behavior", "security-inspection", "alarms", "horns", "runtime", "exception-alert", "public",
        }:
            raise HTTPException(status_code=404, detail="Not Found")
        return await _proxy(request, aivision_url, f"/api/{path}")

    return app
