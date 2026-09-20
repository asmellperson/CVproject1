"""合并后的事件类型、统计与报警处置均按事业部授权。"""
import importlib
from datetime import datetime
from auth.alarm_permissions import DETECTION_EVENT_TYPES
from AiVision.departments.department_registry import DEPARTMENT_SPECS

from fastapi import HTTPException
import pytest

backend = importlib.import_module("unified_backend.app")


def alarm(number, department):
    return {"id": str(number), "feature_name": "detect_human", "event_type": "detect_human",
            "violation_type": 5, "department": department, "created_at": datetime.now().isoformat(),
            "event_label": "人员违规逗留检测", "subject_type": "camera", "subject_id": str(number),
            "subject_name": "测试摄像头"}


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
@pytest.mark.parametrize("event_type", sorted(DETECTION_EVENT_TYPES))
def test_every_event_is_accessible_only_within_authorized_department(department, event_type):
    rows = [{**alarm(index, scope), "feature_name": event_type, "event_type": event_type}
            for index, scope in enumerate([*DEPARTMENT_SPECS, None, "unknown"])]
    user = {"role": "viewer", "departments": [department]}
    visible = backend._filter_alarms(rows, user=user, event_types={event_type})
    assert [row["department"] for row in visible] == [department]
    stats = backend._build_alarm_statistics(visible, days=1)
    assert stats["summary"]["total"] == 1
    assert backend._allowed_event_types_for_user(user) == DETECTION_EVENT_TYPES


def test_disposition_read_and_write_require_alarm_ownership(monkeypatch, tmp_path):
    import asyncio
    import httpx
    from starlette.requests import Request
    from unified_backend.disposition_queries import DispositionQueries

    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    app = backend.create_app()
    get = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/alarm-dispositions" and "GET" in route.methods)
    put = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/alarm-dispositions" and "POST" in route.methods)
    admin = {"role": "admin", "employee_id": "test-admin"}
    viewer = {"role": "viewer", "departments": ["haoda_company"], "employee_id": "test-viewer"}
    request = Request({"type": "http", "headers": []})
    def payload(number, note="test-note"):
        return backend.AlarmDispositionUpdateRequest(alarm_id=f"aivision:{number}", status="acknowledged", note=note)
    def upstream(request):
        import json
        ids = json.loads(request.content)["alarm_ids"]
        return httpx.Response(200, json={"allowed_ids": [n for n in ids if n == 2]})
    async def scenario():
        service = DispositionQueries("http://aivision", transport=httpx.MockTransport(upstream))
        app.state.disposition_queries = service
        try:
            for number in (1, 2):
                await put(payload(number), request=request, user=admin)
            page = await get(request=request, user=viewer, limit=50, cursor=None)
            assert [item["alarm_id"] for item in page.items] == ["aivision:2"]
            assert (await put(payload(2, "permitted"), request=request, user=viewer))["success"] is True
            before = (tmp_path / "alarm_dispositions.json").read_bytes()
            for number in (1, 999):
                with pytest.raises(HTTPException) as error:
                    await put(payload(number), request=request, user=viewer)
                assert error.value.status_code == 403
            assert (tmp_path / "alarm_dispositions.json").read_bytes() == before
        finally:
            await service.close()
    asyncio.run(scenario())


def test_public_notification_proxy_preserves_query_and_cache_headers(monkeypatch, tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    calls = []
    class FakeProxy:
        def __init__(self, *_args, **_kwargs):
            pass
        async def send(self, **kwargs):
            calls.append(kwargs)
            return httpx.Response(200, content=b"test-thumbnail", request=httpx.Request("GET", kwargs["url"]),
                                  headers={"Content-Type": "image/jpeg", "Cache-Control": "private, no-store"})
        async def close(self):
            pass
    monkeypatch.setattr(backend, "AsyncProxyClient", FakeProxy)
    with TestClient(backend.create_app()) as client:
        response = client.get("/api/public/alarms/1/image?thumbnail_token=expiry.signature")
    assert response.status_code == 200 and response.content == b"test-thumbnail"
    assert calls[0]["url"].endswith("/api/public/alarms/1/image?thumbnail_token=expiry.signature")
    assert response.headers["cache-control"] == "private, no-store"
