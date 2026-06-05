"""统一平台后端入口。

统一后端只做平台级能力和请求转发，不接管各算法子系统的运行逻辑：
- 本地处理登录、当前用户、改密、报警处置状态；
- 转发 Guard Room、AiVision、Security VLM 的业务接口。
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from auth.auth import (  # noqa: E402
    AuthError,
    ChangePasswordRequest,
    LoginRequest,
    change_own_password,
    clear_auth_cookie,
    create_token,
    get_current_user,
    get_current_user_from_request,
    set_auth_cookie,
    verify_login,
)
from unified_backend.alarm_dispositions import AlarmDispositionStore  # noqa: E402


class AlarmDispositionUpdateRequest(BaseModel):
    alarm_id: str
    status: str
    note: str = ""


ALARM_TYPE_META: dict[str, dict[str, str]] = {
    "blocks": {"name": "区域入侵", "color": "#ef4444"},
    "detect_door": {"name": "大门开关", "color": "#f59e0b"},
    "detect_phone": {"name": "手机检测", "color": "#f97316"},
    "detect_face": {"name": "人脸检测", "color": "#8b5cf6"},
    "detect_human": {"name": "人体逗留", "color": "#2563eb"},
    "guard_absent": {"name": "保安离岗", "color": "#dc2626"},
    "guard_phone_use": {"name": "保安玩手机", "color": "#ea580c"},
    "guard_prone_sleep": {"name": "保安趴睡", "color": "#ca8a04"},
    "security_vlm_non_compliant": {"name": "安检流程不规范", "color": "#0891b2"},
    "security_vlm_error": {"name": "安检判定错误", "color": "#d97706"},
}

GUARD_EVENT_META: dict[str, dict[str, str]] = {
    "absent": {"event_type": "guard_absent", "event_label": "保安离岗"},
    "phone_use": {"event_type": "guard_phone_use", "event_label": "保安玩手机"},
    "prone_sleep": {"event_type": "guard_prone_sleep", "event_label": "保安趴睡"},
}

DEPARTMENT_EVENT_TYPES: dict[str, set[str]] = {
    "general_electric": {
        "security_vlm_non_compliant",
        "security_vlm_error",
        "guard_absent",
        "guard_phone_use",
        "guard_prone_sleep",
        "detect_human",
    },
    "research_institute": {
        "blocks",
        "detect_face",
        "detect_phone",
    },
}


def _now() -> float:
    return time.time()


def _env_url(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


def _cors_origins() -> list[str]:
    raw = os.getenv(
        "AUTH_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://aicv.fudar.com",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def _filtered_headers(headers: requests.structures.CaseInsensitiveDict) -> dict[str, str]:
    excluded = {"content-length", "transfer-encoding", "connection", "content-encoding"}
    return {key: value for key, value in headers.items() if key.lower() not in excluded}


def _request_headers(request: Request) -> dict[str, str]:
    excluded = {"host", "content-length", "connection"}
    return {key: value for key, value in request.headers.items() if key.lower() not in excluded}


def _stream_response(upstream: requests.Response) -> StreamingResponse:
    def chunks() -> Iterable[bytes]:
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        chunks(),
        status_code=upstream.status_code,
        headers=_filtered_headers(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


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


def _parse_iso_ts(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


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


def _alarm_sort_key(alarm: dict[str, Any]) -> float:
    created = _parse_alarm_datetime(alarm.get("created_at"))
    return created.timestamp() if created else 0.0


def _items_from_payload(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("items") or payload.get("alarms") or []
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_guard_alarm(alarm: dict[str, Any]) -> dict[str, Any]:
    source_id = str(alarm.get("id") or "")
    raw_type = str(alarm.get("event_type") or "")
    meta = GUARD_EVENT_META.get(raw_type) or {
        "event_type": f"guard_{raw_type}" if raw_type else "guard_alarm",
        "event_label": "保安行为",
    }
    camera_name = str(alarm.get("camera_name") or "保安行为规范检测")
    return {
        **alarm,
        "id": f"guard:{source_id}",
        "source": "guard_room",
        "source_id": source_id,
        "event_type": meta["event_type"],
        "event_label": meta["event_label"],
        "camera_no": alarm.get("camera_name") or "guard_room",
        "camera_name": camera_name,
        "image_url": f"/api/alarms/{source_id}/image",
        "video_url": f"/api/alarms/{source_id}/video" if alarm.get("video_status") == "ready" else None,
    }


def _normalize_aivision_alarm(alarm: dict[str, Any]) -> dict[str, Any]:
    source_id = str(alarm.get("id") or "")
    return {
        **alarm,
        "id": f"aivision:{source_id}",
        "source": "aivision",
        "source_id": source_id,
        "image_url": alarm.get("image_url") or f"/api/aivision/alarms/{source_id}/image",
        "video_url": alarm.get("video_url") or None,
    }


def _normalize_security_vlm_alarm(item: dict[str, Any]) -> dict[str, Any] | None:
    status = str(item.get("status") or "")
    if status not in {"non_compliant", "error"}:
        return None
    source_id = str(item.get("session_id") or f"{item.get('roi_name') or 'security_vlm'}:{item.get('time') or int(_now())}")
    event_type = "security_vlm_error" if status == "error" else "security_vlm_non_compliant"
    return {
        "id": f"security_vlm:{source_id}",
        "source": "security_vlm",
        "source_id": source_id,
        "event_type": event_type,
        "event_label": "安检判定错误" if status == "error" else "安检流程不规范",
        "camera_no": item.get("roi_name") or "security_vlm",
        "camera_name": item.get("roi_name") or "安检流程规范检测",
        "reason": item.get("error") or item.get("reason") or "安检流程规范检测判定异常",
        "confidence": 1,
        "created_at": item.get("time"),
        "image_url": None,
        "video_url": None,
        "video_status": None,
    }


def _allowed_event_types_for_user(user: dict[str, Any]) -> set[str] | None:
    role = str(user.get("role") or "").strip().lower()
    if role == "admin":
        return None
    if role != "viewer":
        return set()
    department = str(user.get("department") or "").strip()
    if department == "all":
        return None
    return set(DEPARTMENT_EVENT_TYPES.get(department, set()))


def _parse_event_types(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    values = {item.strip() for item in raw.split(",") if item.strip()}
    return values or None


def _filter_alarms(
    alarms: list[dict[str, Any]],
    *,
    user: dict[str, Any],
    event_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = _allowed_event_types_for_user(user)
    if allowed is not None:
        alarms = [alarm for alarm in alarms if alarm.get("event_type") in allowed]
    if event_types is not None:
        alarms = [alarm for alarm in alarms if alarm.get("event_type") in event_types]
    return alarms


def _with_disposition(alarm: dict[str, Any], dispositions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    disposition = dispositions.get(str(alarm.get("id") or ""))
    return {
        **alarm,
        "disposition_status": disposition.get("status", "pending") if disposition else "pending",
        "disposition_note": disposition.get("note", "") if disposition else "",
        "disposition_updated_at": disposition.get("updated_at") if disposition else None,
        "disposition_updated_by": disposition.get("updated_by") if disposition else None,
    }


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

    ai_payload = _get_upstream_json(aivision_url, f"/api/aivision/alarms?limit={upstream_limit}", request)
    alarms.extend(_normalize_aivision_alarm(item) for item in _items_from_payload(ai_payload))

    guard_payload = _get_upstream_json(guard_room_url, f"/api/alarms?limit={upstream_limit}", request)
    alarms.extend(_normalize_guard_alarm(item) for item in _items_from_payload(guard_payload))

    vlm_payload = _get_upstream_json(security_vlm_url, f"/api/history?limit={upstream_limit}", request)
    if isinstance(vlm_payload, dict):
        for item in _items_from_payload(vlm_payload.get("history")):
            alarm = _normalize_security_vlm_alarm(item)
            if alarm:
                alarms.append(alarm)

    disposition_map = {
        str(item.get("alarm_id")): item
        for item in disposition_store.list_items()
        if isinstance(item, dict) and item.get("alarm_id")
    }
    merged = [_with_disposition(alarm, disposition_map) for alarm in alarms]
    scoped = _filter_alarms(merged, user=user, event_types=event_types)
    return sorted(scoped, key=_alarm_sort_key, reverse=True)[:limit]


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
    by_camera: Counter[str] = Counter()
    camera_names: dict[str, str] = {}
    daily_counts: dict[str, Counter[str]] = defaultdict(Counter)
    hourly_counts: dict[int, Counter[str]] = defaultdict(Counter)

    for alarm, created in in_range:
        event_type = str(alarm.get("event_type") or "unknown")
        meta = ALARM_TYPE_META.get(event_type, {"name": event_type, "color": "#64748b"})
        row = by_type.setdefault(
            event_type,
            {
                "event_type": event_type,
                "name": alarm.get("event_label") or meta["name"],
                "value": 0,
                "color": meta["color"],
            },
        )
        row["value"] += 1

        camera_no = str(alarm.get("camera_no") or alarm.get("camera_name") or "unknown")
        by_camera[camera_no] += 1
        camera_names[camera_no] = str(alarm.get("camera_name") or camera_no)
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
            "week": len(in_range),
            "avg_per_day": round(len(in_range) / days, 2),
            "active_cameras": len(by_camera),
            "peak_hour": peak.get("time") if peak.get("total") else "-",
        },
        "by_type": list(by_type.values()),
        "by_camera": [
            {"camera_no": camera_no, "name": camera_names.get(camera_no, camera_no), "value": value}
            for camera_no, value in by_camera.most_common(8)
        ],
        "daily": daily,
        "hourly": hourly,
        "recent": alarms[:8],
    }


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


def _camera_functions_enabled(camera: dict) -> bool:
    functions = camera.get("functions")
    if isinstance(functions, dict):
        return any(bool(value) for value in functions.values())
    if isinstance(functions, list):
        return len(functions) > 0
    return False


def _camera_feature_enabled(camera: dict, feature: str) -> bool:
    functions = camera.get("functions")
    if isinstance(functions, dict):
        return bool(functions.get(feature))
    if isinstance(functions, list):
        return feature in {str(item) for item in functions}
    return False


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


def _service_status(name: str, url: str, online: bool, latency_ms: float | None, error: str | None, extra: dict) -> dict:
    return {
        "name": name,
        "url": url,
        "online": online,
        "latency_ms": latency_ms,
        "error": error,
        **extra,
    }


async def _proxy(request: Request, base_url: str, upstream_path: str) -> Response:
    query = f"?{request.url.query}" if request.url.query else ""
    url = urljoin(f"{base_url}/", upstream_path.lstrip("/")) + query
    body = await request.body()
    try:
        upstream = requests.request(
            method=request.method,
            url=url,
            params=None,
            data=body if body else None,
            headers=_request_headers(request),
            cookies=request.cookies,
            stream=True,
            timeout=(5, None),
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"upstream unavailable: {base_url}") from exc

    return _stream_response(upstream)


def create_app() -> FastAPI:
    guard_room_url = _env_url("UNIFIED_GUARD_ROOM_URL", "http://127.0.0.1:5001")
    aivision_url = _env_url("UNIFIED_AIVISION_URL", "http://127.0.0.1:7862")
    security_vlm_url = _env_url("UNIFIED_SECURITY_VLM_URL", "http://127.0.0.1:8000")
    data_dir = os.getenv("UNIFIED_BACKEND_DATA_DIR", str(_REPO_ROOT / "unified_backend" / "data"))
    disposition_store = AlarmDispositionStore(data_dir)

    app = FastAPI(title="Fuda Unified Backend", version="1.0.0")
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
        if request.method == "OPTIONS" or path in public_paths:
            return await call_next(request)
        protected = path.startswith("/api/") or path.startswith("/security-vlm") or path.startswith("/aivision")
        if protected:
            try:
                request.state.user = get_current_user_from_request(request)
            except AuthError as exc:
                return JSONResponse(status_code=401, content={"detail": str(exc)})
        return await call_next(request)

    @app.get("/")
    def root():
        return {
            "name": "fuda-unified-backend",
            "ok": True,
            "guard_room": guard_room_url,
            "aivision": aivision_url,
            "security_vlm": security_vlm_url,
        }

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "unified_backend", "port": int(os.getenv("UNIFIED_BACKEND_PORT", "5000"))}

    @app.get("/api/platform/status")
    def platform_status(request: Request):
        now = _now()

        guard_health_ok, _guard_health, guard_latency, guard_health_error = _get_json(guard_room_url, "/api/health")
        _guard_status_ok, guard_status, _guard_status_latency, guard_status_error = _get_json(guard_room_url, "/api/status", request=request)
        guard_cfg_ok, guard_config, _guard_cfg_latency, _guard_cfg_error = _get_json(guard_room_url, "/api/config", request=request)
        guard_last_frame_ts = _parse_iso_ts(guard_status.get("updated_at") if isinstance(guard_status, dict) else None)
        guard_camera_count = _count_guard_cameras(guard_config) if guard_cfg_ok else 0
        guard_running = bool(guard_status.get("running")) if isinstance(guard_status, dict) else False

        ai_health_ok, ai_health, ai_latency, ai_health_error = _get_json(aivision_url, "/api/v2/runtime/health")
        _ai_status_ok, ai_status, _ai_status_latency, ai_status_error = _get_json(aivision_url, "/api/v2/runtime/status", request=request)
        _ai_cam_ok, ai_cameras, _ai_cam_latency, _ai_cam_error = _get_json(aivision_url, "/api/v2/cameras", request=request)
        if not isinstance(ai_status, dict) and isinstance(ai_health, dict):
            ai_status = ai_health
        ai_running_cameras = ai_status.get("running_cameras", []) if isinstance(ai_status, dict) else []
        ai_running_models = ai_status.get("running_models", []) if isinstance(ai_status, dict) else []
        ai_running_consumers = ai_status.get("running_consumers", []) if isinstance(ai_status, dict) else []
        ai_camera_items = ai_cameras if isinstance(ai_cameras, list) else []
        ai_enabled_camera_count = sum(1 for camera in ai_camera_items if camera.get("enabled") and _camera_functions_enabled(camera))
        ai_feature_status = _aivision_feature_status(ai_camera_items, ai_running_cameras)

        vlm_ok, vlm_health, vlm_latency, vlm_error = _get_json(security_vlm_url, "/health")
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
                guard_health_error if not guard_health_ok else (guard_status_error if guard_status_error and guard_status_error != "401 Unauthorized" else None),
                {
                    "running": guard_running,
                    "camera_count": guard_camera_count,
                    "online_camera_count": guard_camera_count if guard_running else 0,
                    "offline_camera_count": 0 if guard_running else guard_camera_count,
                    "fps": guard_status.get("fps") if isinstance(guard_status, dict) else None,
                    "frame_count": guard_status.get("frame_count") if isinstance(guard_status, dict) else None,
                    "last_frame_age_sec": round(now - guard_last_frame_ts, 1) if guard_last_frame_ts else None,
                    "model_status": {
                        "pose_enabled": bool(guard_status.get("pose_enabled")) if isinstance(guard_status, dict) else False,
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

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response):
        user = verify_login(payload.employee_id, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid employee_id or password")
        token = create_token(user)
        set_auth_cookie(response, token, request)
        return {"success": True, "user": user}

    @app.get("/api/auth/me")
    def me(user: dict = Depends(get_current_user)):
        return {"success": True, "user": user}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        clear_auth_cookie(response, request)
        return {"success": True}

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
        return {"success": True, "user": updated_user}

    @app.get("/api/alarm-dispositions")
    def get_alarm_dispositions():
        return {"items": disposition_store.list_items()}

    @app.post("/api/alarm-dispositions")
    def update_alarm_disposition(payload: AlarmDispositionUpdateRequest, user: dict = Depends(get_current_user)):
        try:
            item = disposition_store.update(
                alarm_id=payload.alarm_id,
                status=payload.status,
                note=payload.note,
                user=user,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "item": item}

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

    @app.api_route("/api/aivision/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_aivision_api(path: str, request: Request):
        return await _proxy(request, aivision_url, f"/api/aivision/{path}")

    @app.api_route("/api/v2/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_aivision_v2_api(path: str, request: Request):
        return await _proxy(request, aivision_url, f"/api/v2/{path}")

    @app.api_route("/api/ai/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_aivision_legacy_api(path: str, request: Request):
        return await _proxy(request, aivision_url, f"/api/ai/{path}")

    @app.api_route("/aivision/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_aivision_root(path: str, request: Request):
        return await _proxy(request, aivision_url, f"/{path}")

    @app.api_route("/security-vlm/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_security_vlm(path: str, request: Request):
        return await _proxy(request, security_vlm_url, f"/{path}")

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_guard_room_api(path: str, request: Request):
        return await _proxy(request, guard_room_url, f"/api/{path}")

    return app
