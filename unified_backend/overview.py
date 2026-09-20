"""按登录用户授权范围聚合平台总览，物流成员只补充物理摄像头的能力信息。"""
from collections.abc import Callable
from time import time
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, Field


CAPABILITIES = (
    ("security-vlm", "安检流程规范检测", "security_inspection"),
    ("guard-behavior", "保安行为规范检测", "guard_behavior"),
    ("intrusion-detection", "区域入侵检测", "blocks"),
    ("door-detection", "大门开关异常检测", "detect_door"),
    ("face-detection", "人脸逗留检测", "detect_face"),
    ("face-recognition", "人脸身份识别", "recognize_face"),
    ("human-detection", "人员违规逗留检测", "detect_human"),
    ("logistics-single-person", "物流通道单人检测", "detect_logistics_single_person"),
    ("phone-detection", "手机使用检测", "detect_phone"),
)
FEATURE_PAGES = {feature: page for page, _name, feature in CAPABILITIES}
UpstreamResult = tuple[bool, dict | list | None, float | None, str | None]
ReadMany = Callable[[dict[str, tuple[str, str, Request | None]]], dict[str, UpstreamResult]]


class OverviewCamera(BaseModel):
    key: str
    source: Literal["aivision"]
    camera_id: int
    name: str
    department: str
    identifier: str
    enabled: bool
    online: bool
    capabilities: list[str]
    running_capabilities: list[str] = Field(default_factory=list)
    logistics_memberships: list[dict] = Field(default_factory=list)
    aivision_camera: dict | None = None
    site_id: int | None = None


class OverviewCapability(BaseModel):
    id: str
    name: str
    source: Literal["aivision"]
    camera_count: int
    online_camera_count: int
    running: bool
    model_ready: bool


class OverviewServiceStatus(BaseModel):
    online: bool
    running: bool = False
    error: str | None = None
    latency_ms: float | None = None
    camera_count: int = 0
    online_camera_count: int = 0
    model_ready: bool = False


class OverviewSummary(BaseModel):
    capability_total: int
    capability_online: int
    capability_running: int
    camera_total: int
    camera_online: int
    camera_offline: int


class _OverviewScope(BaseModel):
    generated_at: float
    ok: bool
    level: Literal["healthy", "degraded", "down"]
    inventory_complete: bool
    inventory_errors: dict[str, str]
    summary: OverviewSummary
    capabilities: list[OverviewCapability]
    cameras: list[OverviewCamera]
    services: dict[str, OverviewServiceStatus]
    guard_behavior_sites: list[dict]


class OverviewStatus(_OverviewScope):
    departments: list[str]
    department_summaries: dict[str, OverviewSummary]


def _build_department_overview(department: str, upstream: dict[str, UpstreamResult],
                               site_results: dict[str, UpstreamResult]) -> _OverviewScope:
    errors = {}

    def payload(key: str, expected: type):
        ok, value, _latency, error = upstream[key]
        if not ok or not isinstance(value, expected):
            errors[key] = error or "上游响应格式错误"
            return expected()
        return value

    ai_status = payload("ai_status", dict)
    ai_cameras = payload("ai_cameras", list)
    feature_meta = {item["name"]: item for item in payload("features", dict).get("features", [])}
    logistics = payload("logistics", dict)
    guard_sites = payload("guard_sites", list)
    inspection_status = payload("inspection_status", dict)
    sites = [site for site in guard_sites if site.get("department") == department]
    ok, _value, latency, error = upstream["ai_status"]
    service = OverviewServiceStatus(
        online=ok, latency_ms=latency, error=errors.get("ai_status") or error,
        model_ready=bool(ai_status.get("running_models")),
    )
    running_cameras = set(ai_status.get("running_cameras", []))
    running_features = set(ai_status.get("running_consumers", []))
    memberships = {item["camera_id"]: item for item in logistics.get("items", []) if item.get("department") == department}
    cameras = []
    seen = set()
    for camera in ai_cameras:
        if camera.get("department") != department or camera["camera_id"] in seen:
            continue
        seen.add(camera["camera_id"])
        member = memberships.get(camera["camera_id"], {})
        links = member.get("memberships", [])
        features = [name for name, enabled in camera.get("functions", {}).items() if enabled and name in FEATURE_PAGES]
        capabilities = [FEATURE_PAGES[name] for name in features]
        if links and "logistics-single-person" not in capabilities:
            capabilities.append("logistics-single-person")
        enabled = bool(camera.get("enabled"))
        physical_online = enabled and camera["shm_name"] in running_cameras
        # Guard 是否参与检测以 Site/member 状态为准，Consumer 存活不能代替成员可用性。
        active = [FEATURE_PAGES[name] for name in features
                  if physical_online and name in running_features and name != "guard_behavior"
                  and (name != "security_inspection" or (inspection_status.get("running") and not inspection_status.get("error")))]
        if enabled and member.get("online") and "logistics-single-person" not in active:
            active.append("logistics-single-person")
        cameras.append(OverviewCamera(
            key=f"aivision:{camera['camera_id']}", source="aivision", camera_id=camera["camera_id"],
            name=camera["name"], identifier=camera["shm_name"], department=department,
            enabled=enabled, online=physical_online or (enabled and bool(member.get("online"))),
            capabilities=capabilities, running_capabilities=active,
            logistics_memberships=links, aivision_camera=camera,
        ))
    physical = {camera.camera_id: camera for camera in cameras}
    for site in sites:
        ok, state, _latency, error = site_results[f"{site['id']}:status"]
        members_ok, members, _latency, member_error = site_results[f"{site['id']}:cameras"]
        if not ok or not isinstance(state, dict):
            errors[f"guard_site:{site['id']}"] = error or "保安室状态读取失败"
            state = {}
        if not members_ok or not isinstance(members, list):
            errors[f"guard_members:{site['id']}"] = member_error or "保安室成员读取失败"
            continue
        for member in members:
            camera = physical.get(member["camera_id"])
            if camera is None:
                errors[f"guard_camera:{member['camera_id']}"] = "保安室成员不在物理摄像头清单中"
                continue
            camera.site_id = site["id"]
            if "guard-behavior" not in camera.capabilities:
                camera.capabilities.append("guard-behavior")
            camera.running_capabilities = [name for name in camera.running_capabilities if name != "guard-behavior"]
            ready = state.get("camera_states", {}).get(str(camera.camera_id)) == "READY"
            if (camera.enabled and site.get("enabled") and member.get("member_enabled")
                    and state.get("running") and ready):
                camera.running_capabilities.append("guard-behavior")
    capabilities = []
    for page, name, feature in CAPABILITIES:
        members = [camera for camera in cameras if page in camera.capabilities]
        online_count = sum(page in camera.running_capabilities for camera in members)
        metadata = feature_meta.get(feature)
        model_ready = metadata is not None and set(metadata["required_models"]).issubset(ai_status.get("running_models", []))
        if feature == "security_inspection":
            model_ready = model_ready and bool(inspection_status.get("running")) and not inspection_status.get("error")
        capabilities.append(OverviewCapability(
            id=page, name=name, source="aivision", camera_count=len(members),
            online_camera_count=online_count, running=online_count > 0,
            model_ready=model_ready,
        ))
    camera_online = sum(camera.online for camera in cameras)
    service.camera_count = len(cameras)
    service.online_camera_count = camera_online
    service.running = any(capability.running for capability in capabilities)
    all_online = service.online and not errors
    return _OverviewScope(
        generated_at=time(), ok=all_online,
        level="healthy" if all_online else "degraded" if service.online else "down",
        inventory_complete=not errors, inventory_errors=errors,
        summary=OverviewSummary(
            capability_total=len(capabilities), capability_online=len(capabilities) if service.online else 0,
            capability_running=sum(c.running for c in capabilities), camera_total=len(cameras),
            camera_online=camera_online, camera_offline=len(cameras) - camera_online,
        ), capabilities=capabilities, cameras=cameras, services={"aivision": service},
        guard_behavior_sites=[{"id": site["id"], "name": site["name"], "department": department} for site in sites],
    )


def build_overview(request: Request, departments: list[str], aivision_url: str,
                   read_many: ReadMany) -> OverviewStatus:
    # 公共状态只读取一次，各事业部清单并发获取，避免随授权范围串行增加等待时间。
    calls = {
        "ai_status": (aivision_url, "/api/runtime/status", request),
        "features": (aivision_url, "/api/features", request),
    } if departments else {}
    for department in departments:
        calls.update({
            f"{department}:ai_cameras": (aivision_url, f"/api/cameras?department={department}", request),
            f"{department}:logistics": (aivision_url, f"/api/logistics-channels/inventory?department={department}", request),
            f"{department}:guard_sites": (aivision_url, f"/api/guard-behavior/sites?department={department}", request),
            f"{department}:inspection_status": (aivision_url, f"/api/security-inspection/status?department={department}", request),
        })
    upstream = read_many(calls) if calls else {}
    site_calls = {}
    for department in departments:
        ok, payload, _latency, _error = upstream[f"{department}:guard_sites"]
        if ok and isinstance(payload, list):
            for site in payload:
                if site.get("department") == department:
                    for resource in ("status", "cameras"):
                        site_calls[f"{site['id']}:{resource}"] = (
                            aivision_url, f"/api/guard-behavior/sites/{site['id']}/{resource}", request,
                        )
    site_results = read_many(site_calls) if site_calls else {}
    scopes = {}
    for department in departments:
        scope_upstream = {key: upstream[key] for key in ("ai_status", "features")}
        scope_upstream.update({
            key: upstream[f"{department}:{key}"]
            for key in ("ai_cameras", "logistics", "guard_sites", "inspection_status")
        })
        scopes[department] = _build_department_overview(department, scope_upstream, site_results)

    cameras = [camera for scope in scopes.values() for camera in scope.cameras]
    errors = {f"{department}:{key}": error for department, scope in scopes.items()
              for key, error in scope.inventory_errors.items()}
    items = [scope.services["aivision"] for scope in scopes.values()]
    service = OverviewServiceStatus(
        online=any(item.online for item in items), running=any(item.running for item in items),
        model_ready=any(item.model_ready for item in items),
        camera_count=sum(item.camera_count for item in items),
        online_camera_count=sum(item.online_camera_count for item in items),
        latency_ms=max((item.latency_ms for item in items if item.latency_ms is not None), default=None),
        error="；".join(dict.fromkeys(item.error for item in items if item.error)) or None,
    )
    capabilities = []
    for index, (page, name, _feature) in enumerate(CAPABILITIES):
        items = [scope.capabilities[index] for scope in scopes.values()]
        capabilities.append(OverviewCapability(
            id=page, name=name, source="aivision", camera_count=sum(item.camera_count for item in items),
            online_camera_count=sum(item.online_camera_count for item in items),
            running=any(item.running for item in items), model_ready=any(item.model_ready for item in items),
        ))
    all_online = bool(scopes) and all(scope.ok for scope in scopes.values())
    camera_online = sum(camera.online for camera in cameras)
    return OverviewStatus(
        departments=departments, department_summaries={department: scope.summary for department, scope in scopes.items()},
        generated_at=time(), ok=all_online,
        level="healthy" if all_online else "degraded" if service.online else "down",
        inventory_complete=not errors, inventory_errors=errors,
        summary=OverviewSummary(
            capability_total=len(capabilities), capability_online=len(capabilities) if service.online else 0,
            capability_running=sum(c.running for c in capabilities), camera_total=len(cameras),
            camera_online=camera_online, camera_offline=len(cameras) - camera_online,
        ), capabilities=capabilities, cameras=cameras, services={"aivision": service},
        guard_behavior_sites=[site for scope in scopes.values() for site in scope.guard_behavior_sites],
    )
