"""按登录用户授权范围聚合平台总览，物流成员只补充物理摄像头的能力信息。"""
from collections.abc import Callable
from time import time
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, Field


CAPABILITIES = (
    ("security-vlm", "安检流程规范检测", "security_vlm", None),
    ("guard-behavior", "保安行为规范检测", "guard_room", None),
    ("intrusion-detection", "区域入侵检测", "aivision", "blocks"),
    ("door-detection", "大门开关异常检测", "aivision", "detect_door"),
    ("face-detection", "人脸逗留检测", "aivision", "detect_face"),
    ("face-recognition", "人脸身份识别", "aivision", "recognize_face"),
    ("human-detection", "人员违规逗留检测", "aivision", "detect_human"),
    ("logistics-single-person", "物流通道单人检测", "aivision", "detect_logistics_single_person"),
    ("phone-detection", "手机使用检测", "aivision", "detect_phone"),
)
FEATURE_PAGES = {feature: page for page, _name, _source, feature in CAPABILITIES if feature}
UpstreamResult = tuple[bool, dict | list | None, float | None, str | None]
ReadMany = Callable[[dict[str, tuple[str, str, Request | None]]], dict[str, UpstreamResult]]


class OverviewCamera(BaseModel):
    key: str
    source: Literal["aivision", "guard_room", "security_vlm"]
    camera_id: int | str
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
    source: str
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
    guard_room_sites: list[dict]


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
    guard_sites = payload("guard_sites", dict)
    vlm_state = payload("vlm_state", dict)
    sites = [site for site in guard_sites.get("items", []) if site.get("department") == department]
    services = {}
    for source, key in (("aivision", "ai_status"), ("guard_room", "guard_sites"), ("security_vlm", "vlm_state")):
        ok, _value, latency, error = upstream[key]
        services[source] = OverviewServiceStatus(online=ok, latency_ms=latency, error=errors.get(key) or error)
    services["aivision"].model_ready = bool(ai_status.get("running_models"))
    services["security_vlm"].model_ready = bool(vlm_state.get("vlm", {}).get("ok"))
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
        active = [FEATURE_PAGES[name] for name in features if physical_online and name in running_features]
        if enabled and member.get("online") and "logistics-single-person" not in active:
            active.append("logistics-single-person")
        cameras.append(OverviewCamera(
            key=f"aivision:{camera['camera_id']}", source="aivision", camera_id=camera["camera_id"],
            name=camera["name"], identifier=camera["shm_name"], department=department,
            enabled=enabled, online=physical_online or (enabled and bool(member.get("online"))),
            capabilities=capabilities, running_capabilities=active,
            logistics_memberships=links, aivision_camera=camera,
        ))
    for site in sites:
        ok, state, _latency, error = site_results[str(site["id"])]
        state = state if ok and isinstance(state, dict) else {}
        if not ok:
            errors[f"guard_site:{site['id']}"] = error or "保安室状态读取失败"
            services["guard_room"].error = "部分保安室状态读取失败"
        running = bool(state.get("running")) and not state.get("error")
        services["guard_room"].model_ready |= running
        for camera in site.get("cameras", []):
            enabled = bool(site.get("enabled")) and bool(camera.get("enabled"))
            online = enabled and running
            cameras.append(OverviewCamera(
                key=f"guard_room:{site['id']}:{camera['id']}", source="guard_room", camera_id=camera["id"],
                name=camera["name"], identifier=f"保安室：{site['name']}", site_id=site["id"],
                department=department, enabled=enabled, online=online,
                capabilities=["guard-behavior"], running_capabilities=["guard-behavior"] if online else [],
            ))
    for camera in vlm_state.get("cameras", []):
        # 安检摄像头来自当前事业部工作区，拒绝上游显式返回的其他事业部数据。
        if camera.get("department", department) != department:
            continue
        online = bool(camera.get("running"))
        cameras.append(OverviewCamera(
            key=f"security_vlm:{department}:{camera['camera_id']}", source="security_vlm",
            camera_id=camera["camera_id"], name=camera["name"], identifier=camera["camera_id"],
            department=department, enabled=bool(camera.get("desired_running", online)), online=online,
            capabilities=["security-vlm"], running_capabilities=["security-vlm"] if online else [],
        ))
    capabilities = []
    for page, name, source, feature in CAPABILITIES:
        members = [camera for camera in cameras if page in camera.capabilities]
        online_count = sum(page in camera.running_capabilities for camera in members)
        model_ready = services[source].model_ready
        if feature:
            metadata = feature_meta.get(feature)
            model_ready = metadata is not None and set(metadata["required_models"]).issubset(ai_status.get("running_models", []))
        capabilities.append(OverviewCapability(
            id=page, name=name, source=source, camera_count=len(members),
            online_camera_count=online_count, running=online_count > 0,
            model_ready=model_ready,
        ))
    for source, service in services.items():
        service.camera_count = sum(camera.source == source for camera in cameras)
        service.online_camera_count = sum(camera.source == source and camera.online for camera in cameras)
        service.running = any(capability.source == source and capability.running for capability in capabilities)
    all_online = all(service.online for service in services.values()) and not errors
    camera_online = sum(camera.online for camera in cameras)
    return _OverviewScope(
        generated_at=time(), ok=all_online,
        level="healthy" if all_online else "degraded" if any(s.online for s in services.values()) else "down",
        inventory_complete=not errors, inventory_errors=errors,
        summary=OverviewSummary(
            capability_total=len(capabilities), capability_online=sum(services[c.source].online for c in capabilities),
            capability_running=sum(c.running for c in capabilities), camera_total=len(cameras),
            camera_online=camera_online, camera_offline=len(cameras) - camera_online,
        ), capabilities=capabilities, cameras=cameras, services=services,
        guard_room_sites=[{"id": site["id"], "name": site["name"], "department": department} for site in sites],
    )


def build_overview(request: Request, departments: list[str], aivision_url: str,
                   guard_room_url: str, security_vlm_url: str, read_many: ReadMany) -> OverviewStatus:
    # 公共状态只读取一次，各事业部清单并发获取，避免随授权范围串行增加等待时间。
    calls = {
        "ai_status": (aivision_url, "/api/runtime/status", request),
        "features": (aivision_url, "/api/features", request),
    } if departments else {}
    for department in departments:
        calls.update({
            f"{department}:ai_cameras": (aivision_url, f"/api/cameras?department={department}", request),
            f"{department}:logistics": (aivision_url, f"/api/logistics-channels/inventory?department={department}", request),
            f"{department}:guard_sites": (guard_room_url, f"/api/sites?department={department}", request),
            f"{department}:vlm_state": (security_vlm_url, f"/api/departments/{department}/health", request),
        })
    upstream = read_many(calls) if calls else {}
    site_calls = {}
    for department in departments:
        ok, payload, _latency, _error = upstream[f"{department}:guard_sites"]
        if ok and isinstance(payload, dict):
            for site in payload.get("items", []):
                if site.get("department") == department:
                    site_calls[str(site["id"])] = (
                        guard_room_url, f"/api/sites/{site['id']}/status?department={department}", request,
                    )
    site_results = read_many(site_calls) if site_calls else {}
    scopes = {}
    for department in departments:
        scope_upstream = {key: upstream[key] for key in ("ai_status", "features")}
        scope_upstream.update({
            key: upstream[f"{department}:{key}"]
            for key in ("ai_cameras", "logistics", "guard_sites", "vlm_state")
        })
        scopes[department] = _build_department_overview(department, scope_upstream, site_results)

    cameras = [camera for scope in scopes.values() for camera in scope.cameras]
    errors = {f"{department}:{key}": error for department, scope in scopes.items()
              for key, error in scope.inventory_errors.items()}
    services = {}
    for source in ("aivision", "guard_room", "security_vlm"):
        items = [scope.services[source] for scope in scopes.values()]
        services[source] = OverviewServiceStatus(
            online=any(item.online for item in items), running=any(item.running for item in items),
            model_ready=any(item.model_ready for item in items),
            camera_count=sum(item.camera_count for item in items),
            online_camera_count=sum(item.online_camera_count for item in items),
            latency_ms=max((item.latency_ms for item in items if item.latency_ms is not None), default=None),
            error="；".join(dict.fromkeys(item.error for item in items if item.error)) or None,
        )
    capabilities = []
    for index, (page, name, source, _feature) in enumerate(CAPABILITIES):
        items = [scope.capabilities[index] for scope in scopes.values()]
        capabilities.append(OverviewCapability(
            id=page, name=name, source=source, camera_count=sum(item.camera_count for item in items),
            online_camera_count=sum(item.online_camera_count for item in items),
            running=any(item.running for item in items), model_ready=any(item.model_ready for item in items),
        ))
    all_online = bool(scopes) and all(scope.ok for scope in scopes.values())
    camera_online = sum(camera.online for camera in cameras)
    return OverviewStatus(
        departments=departments, department_summaries={department: scope.summary for department, scope in scopes.items()},
        generated_at=time(), ok=all_online,
        level="healthy" if all_online else "degraded" if any(s.online for s in services.values()) else "down",
        inventory_complete=not errors, inventory_errors=errors,
        summary=OverviewSummary(
            capability_total=len(capabilities), capability_online=sum(services[c.source].online for c in capabilities),
            capability_running=sum(c.running for c in capabilities), camera_total=len(cameras),
            camera_online=camera_online, camera_offline=len(cameras) - camera_online,
        ), capabilities=capabilities, cameras=cameras, services=services,
        guard_room_sites=[site for scope in scopes.values() for site in scope.guard_room_sites],
    )
