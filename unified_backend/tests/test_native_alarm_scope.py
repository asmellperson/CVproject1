import pytest
from AiVision.departments.department_registry import DEPARTMENT_SPECS


@pytest.mark.parametrize("department", tuple(DEPARTMENT_SPECS))
def test_overview_alarms_query_department_before_limiting(monkeypatch, department):
    import importlib
    from types import SimpleNamespace
    from fastapi import HTTPException
    backend = importlib.import_module("unified_backend.app")
    calls = []
    foreign = next(value for value in DEPARTMENT_SPECS if value != department)
    def upstream(base, path, request):
        calls.append((base, path))
        if base == "ai":
            return {"items": [
                {"id": 1, "feature_name": "recognize_face", "event_type": "recognize_face", "violation_type": 7,
                 "department": department, "created_at": "2026-09-01", "video_status": None,
                 "event_label": "人脸身份识别", "subject_type": "face_person", "subject_id": "one", "subject_name": "测试一"},
                {"id": 2, "feature_name": "recognize_face", "event_type": "recognize_face", "violation_type": 7,
                 "department": foreign, "created_at": "2026-09-02", "video_status": None,
                 "event_label": "人脸身份识别", "subject_type": "face_person", "subject_id": "two", "subject_name": "测试二"},
            ]}
        return {}
    monkeypatch.setattr(backend, "_get_upstream_json", upstream)
    args = dict(request=None, user={"role": "viewer", "departments": [department]},
                aivision_url="ai",
                disposition_store=SimpleNamespace(get_many=lambda ids: {}), limit=1)
    rows = backend._collect_alarms(**args, department=department)
    assert len(rows) == 1 and rows[0]["department"] == department
    assert ("ai", f"/api/alarms?limit=100&department={department}") in calls
    assert {base for base, _ in calls} == {"ai"}
    calls.clear()
    with pytest.raises(HTTPException) as caught:
        backend._collect_alarms(**args, department=foreign)
    assert caught.value.status_code == 403
    assert calls == []


def test_removed_security_probe_does_not_bypass_business_authorization(tmp_path, monkeypatch):
    import asyncio
    import importlib
    import httpx
    from fastapi.responses import JSONResponse
    from auth.auth import AuthError

    backend = importlib.import_module("unified_backend.app")
    forwarded = []

    async def proxy(request, base_url, upstream_path):
        forwarded.append(upstream_path)
        return JSONResponse({"status": "ok", "ready": True})

    def unauthenticated(_request):
        raise AuthError("authentication required")

    monkeypatch.setenv("UNIFIED_BACKEND_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(backend, "_proxy", proxy)
    monkeypatch.setattr(backend, "get_current_user_from_request", unauthenticated)
    app = backend.create_app()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/security-vlm/health")
            assert response.status_code == 404
            assert (await client.get("/api/security-vlm/departments/fulida_company/health")).status_code == 401
        assert forwarded == []

    asyncio.run(scenario())
