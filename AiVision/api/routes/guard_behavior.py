"""原生保安室资源 API；配置持久化与运行时刷新分开处理。"""
from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import feature_departments
from AiVision.api.deps import get_guard_behavior_runtime, get_guard_behavior_service, get_optional_orchestrator
from AiVision.api.routes.cameras import encode_frame_to_jpeg, frame_size_headers
from AiVision.alarms.records.schema import AlarmEventResponse
from AiVision.alarms.records.queries import event_dict
from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.core.db import get_session
from AiVision.departments.department_registry import require_department
from AiVision.features.guard_behavior.schema import (
    GuardBehaviorAlarmPolicyResponse, GuardBehaviorAlarmPolicyUpdate,
    GuardBehaviorCameraRoiResponse, GuardBehaviorCameraRoiUpdate,
    GuardBehaviorMemberCreate, GuardBehaviorMemberEnabledUpdate,
    GuardBehaviorMemberOrder, GuardBehaviorMemberResponse,
    GuardBehaviorSiteCreate, GuardBehaviorSitePolicyResponse, GuardBehaviorSitePolicyUpdate,
    GuardBehaviorSiteResponse, GuardBehaviorSiteUpdate,
)
from AiVision.features.guard_behavior.state import CameraAvailability, GuardCameraMetrics, SiteRuleDecision


router = APIRouter(prefix="/api/guard-behavior", tags=["guard-behavior"])
ResourceId = Annotated[int, Path(gt=0)]
Service = Annotated[object, Depends(get_guard_behavior_service)]
Runtime = Annotated[object, Depends(get_guard_behavior_runtime)]
Orchestrator = Annotated[object, Depends(get_optional_orchestrator)]
ADMIN = [Depends(require_admin)]


class OkResponse(BaseModel):
    success: bool = True


def _unavailable_rule() -> SiteRuleDecision:
    return SiteRuleDecision("unavailable", "unknown", "未运行或尚无感知数据")


class GuardBehaviorSiteStatusResponse(BaseModel):
    site_id: int
    running: bool
    status: Literal["disabled", "unconfigured", "healthy", "degraded", "unavailable"] = "unavailable"
    camera_states: dict[int, CameraAvailability] = Field(default_factory=dict)
    camera_online: dict[int, bool] = Field(default_factory=dict)
    camera_metrics: dict[int, GuardCameraMetrics] = Field(default_factory=dict)
    absence: SiteRuleDecision = Field(default_factory=_unavailable_rule)
    phone: SiteRuleDecision = Field(default_factory=_unavailable_rule)
    prone: SiteRuleDecision = Field(default_factory=_unavailable_rule)
    vehicle: SiteRuleDecision = Field(default_factory=_unavailable_rule)
    updated_at: float | None = None


def _departments(user: dict) -> tuple[str, ...]:
    return tuple(feature_departments(user, "guard_behavior"))


@contextmanager
def _service_errors():
    try:
        yield
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "不存在" in detail else 400
        if any(word in detail for word in ("已存在", "已属于", "写入冲突", "最多")):
            code = 409
        raise HTTPException(code, detail) from exc


def _site_access(site_id: ResourceId, service: Service, user: dict = Depends(get_current_user)) -> dict:
    with _service_errors():
        site = service.get_site(site_id)
    departments = _departments(user)
    if site["department"] not in departments:
        raise HTTPException(403, "site department permission required")
    return site


Site = Annotated[dict, Depends(_site_access)]


def _reload(orchestrator, site_id: int, camera_ids=()) -> None:
    if orchestrator is not None:
        try:
            orchestrator.refresh_guard_site(site_id, camera_ids)
        except (ValueError, RuntimeError) as exc:
            # 数据已提交，不能把刷新失败伪装成保存失败或自动重复写入。
            raise HTTPException(503, "配置已保存，但运行时刷新失败，请重新读取配置") from exc


@router.get("/sites", response_model=list[GuardBehaviorSiteResponse])
def list_sites(service: Service, user: dict = Depends(get_current_user), department: str | None = None):
    departments = _departments(user)
    if department is not None:
        with _service_errors():
            require_department(department)
        if department not in departments:
            raise HTTPException(403, "department permission required")
        departments = (department,)
    items = [site for value in departments for site in service.list_sites(value)]
    return sorted(items, key=lambda item: (item["sort_order"], item["id"]))


@router.post("/sites", response_model=GuardBehaviorSiteResponse, status_code=201, dependencies=ADMIN)
def create_site(payload: GuardBehaviorSiteCreate, service: Service, orchestrator: Orchestrator):
    with _service_errors():
        site = service.create_site(**payload.model_dump())
    _reload(orchestrator, site["id"])
    return site


@router.get("/sites/{site_id}", response_model=GuardBehaviorSiteResponse)
def get_site(site: Site):
    return site


@router.patch("/sites/{site_id}", response_model=GuardBehaviorSiteResponse, dependencies=ADMIN)
def update_site(site: Site, payload: GuardBehaviorSiteUpdate, service: Service, orchestrator: Orchestrator):
    with _service_errors():
        result = service.update_site(site["id"], payload.model_dump(exclude_unset=True))
    _reload(orchestrator, site["id"])
    return result


@router.delete("/sites/{site_id}", response_model=OkResponse, dependencies=ADMIN)
def delete_site(site: Site, service: Service, orchestrator: Orchestrator):
    with _service_errors():
        camera_ids = [member["camera_id"] for member in service.list_site_cameras(site["id"])]
        service.delete_site(site["id"])
    _reload(orchestrator, site["id"], camera_ids)
    return OkResponse()


@router.get("/sites/{site_id}/cameras", response_model=list[GuardBehaviorMemberResponse])
def list_cameras(site: Site, service: Service):
    with _service_errors():
        return service.list_site_cameras(site["id"])


@router.post("/sites/{site_id}/cameras", response_model=GuardBehaviorMemberResponse,
             status_code=201, dependencies=ADMIN)
def add_camera(site: Site, payload: GuardBehaviorMemberCreate, service: Service, orchestrator: Orchestrator):
    with _service_errors():
        result = service.add_camera(site["id"], payload.camera_id)
    _reload(orchestrator, site["id"])
    return result


@router.put("/sites/{site_id}/cameras/order", response_model=OkResponse, dependencies=ADMIN)
def reorder_cameras(site: Site, payload: GuardBehaviorMemberOrder, service: Service, orchestrator: Orchestrator):
    with _service_errors():
        service.reorder_cameras(site["id"], payload.camera_ids)
    _reload(orchestrator, site["id"])
    return OkResponse()


@router.put("/sites/{site_id}/cameras/{camera_id}/enabled", response_model=GuardBehaviorMemberResponse,
            dependencies=ADMIN)
def set_camera_enabled(site: Site, camera_id: ResourceId, payload: GuardBehaviorMemberEnabledUpdate,
                       service: Service, orchestrator: Orchestrator):
    with _service_errors():
        result = service.set_camera_enabled(site["id"], camera_id, payload.enabled)
    _reload(orchestrator, site["id"])
    return result


@router.delete("/sites/{site_id}/cameras/{camera_id}", response_model=OkResponse, dependencies=ADMIN)
def remove_camera(site: Site, camera_id: ResourceId, service: Service, orchestrator: Orchestrator):
    with _service_errors():
        service.remove_camera(site["id"], camera_id)
    _reload(orchestrator, site["id"], (camera_id,))
    return OkResponse()


@router.get("/sites/{site_id}/policy", response_model=GuardBehaviorSitePolicyResponse)
def get_policy(site: Site, service: Service):
    with _service_errors():
        return service.get_policy(site["id"])


@router.patch("/sites/{site_id}/policy", response_model=GuardBehaviorSitePolicyResponse, dependencies=ADMIN)
def update_policy(site: Site, payload: GuardBehaviorSitePolicyUpdate, service: Service, orchestrator: Orchestrator):
    with _service_errors():
        result = service.update_policy(site["id"], payload.model_dump(exclude_unset=True))
    _reload(orchestrator, site["id"])
    return result


@router.get("/sites/{site_id}/cameras/{camera_id}/roi", response_model=GuardBehaviorCameraRoiResponse)
def get_roi(site: Site, camera_id: ResourceId, service: Service):
    with _service_errors():
        return service.get_camera_roi(site["id"], camera_id)


@router.put("/sites/{site_id}/cameras/{camera_id}/roi", response_model=GuardBehaviorCameraRoiResponse,
            dependencies=ADMIN)
def update_roi(site: Site, camera_id: ResourceId, payload: GuardBehaviorCameraRoiUpdate,
               service: Service, orchestrator: Orchestrator):
    with _service_errors():
        result = service.update_camera_roi(site["id"], camera_id, payload.model_dump())
    _reload(orchestrator, site["id"])
    return result


@router.get("/sites/{site_id}/alarm-policies", response_model=list[GuardBehaviorAlarmPolicyResponse])
def list_alarm_policies(site: Site, service: Service):
    with _service_errors():
        return service.list_alarm_policies(site["id"])


@router.patch("/sites/{site_id}/alarm-policies/{violation_type}",
              response_model=GuardBehaviorAlarmPolicyResponse, dependencies=ADMIN)
def update_alarm_policy(site: Site, violation_type: int, payload: GuardBehaviorAlarmPolicyUpdate,
                        service: Service, orchestrator: Orchestrator):
    with _service_errors():
        result = service.update_alarm_policy(site["id"], violation_type, payload.model_dump(exclude_unset=True))
    _reload(orchestrator, site["id"])
    return result


@router.get("/sites/{site_id}/status", response_model=GuardBehaviorSiteStatusResponse)
def get_status(site: Site, runtime: Runtime):
    running = runtime is not None and runtime.running
    evaluation = runtime.get_site_status(site["id"]) if running else None
    values = asdict(evaluation) if evaluation is not None else {}
    camera_online = runtime.get_camera_online(site["id"]) if runtime is not None else {}
    return GuardBehaviorSiteStatusResponse(site_id=site["id"], running=running,
                                           camera_online=camera_online, **values)


@router.get("/sites/{site_id}/frame.jpg")
def get_frame(site: Site, runtime: Runtime,
              max_width: Annotated[int, Query(ge=1, le=3840)] = 1280,
              quality: Annotated[int, Query(ge=1, le=95)] = 85):
    # 空拼图不是实时画面，至少一路必须已有可用感知数据。
    evaluation = runtime.get_site_status(site["id"]) if runtime is not None and runtime.running else None
    if evaluation is None or not any(value == CameraAvailability.READY for value in evaluation.camera_states.values()):
        raise HTTPException(503, "保安室画面不可用：尚无实时感知数据")
    frame = runtime.get_site_frame(site["id"])
    if frame is None:
        raise HTTPException(503, "保安室画面不可用")
    return Response(encode_frame_to_jpeg(frame, quality=quality, max_width=max_width), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", **frame_size_headers(frame, max_width=max_width)})


@router.get("/sites/{site_id}/latest-alarm", response_model=AlarmEventResponse | None)
def get_latest_alarm(site: Site):
    """先按保安室授权，再查询该主体最新的持久化报警，不受其他保安室报警量影响。"""
    session = get_session()
    try:
        row = session.query(AiAlarmEvent).filter(
            AiAlarmEvent.department == site["department"],
            AiAlarmEvent.feature_name == "guard_behavior",
            AiAlarmEvent.subject_type == "guard_behavior_site",
            AiAlarmEvent.subject_id == str(site["id"]),
        ).order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()).first()
        return event_dict(row) if row is not None else None
    finally:
        session.close()
