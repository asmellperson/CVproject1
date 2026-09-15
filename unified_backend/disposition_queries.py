"""有界处置分页与批量授权，不使用平台状态线程池。"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import secrets
import time
from typing import Any, Literal

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel

from unified_backend.alarm_dispositions import (
    AlarmDispositionStore, DispositionSnapshotChanged, DispositionStoreBusy,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
BATCH_SIZE = 100
MAX_BATCHES = 5
MAX_CONCURRENT_QUERIES = 4
BATCH_TIMEOUT_SECONDS = 2.0
QUERY_TIMEOUT_SECONDS = 6.0
MAX_RESPONSE_BYTES = 8192
CURSOR_TTL_SECONDS = 900
MAX_CURSORS = 2048
MAX_ALARM_ID = 2**64 - 1  # AiAlarmEvent.id: MySQL BIGINT UNSIGNED。


class DispositionPage(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None
    stop_reason: Literal["page_full", "scan_limit", "end"]


@dataclass(frozen=True)
class _Cursor:
    owner: tuple
    revision: str
    offset: int
    expires: float


def _owner(user: dict) -> tuple:
    return (user.get("employee_id"), user.get("role"), user.get("auth_version"),
            tuple(sorted(str(value) for value in user.get("departments", []))))


def _source_id(alarm_id: str) -> int | None:
    value = alarm_id.removeprefix("aivision:")
    if not value.isascii() or not value.isdecimal() or len(value) > 20:
        return None
    number = int(value)
    return number if 0 < number <= MAX_ALARM_ID else None


class DispositionQueries:
    def __init__(self, aivision_url: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._url = f"{aivision_url.rstrip('/')}/api/alarms/access-check"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(BATCH_TIMEOUT_SECONDS, connect=0.5, pool=0.1),
            limits=httpx.Limits(max_connections=MAX_CONCURRENT_QUERIES,
                               max_keepalive_connections=MAX_CONCURRENT_QUERIES),
            follow_redirects=False,
            transport=transport,
        )
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)
        self._cursors: OrderedDict[str, _Cursor] = OrderedDict()
        self._closed = False

    async def close(self):
        self._closed = True
        self._cursors.clear()
        await self._client.aclose()

    @asynccontextmanager
    async def _admitted(self):
        # 同一事件循环内检查并获取；容量不足立即拒绝，不建立无界等待队列。
        if self._closed or self._slots.locked():
            raise HTTPException(503, "disposition authorization busy; retry", headers={"Retry-After": "1"})
        await self._slots.acquire()
        try:
            yield
        finally:
            self._slots.release()

    def _resume(self, token: str | None, user: dict) -> tuple[int, str | None]:
        if token is None:
            return 0, None
        cursor = self._cursors.get(token)
        if cursor is None or cursor.expires <= time.monotonic():
            self._cursors.pop(token, None)
            raise HTTPException(410, "cursor expired or unavailable; restart pagination")
        if cursor.owner != _owner(user):
            raise HTTPException(409, "cursor user or permissions changed; restart pagination")
        return cursor.offset, cursor.revision

    def _continuation(self, user: dict, revision: str, offset: int) -> str:
        token = secrets.token_urlsafe(32)
        self._cursors[token] = _Cursor(_owner(user), revision, offset, time.monotonic() + CURSOR_TTL_SECONDS)
        while len(self._cursors) > MAX_CURSORS:
            self._cursors.popitem(last=False)
        return token

    async def _check(self, ids: list[int], request: Request) -> set[int]:
        # 显式空 Cookie 防止共享 HTTP 客户端的 cookie jar 混入其他请求的身份。
        headers = {"cookie": request.headers.get("cookie", "")}
        if "authorization" in request.headers:
            headers["authorization"] = request.headers["authorization"]

        async def fetch():
            async with self._client.stream("POST", self._url, headers=headers, json={"alarm_ids": ids}) as response:
                if response.status_code in (401, 403):
                    raise HTTPException(response.status_code, "alarm authorization rejected")
                if response.status_code != 200:
                    raise HTTPException(502, "alarm authorization upstream failed; retry")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=MAX_RESPONSE_BYTES):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise HTTPException(502, "invalid alarm authorization response")
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise HTTPException(502, "invalid alarm authorization response") from exc
                allowed = data.get("allowed_ids") if isinstance(data, dict) else None
                if (not isinstance(allowed, list) or len(allowed) > BATCH_SIZE
                        or any(type(value) is not int or value not in ids for value in allowed)):
                    raise HTTPException(502, "invalid alarm authorization response")
                return set(allowed)

        try:
            return await asyncio.wait_for(fetch(), timeout=BATCH_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise HTTPException(504, "alarm authorization timed out; retry") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, "alarm authorization upstream unavailable; retry") from exc

    async def _visible(self, candidates: list[str], request: Request, user: dict) -> set[str]:
        # 保持原有管理员及非 AiVision 来源的处置权限，不新增来源权限例外。
        if user.get("role") == "admin":
            return set(candidates)
        visible = {key for key in candidates if not key.startswith("aivision:")}
        source_ids = {key: _source_id(key) for key in candidates if key.startswith("aivision:")}
        ids = list(dict.fromkeys(number for number in source_ids.values() if number is not None))
        if ids:
            allowed = await self._check(ids, request)
            visible.update(key for key, number in source_ids.items() if number in allowed)
        return visible

    async def require_access(self, alarm_id: str, request: Request, user: dict):
        async with self._admitted():
            if alarm_id not in await self._visible([alarm_id], request, user):
                raise HTTPException(403, "alarm permission required")

    async def page(self, store: AlarmDispositionStore, request: Request, user: dict,
                   *, limit: int, cursor: str | None) -> DispositionPage:
        offset, revision = self._resume(cursor, user)

        async def scan():
            nonlocal offset, revision
            selected = []
            reason = "scan_limit"
            for _ in range(MAX_BATCHES):
                candidates, at_end, revision = store.scan_ids(offset=offset, limit=BATCH_SIZE, revision=revision)
                visible = await self._visible(candidates, request, user)
                consumed = 0
                for key in candidates:
                    consumed += 1
                    if key in visible:
                        selected.append(key)
                    if len(selected) == limit:
                        break
                offset += consumed
                if at_end and consumed == len(candidates):
                    reason = "end"
                    break
                if len(selected) == limit:
                    reason = "page_full"
                    break
            # 授权期间发生写入也要求重开分页，不返回混合快照。
            rows = store.get_many(selected, revision=revision)
            next_cursor = None if reason == "end" else self._continuation(user, revision, offset)
            return DispositionPage(items=[rows[key] for key in selected], next_cursor=next_cursor, stop_reason=reason)

        async with self._admitted():
            try:
                return await asyncio.wait_for(scan(), timeout=QUERY_TIMEOUT_SECONDS)
            except DispositionSnapshotChanged as exc:
                raise HTTPException(409, str(exc)) from exc
            except DispositionStoreBusy as exc:
                raise HTTPException(503, "disposition store busy; retry") from exc
            except asyncio.TimeoutError as exc:
                raise HTTPException(504, "disposition query timed out; retry the same cursor") from exc
