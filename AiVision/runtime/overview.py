"""按账号可访问事业部与功能生成平台总览，不额外调用内部 HTTP 服务。

从摄像头配置、通道/保安室关系和运行快照合并物理设备，避免同摄像头多能力重复计数。
在线、模型就绪与正在检测分别统计，尤其 AGV 待机在线不计为正在执行请求。
"""
from time import time
from typing import Literal

from pydantic import BaseModel, Field

from AiVision.features.registry import all_specs
from AiVision.features.guard_behavior.state import CameraAvailability
from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES


CAPABILITIES = (
    ("visual-language-detection", "指令驱动智慧安防", "visual_language_detection"),
    ("security-vlm", "安检流程规范检测", "security_inspection"),
    ("guard-behavior", "保安行为规范检测", "guard_behavior"),
    ("intrusion-detection", "区域入侵检测", "blocks"),
    ("door-detection", "大门开关异常检测", "detect_door"),
    ("face-detection", "人脸逗留检测", "detect_face"),
    ("face-recognition", "人脸身份识别", "recognize_face"),
    ("human-detection", "人员违规逗留检测", "detect_human"),
    ("logistics-single-person", "物流通道单人检测", "detect_logistics_single_person"),
    ("phone-detection", "手机使用检测", "detect_phone"),
    ("agv-person-check", "AGV无人运货检测", "agv_person_check"),
)
FEATURE_PAGES = {feature: page for page, _name, feature in CAPABILITIES}


class OverviewCamera(BaseModel):
    """一个物理摄像头的总览项，分别列出配置能力、运行能力与通道/保安室关联。"""
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
    """一种可见功能的设备数量、运行状态及模型就绪摘要。"""
    id: str
    name: str
    camera_count: int
    online_camera_count: int
    running: bool
    model_ready: bool


class OverviewServiceStatus(BaseModel):
    """HTTP 可访问与检测引擎运行状态的汇总，二者不要求同时为真。"""
    online: bool
    running: bool = False
    error: str | None = None
    camera_count: int = 0
    online_camera_count: int = 0
    model_ready: bool = False


class OverviewSummary(BaseModel):
    """能力和物理摄像头的汇总计数，供平台与各事业部共用。"""
    capability_total: int
    capability_online: int
    capability_running: int
    camera_total: int
    camera_online: int
    camera_offline: int


class OverviewStatus(BaseModel):
    """带生成时刻、资源完整性、服务状态和分事业部计数的完整总览响应。"""
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


def build_overview(departments, cameras, logistics_service, guard_service, orchestrator, feature_access):
    """从已授权资源和本进程运行状态生成总览快照，不启动摄像头或模型。

    调用方提供事业部、摄像头、通道/保安室服务、可选编排器及功能分配。
    安检计入外部服务健康，AGV 仅将尚未完成的请求计为检测中；返回 OverviewStatus。
    """
    status = orchestrator.runtime_status() if orchestrator is not None else {}
    running_cameras = set(status.get("running_cameras", []))
    running_features = set(status.get("running_consumers", []))
    running_models = set(status.get("running_models", []))
    agv = orchestrator.consumers.get("agv_person_check") if orchestrator is not None else None
    detecting_agv_cameras = agv.service.detecting_camera_ids() if agv is not None else set()
    inspection = orchestrator.consumers.get("security_inspection") if orchestrator is not None else None
    health = inspection.vlm_runtime.health_status() if inspection is not None else None
    vlm_ready = bool(inspection is not None and inspection.running and health.reachable is True
                     and health.circuit_state != "open")
    inventory = logistics_service.camera_inventory_status(
        [department for department in departments
         if "detect_logistics_single_person" in feature_access[department]], orchestrator,
    )
    memberships = {item["camera_id"]: item for item in inventory}
    physical = {}
    for camera in cameras:
        features = [name for name, enabled in camera["functions"].items()
                    if enabled and name in FEATURE_PAGES and name in feature_access[camera["department"]]]
        member = memberships.get(camera["camera_id"], {})
        links = member.get("memberships", [])
        enabled = camera["enabled"]
        online = enabled and camera["shm_name"] in running_cameras
        capabilities = [FEATURE_PAGES[name] for name in features if name not in LOGISTICS_FEATURES and name != "guard_behavior"]
        if links:
            capabilities.append("logistics-single-person")
        active = [FEATURE_PAGES[name] for name in features
                  if online and name in running_features and name not in LOGISTICS_FEATURES and name != "guard_behavior"
                  and (name != "security_inspection" or vlm_ready)
                  and (name != "agv_person_check" or camera["camera_id"] in detecting_agv_cameras)]
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
        if "guard_behavior" not in feature_access[department]:
            continue
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
    visible_features = {feature for features in feature_access.values() for feature in features}
    for page, name, feature in CAPABILITIES:
        if feature not in visible_features:
            continue
        members = [camera for camera in physical.values() if page in camera.capabilities]
        active = sum(page in camera.running_capabilities for camera in members)
        # AGV 待机时画面仍在线；只有未完成的检测请求计入“正在检测”。
        online_count = sum(camera.online for camera in members) if feature == "agv_person_check" else active
        ready = set(specs[feature].required_models).issubset(running_models)
        if feature == "security_inspection":
            ready = ready and vlm_ready
        capabilities.append(OverviewCapability(
            id=page, name=name, camera_count=len(members), online_camera_count=online_count,
            running=bool(active), model_ready=ready,
        ))

    def summary(items, features):
        """对已经筛选的设备与功能集合计数，以物理摄像头和运行页面集合去重。"""
        online_count = sum(camera.online for camera in items)
        active_pages = {page for camera in items for page in camera.running_capabilities}
        return OverviewSummary(
            capability_total=len(features), capability_online=len(features),
            capability_running=len(active_pages), camera_total=len(items),
            camera_online=online_count, camera_offline=len(items) - online_count,
        )

    cameras = list(physical.values())
    totals = summary(cameras, visible_features)
    ready = bool(status.get("started"))
    return OverviewStatus(
        generated_at=time(), ok=ready and not errors, level="healthy" if ready and not errors else "degraded",
        inventory_complete=not errors, inventory_errors=errors, summary=totals, capabilities=capabilities,
        cameras=cameras, service=OverviewServiceStatus(
            online=True, running=ready, error=None if ready else "检测引擎尚未就绪",
            camera_count=totals.camera_total, online_camera_count=totals.camera_online,
            model_ready=bool(running_models),
        ), guard_behavior_sites=sites, departments=departments,
        department_summaries={department: summary([camera for camera in cameras if camera.department == department],
                                                  feature_access[department])
                              for department in departments},
    )
