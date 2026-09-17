"""处置有界分页、跨事业部权限、故障隔离与资源生命周期。"""
import asyncio
from contextlib import asynccontextmanager
import importlib
import json
from pathlib import Path
import threading

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from AiVision.tests.test_alarm_access_batch import alarm_api as alarm_api  # 共用临时库和真实认证夹具
from unified_backend.alarm_dispositions import AlarmDispositionStore
from unified_backend.disposition_queries import DispositionQueries
import unified_backend.disposition_queries as queries

backend = importlib.import_module("unified_backend.app")
VIEWER = {"employee_id": "ge", "role": "viewer", "departments": ["general_electric"], "auth_version": 1}
ADMIN = {"employee_id": "admin", "role": "admin", "departments": ["all"]}
REQUEST = Request({"type": "http", "headers": [(b"authorization", b"Bearer test-only-token")]})


def seed_store(tmp_path, ids):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "alarm_dispositions.json").write_text(json.dumps({"items": [
        {"alarm_id": key, "status": "pending", "note": key, "updated_at": "2020-01-01"} for key in ids
    ]}))
    return AlarmDispositionStore(tmp_path)


@asynccontextmanager
async def gateway(monkeypatch, tmp_path, alarm_api):
    data_dir = tmp_path / "dispositions"
    seed_store(data_dir, [f"aivision:{number}" for number in range(1, 502)])
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(data_dir))
    def factory(url):
        return DispositionQueries(url, transport=httpx.ASGITransport(app=alarm_api.app))
    monkeypatch.setattr(backend, "DispositionQueries", factory)
    app = backend.create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield client, app
    assert app.state.disposition_queries._client.is_closed
    assert app.state.disposition_queries._closed


@pytest.mark.parametrize("key,parity", [("ge", 1), ("haoda", 0), ("both", None), ("admin", None)])
def test_interleaved_pages_are_complete_stable_and_scoped(monkeypatch, tmp_path, alarm_api, key, parity):
    async def scenario():
        async with gateway(monkeypatch, tmp_path, alarm_api) as (client, _app):
            headers = {"Authorization": f"Bearer {alarm_api.tokens[key]}"}
            cursor = None
            found = []
            while True:
                params = {"limit": 17}
                if cursor:
                    params["cursor"] = cursor
                response = await client.get("/api/alarm-dispositions", params=params, headers=headers)
                assert response.status_code == 200, response.text
                page = response.json()
                found.extend(item["alarm_id"] for item in page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    assert page["stop_reason"] == "end"
                    break
                assert len(page["items"]) == 17
                assert page["stop_reason"] == "page_full"
            expected = sorted(f"aivision:{n}" for n in range(1, 502) if parity is None or n % 2 == parity)
            assert found == expected
            assert len(set(found)) == len(found)
    asyncio.run(scenario())


def test_defaults_limits_single_and_historic_write_permissions(monkeypatch, tmp_path, alarm_api):
    async def scenario():
        async with gateway(monkeypatch, tmp_path, alarm_api) as (client, _app):
            headers = {"Authorization": f"Bearer {alarm_api.tokens['ge']}"}
            assert (await client.get("/api/alarm-dispositions")).status_code == 401
            page = (await client.get("/api/alarm-dispositions", headers=headers)).json()
            assert len(page["items"]) == 50 and "total" not in page
            assert "aivision:1" in [item["alarm_id"] for item in page["items"]]
            for limit in (0, 101, -1):
                assert (await client.get(f"/api/alarm-dispositions?limit={limit}", headers=headers)).status_code == 422
            assert len((await client.get("/api/alarm-dispositions?limit=100", headers=headers)).json()["items"]) == 100
            assert (await client.get("/api/alarm-dispositions/aivision:1", headers=headers)).status_code == 200
            assert (await client.post("/api/alarm-dispositions", headers=headers, json={
                "alarm_id": "aivision:1", "status": "resolved", "note": "old valid alarm",
            })).status_code == 200
            path = tmp_path / "dispositions" / "alarm_dispositions.json"
            before = path.read_bytes()
            for key in ("aivision:2", "aivision:99999", "aivision:bad"):
                assert (await client.get(f"/api/alarm-dispositions/{key}", headers=headers)).status_code == 403
                assert (await client.post("/api/alarm-dispositions", headers=headers, json={
                    "alarm_id": key, "status": "resolved",
                })).status_code == 403
            assert path.read_bytes() == before
            assert (await client.get("/api/alarm-dispositions/aivision:1001", headers=headers)).status_code == 404
    asyncio.run(scenario())


def test_large_history_scan_is_bounded_and_empty_scan_can_continue(monkeypatch, tmp_path):
    async def scenario():
        ids = [f"aivision:{n:06}" for n in range(1, 20001)]
        store = seed_store(tmp_path, ids)
        calls, scans = [], []
        def upstream(request):
            numbers = json.loads(request.content)["alarm_ids"]
            calls.append(numbers)
            return httpx.Response(200, json={"allowed_ids": [n for n in numbers if n in (501, 503)]})
        scan = store.scan_ids
        def counted_scan(**kwargs):
            result = scan(**kwargs)
            scans.append(len(result[0]))
            return result
        monkeypatch.setattr(store, "scan_ids", counted_scan)
        # 初始化完成后任何全量读取、磁盘读取、排序都是回归。
        def forbidden(*_args, **_kwargs):
            raise AssertionError("full store read/sort during page")
        monkeypatch.setattr(Path, "read_text", forbidden)
        class NoIteration(dict):
            def __iter__(self): return forbidden()
            def values(self): return forbidden()
            def items(self): return forbidden()
        class NoIndexIteration(list):
            def __iter__(self): return forbidden()
        store._items = NoIteration(store._items)
        store._ordered_ids = NoIndexIteration(store._ordered_ids)
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
        try:
            page = await service.page(store, REQUEST, VIEWER, limit=2, cursor=None)
            assert page.items == [] and page.stop_reason == "scan_limit" and page.next_cursor
            assert len(calls) == 5 and sum(map(len, calls)) == sum(scans) == 500
            calls.clear()
            scans.clear()
            page = await service.page(store, REQUEST, VIEWER, limit=2, cursor=page.next_cursor)
            assert [item["alarm_id"] for item in page.items] == ids[500:503:2]
            assert page.stop_reason == "page_full" and page.next_cursor
            assert len(calls) == 1 and sum(scans) == 100
        finally:
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("kind,status", [
    ("error", 502), ("timeout", 504), ("disconnect", 502), ("malformed", 502),
    ("oversized", 502), ("unauthorized_id", 502), ("login_expired", 401), ("denied", 403),
])
def test_batch_failure_never_returns_partial_page_or_advances_cursor(tmp_path, kind, status):
    async def scenario():
        store = seed_store(tmp_path, [f"aivision:{n:04}" for n in range(1, 1002)])
        calls = []
        failing = False
        def upstream(request):
            ids = json.loads(request.content)["alarm_ids"]
            calls.append(ids)
            if failing:
                if kind == "timeout":
                    raise httpx.ReadTimeout("test", request=request)
                if kind == "disconnect":
                    raise httpx.ConnectError("test", request=request)
                if kind == "malformed":
                    return httpx.Response(200, content=b"invalid")
                if kind == "oversized":
                    return httpx.Response(200, content=b" " * 9000)
                if kind == "unauthorized_id":
                    return httpx.Response(200, json={"allowed_ids": [99999]})
                return httpx.Response({"error": 500, "login_expired": 401, "denied": 403}[kind])
            return httpx.Response(200, json={"allowed_ids": ids})
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
        try:
            page = await service.page(store, REQUEST, VIEWER, limit=10, cursor=None)
            cursor = page.next_cursor
            failing = True
            with pytest.raises(HTTPException) as error:
                await service.page(store, REQUEST, VIEWER, limit=10, cursor=cursor)
            assert error.value.status_code == status
            failed_ids = calls[-1]
            failing = False
            page = await service.page(store, REQUEST, VIEWER, limit=10, cursor=cursor)
            assert calls[-1] == failed_ids
            assert page.items[0]["alarm_id"] == "aivision:0011"
        finally:
            await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("deadline", ["QUERY_TIMEOUT_SECONDS", "BATCH_TIMEOUT_SECONDS"])
def test_late_batch_failure_discards_earlier_results_and_deadline_cancels(tmp_path, monkeypatch, deadline):
    async def scenario():
        store = seed_store(tmp_path, [f"aivision:{n:04}" for n in range(1, 1002)])
        calls = 0
        cancelled = asyncio.Event()
        async def upstream(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(200, json={"allowed_ids": [1]})
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        monkeypatch.setattr(queries, deadline, .05)
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
        try:
            with pytest.raises(HTTPException) as error:
                await service.page(store, REQUEST, VIEWER, limit=50, cursor=None)
            assert error.value.status_code == 504
            assert calls == 2 and cancelled.is_set() and not service._cursors
            assert service._slots._value == queries.MAX_CONCURRENT_QUERIES
        finally:
            await service.close()
    asyncio.run(scenario())


def test_slow_authorization_has_bounded_concurrency_and_leaves_home_executor_free(tmp_path, monkeypatch):
    async def scenario():
        store = seed_store(tmp_path, ["aivision:1"])
        entered, release = asyncio.Event(), asyncio.Event()
        calls = 0
        async def upstream(_request):
            nonlocal calls
            calls += 1
            if calls == queries.MAX_CONCURRENT_QUERIES:
                entered.set()
            await release.wait()
            return httpx.Response(200, json={"allowed_ids": [1]})
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
        tasks = [asyncio.create_task(service.page(store, REQUEST, VIEWER, limit=1, cursor=None))
                 for _ in range(queries.MAX_CONCURRENT_QUERIES)]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with pytest.raises(HTTPException) as error:
                await service.page(store, REQUEST, VIEWER, limit=1, cursor=None)
            assert error.value.status_code == 503 and calls == 4
            threads = []
            def status(*_args, **_kwargs):
                threads.append(threading.current_thread().name)
                return True, {"started": True}, 0, None
            monkeypatch.setattr(backend, "_get_json", status)
            result = await asyncio.wait_for(asyncio.to_thread(backend._get_json_concurrently,
                {"status": ("http://aivision", "/api/runtime/status", None)}), .5)
            assert result["status"][1] == {"started": True}
            assert threads and all(name.startswith("overview") for name in threads)
            assert all(not task.done() for task in tasks)
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await service.close()
        assert service._client.is_closed
        with pytest.raises(HTTPException) as error:
            await service.page(store, REQUEST, VIEWER, limit=1, cursor=None)
        assert error.value.status_code == 503
    asyncio.run(scenario())


def test_cursors_bind_user_permissions_revision_expiry_and_capacity(tmp_path, monkeypatch):
    async def scenario():
        store = seed_store(tmp_path, ["aivision:1", "aivision:2"])
        service = DispositionQueries("http://aivision")
        try:
            page = await service.page(store, REQUEST, ADMIN, limit=1, cursor=None)
            for user in (VIEWER, {**ADMIN, "auth_version": 99}):
                with pytest.raises(HTTPException) as error:
                    await service.page(store, REQUEST, user, limit=1, cursor=page.next_cursor)
                assert error.value.status_code == 409
            store.update(alarm_id="aivision:1", status="resolved", note="change", user=ADMIN)
            with pytest.raises(HTTPException) as error:
                await service.page(store, REQUEST, ADMIN, limit=1, cursor=page.next_cursor)
            assert error.value.status_code == 409
            monkeypatch.setattr(queries, "MAX_CURSORS", 2)
            for _ in range(3):
                await service.page(store, REQUEST, ADMIN, limit=1, cursor=None)
            assert len(service._cursors) == 2
            with pytest.raises(HTTPException) as error:
                await service.page(store, REQUEST, ADMIN, limit=1, cursor=page.next_cursor)
            assert error.value.status_code == 410
            monkeypatch.setattr(queries, "CURSOR_TTL_SECONDS", -1)
            page = await service.page(store, REQUEST, ADMIN, limit=1, cursor=None)
            with pytest.raises(HTTPException) as error:
                await service.page(store, REQUEST, ADMIN, limit=1, cursor=page.next_cursor)
            assert error.value.status_code == 410
        finally:
            await service.close()
        assert not service._cursors
    asyncio.run(scenario())


def test_shared_client_never_reuses_another_users_cookie(tmp_path):
    async def scenario():
        cookies = []
        def upstream(request):
            cookies.append(request.headers.get("cookie"))
            return httpx.Response(200, json={"allowed_ids": [1]}, headers={"Set-Cookie": "session=other-user; Path=/"})
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
        try:
            request = Request({"type": "http", "headers": [(b"cookie", b"session=first-user")]})
            await service.require_access("aivision:1", request, VIEWER)
            await service.require_access("aivision:1", REQUEST, VIEWER)
            assert cookies == ["session=first-user", ""]
        finally:
            await service.close()
    asyncio.run(scenario())


def test_store_write_failure_preserves_memory_disk_and_revision(tmp_path, monkeypatch):
    store = seed_store(tmp_path, ["aivision:1"])
    before = store.path.read_bytes()
    ids, _end, revision = store.scan_ids(offset=0, limit=100, revision=None)
    def fail(_items):
        raise OSError("test disk failure")
    monkeypatch.setattr(store, "_flush", fail)
    with pytest.raises(OSError):
        store.update(alarm_id="aivision:2", status="resolved", note="test", user=ADMIN)
    assert store.path.read_bytes() == before
    assert store.scan_ids(offset=0, limit=100, revision=revision)[0] == ids
    assert not store.get_many(["aivision:2"])


def test_update_during_authorization_rejects_mixed_snapshot(tmp_path):
    async def scenario():
        store = seed_store(tmp_path, ["aivision:1", "aivision:2"])
        def upstream(_request):
            store.update(alarm_id="aivision:1", status="resolved", note="concurrent change", user=ADMIN)
            return httpx.Response(200, json={"allowed_ids": [1, 2]})
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
        try:
            with pytest.raises(HTTPException) as error:
                await service.page(store, REQUEST, VIEWER, limit=1, cursor=None)
            assert error.value.status_code == 409 and not service._cursors
        finally:
            await service.close()
    asyncio.run(scenario())


def test_store_lock_has_bounded_wait_and_disk_write_does_not_block_reads(tmp_path, monkeypatch):
    async def scenario():
        store = seed_store(tmp_path, ["aivision:1"])
        service = DispositionQueries("http://aivision")
        try:
            store._lock.acquire()
            try:
                with pytest.raises(HTTPException) as error:
                    await service.page(store, REQUEST, ADMIN, limit=1, cursor=None)
                assert error.value.status_code == 503
            finally:
                store._lock.release()
            entered, release = threading.Event(), threading.Event()
            original_flush = store._flush
            def slow_flush(items):
                entered.set()
                assert release.wait(2)
                original_flush(items)
            monkeypatch.setattr(store, "_flush", slow_flush)
            write = asyncio.create_task(asyncio.to_thread(store.update, alarm_id="aivision:1",
                                        status="resolved", note="test", user=ADMIN))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                page = await service.page(store, REQUEST, ADMIN, limit=1, cursor=None)
                assert page.items[0]["status"] == "pending" and not write.done()
            finally:
                release.set()
                await write
            assert store.get_many(["aivision:1"])["aivision:1"]["status"] == "resolved"
            assert AlarmDispositionStore(tmp_path).get_many(["aivision:1"]) == store.get_many(["aivision:1"])
        finally:
            await service.close()
    asyncio.run(scenario())


def test_alarm_list_reads_only_returned_dispositions(tmp_path, monkeypatch):
    store = seed_store(tmp_path, [f"aivision:{n}" for n in range(1, 20001)])
    from types import SimpleNamespace
    read_ids = []
    def get_many(ids):
        read_ids.extend(ids)
        return store.get_many(read_ids)
    rows = [{"id": str(n), "event_type": "detect_human", "violation_type": 5,
             "feature_name": "detect_human", "department": "general_electric" if n % 2 else "haoda_company",
             "created_at": "2020-01-01"} for n in range(1, 101)]
    monkeypatch.setattr(backend, "_get_upstream_json", lambda url, *_args: {"items": rows} if url == "ai" else {})
    result = backend._collect_alarms(request=REQUEST, user=VIEWER, aivision_url="ai",
                                    security_vlm_url="security", disposition_store=SimpleNamespace(get_many=get_many), limit=7)
    assert len(result) == len(read_ids) == 7
    assert all(row["department"] == "general_electric" and row["disposition_status"] == "pending" for row in result)
    assert read_ids == [row["id"] for row in result]


def test_other_sources_and_admin_orphan_permissions_are_unchanged(tmp_path):
    async def scenario():
        ids = ["aivision:99999", "removed_source:1", "security_vlm:general_electric:1"]
        store = seed_store(tmp_path, ids)
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"allowed_ids": []})))
        try:
            page = await service.page(store, REQUEST, ADMIN, limit=50, cursor=None)
            assert [item["alarm_id"] for item in page.items] == sorted(ids)
            page = await service.page(store, REQUEST, VIEWER, limit=50, cursor=None)
            assert [item["alarm_id"] for item in page.items] == sorted(ids[1:])
            for key in ids[1:]:
                await service.require_access(key, REQUEST, VIEWER)
        finally:
            await service.close()
    asyncio.run(scenario())


def test_lifespan_releases_client_on_application_error(monkeypatch, tmp_path):
    async def scenario():
        monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("AUTH_USERS_DB", str(tmp_path / "auth.sqlite"))
        app = backend.create_app()
        with pytest.raises(RuntimeError, match="test application failure"):
            async with app.router.lifespan_context(app):
                service = app.state.disposition_queries
                assert not service._client.is_closed
                raise RuntimeError("test application failure")
        assert service._client.is_closed and service._closed
    asyncio.run(scenario())


def test_upstream_failure_is_http_error_for_read_and_write_without_file_change(monkeypatch, tmp_path, alarm_api):
    async def scenario():
        async with gateway(monkeypatch, tmp_path, alarm_api) as (client, app):
            def upstream(_request):
                return httpx.Response(503)
            await app.state.disposition_queries.close()
            app.state.disposition_queries = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
            try:
                headers = {"Authorization": f"Bearer {alarm_api.tokens['ge']}"}
                path = tmp_path / "dispositions" / "alarm_dispositions.json"
                before = path.read_bytes()
                for route in ("/api/alarm-dispositions", "/api/alarm-dispositions/aivision:1"):
                    response = await client.get(route, headers=headers)
                    assert response.status_code == 502 and "items" not in response.json()
                response = await client.post("/api/alarm-dispositions", headers=headers,
                                             json={"alarm_id": "aivision:1", "status": "resolved"})
                assert response.status_code == 502
                assert path.read_bytes() == before
            finally:
                await app.state.disposition_queries.close()
    asyncio.run(scenario())
