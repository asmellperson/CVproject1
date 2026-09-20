"""总览从本进程配置服务与运行快照生成，摄像头按物理设备计数。"""
from time import time
from typing import Literal

from pydantic import BaseModel, Field

from AiVision.features.registry import all_specs
from AiVision.features.guard_behavior.state import CameraAvailability
from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES


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


class OverviewCamera(BaseModel):
    key: str
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
    camera_count: int
    online_camera_count: int
    running: bool
    model_ready: bool


class OverviewServiceStatus(BaseModel):
    online: bool
    running: bool = False
    error: str | None = None
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


class OverviewStatus(BaseModel):
    generated_at: float
    ok: bool
    level: Literal["healthy", "degraded", "down"]
    inventory_complete: bool
    inventory_errors: dict[str, str]
    summary: OverviewSummary
    capabilities: list[OverviewCapability]
    cameras: list[OverviewCamera]
    service: OverviewServiceStatus
    guard_behavior_sites: list[dict]

    departments: list[str]
    department_summaries: dict[str, OverviewSummary]


def build_overview(departments, cameras, logistics_service, guard_service, orchestrator):
    status = orchestrator.runtime_status() if orchestrator is not None else {}
    running_cameras = set(status.get("running_cameras", []))
    running_features = set(status.get("running_consumers", []))
    running_models = set(status.get("running_models", []))
    inspection = orchestrator.consumers.get("security_inspection") if orchestrator is not None else None
    health = inspection.vlm_runtime.health_status() if inspection is not None else None
    vlm_ready = bool(inspection is not None and inspection.running and health.reachable is True
                     and health.circuit_state != "open")
    inventory = logistics_service.camera_inventory_status(departments, orchestrator)
    memberships = {item["camera_id"]: item for item in inventory}
    physical = {}
    for camera in cameras:
        features = [name for name, enabled in camera["functions"].items() if enabled and name in FEATURE_PAGES]
        member = memberships.get(camera["camera_id"], {})
        links = member.get("memberships", [])
        enabled = camera["enabled"]
        online = enabled and camera["shm_name"] in running_cameras
        capabilities = [FEATURE_PAGES[name] for name in features if name not in LOGISTICS_FEATURES and name != "guard_behavior"]
        if links:
            capabilities.append("logistics-single-person")
        active = [FEATURE_PAGES[name] for name in features
                  if online and name in running_features and name not in LOGISTICS_FEATURES and name != "guard_behavior"
                  and (name != "security_inspection" or vlm_ready)]
        if enabled and member.get("online"):
            active.append("logistics-single-person")
        physical[camera["camera_id"]] = OverviewCamera(
            key=str(camera["camera_id"]), camera_id=camera["camera_id"], name=camera["name"],
            department=camera["department"], identifier=camera["shm_name"], enabled=enabled,
            online=online, capabilities=capabilities, running_capabilities=active,
            logistics_memberships=links, aivision_camera=camera,
        )
    guard_runtime = orchestrator.guard_behavior_runtime if orchestrator is not None else None
    sites = []
    errors = {}
    for department in departments:
        for site in guard_service.list_sites(department):
            sites.append({"id": site["id"], "name": site["name"], "department": department})
            evaluation = guard_runtime.get_site_status(site["id"]) if guard_runtime is not None and guard_runtime.running else None
            for member in guard_service.list_site_cameras(site["id"]):
                camera = physical.get(member["camera_id"])
                if camera is None:
                    errors[f"guard_camera:{member['camera_id']}"] = "保安室成员不在物理摄像头清单中"
                    continue
                camera.site_id = site["id"]
                camera.capabilities.append("guard-behavior")
                if (camera.online and site["enabled"] and member["member_enabled"] and evaluation is not None
                        and evaluation.camera_states.get(camera.camera_id) == CameraAvailability.READY):
                    camera.running_capabilities.append("guard-behavior")
    specs = all_specs()
    capabilities = []
    for page, name, feature in CAPABILITIES:
        members = [camera for camera in physical.values() if page in camera.capabilities]
        active = sum(page in camera.running_capabilities for camera in members)
        ready = set(specs[feature].required_models).issubset(running_models)
        if feature == "security_inspection":
            ready = ready and vlm_ready
        capabilities.append(OverviewCapability(
            id=page, name=name, camera_count=len(members), online_camera_count=active,
            running=bool(active), model_ready=ready,
        ))

    def summary(items):
        online_count = sum(camera.online for camera in items)
        active_pages = {page for camera in items for page in camera.running_capabilities}
        return OverviewSummary(
            capability_total=len(CAPABILITIES), capability_online=len(CAPABILITIES),
            capability_running=len(active_pages), camera_total=len(items),
            camera_online=online_count, camera_offline=len(items) - online_count,
        )

    cameras = list(physical.values())
    totals = summary(cameras)
    ready = bool(status.get("started"))
    return OverviewStatus(
        generated_at=time(), ok=ready and not errors, level="healthy" if ready and not errors else "degraded",
        inventory_complete=not errors, inventory_errors=errors, summary=totals, capabilities=capabilities,
        cameras=cameras, service=OverviewServiceStatus(
            online=True, running=ready, error=None if ready else "检测引擎尚未就绪",
            camera_count=totals.camera_total, online_camera_count=totals.camera_online,
            model_ready=bool(running_models),
        ), guard_behavior_sites=sites, departments=departments,
        department_summaries={department: summary([camera for camera in cameras if camera.department == department])
                              for department in departments},
    )
