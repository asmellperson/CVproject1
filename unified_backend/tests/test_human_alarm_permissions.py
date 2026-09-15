"""合并后的事件类型、统计与报警处置均按事业部授权。"""
import importlib
from datetime import datetime

from fastapi import HTTPException
import pytest

backend = importlib.import_module("unified_backend.app")


def alarm(number, department):
    return {"id": str(number), "feature_name": "detect_human", "event_type": "detect_human",
            "violation_type": 5, "department": department, "created_at": datetime.now().isoformat()}


@pytest.mark.parametrize("department", ["general_electric", "haoda_company"])
def test_shared_type_permissions_and_statistics_never_mix_departments(department):
    rows = [backend._normalize_aivision_alarm(alarm(1, "general_electric")),
            backend._normalize_aivision_alarm(alarm(2, "haoda_company")),
            backend._normalize_aivision_alarm(alarm(3, None))]
    user = {"role": "viewer", "departments": [department]}
    visible = backend._filter_alarms(rows, user=user, event_types={"detect_human"})
    assert [row["department"] for row in visible] == [department]
    stats = backend._build_alarm_statistics(visible, days=1)
    assert stats["summary"]["total"] == 1


def test_disposition_read_and_write_require_alarm_ownership(monkeypatch, tmp_path):
    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    app = backend.create_app()
    get = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/alarm-dispositions" and "GET" in route.methods)
    put = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/alarm-dispositions" and "POST" in route.methods)
    rows = {"1": alarm(1, "general_electric"), "2": alarm(2, "haoda_company")}
    monkeypatch.setattr(backend, "_get_upstream_json", lambda _url, path, _request: rows.get(path.rsplit("/", 1)[-1]))
    admin = {"role": "admin", "employee_id": "test-admin"}
    viewer = {"role": "viewer", "departments": ["haoda_company"], "employee_id": "test-viewer"}
    def payload(number, note="test-note"):
        return backend.AlarmDispositionUpdateRequest(alarm_id=f"aivision:{number}", status="acknowledged", note=note)
    for number in (1, 2):
        put(payload(number), request=None, user=admin)
    assert [item["alarm_id"] for item in get(request=None, user=viewer)["items"]] == ["aivision:2"]
    assert put(payload(2, "permitted"), request=None, user=viewer)["success"] is True
    before = (tmp_path / "alarm_dispositions.json").read_bytes()
    for number in (1, 999):
        with pytest.raises(HTTPException) as error:
            put(payload(number), request=None, user=viewer)
        assert error.value.status_code == 403
    assert (tmp_path / "alarm_dispositions.json").read_bytes() == before


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
