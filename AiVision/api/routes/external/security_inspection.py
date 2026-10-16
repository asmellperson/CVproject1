"""外部安检展示及逐摄配置入口，复用平台业务服务和响应字段。"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, model_validator

from AiVision.api.deps import (
    get_camera_config_manager,
    get_current_orchestrator,
    get_department_service,
    get_horn_service,
    get_inspection_consumer,
    get_inspection_service,
)
from AiVision.api.routes.cameras import build_camera_frame_response
from AiVision.api.routes.security_inspection import build_inspection_image_response
from AiVision.departments.department_registry import DEPARTMENT_SPECS
from .common import CameraResponse, DepartmentResponse, require_feature_department, scoped_camera as find_scoped_camera
from AiVision.features._shared.config_manager import FeatureCameraScopeConflict, feature_config_manager
from AiVision.features.registry import get_spec
from AiVision.features.security_inspection.schema import (
    HistoryResponse,
    InspectionConfig,
    StatusResponse,
)
from AiVision.features.security_inspection.service import InspectionService
from auth.external import inspection_reader, inspection_writer
from auth.external_schema import ExternalClientInfo, INSPECTION_FEATURE

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/security-inspection", tags=["external-security-inspection"])


class ConfigCameraResponse(BaseModel):
    id: int
    name: str
    shm_name: str
    enable: bool


class ConfigResponse(BaseModel):
    camera: ConfigCameraResponse
    feature: Literal["security_inspection"] = INSPECTION_FEATURE
    config: InspectionConfig


class ConfigWrite(InspectionConfig):
    """完整提交 GET 返回的 config，缺字段时拒绝默认值覆盖已有配置。"""

    @model_validator(mode="after")
    def require_complete_config(self):
        def check(model: BaseModel, path: str):
            missing = set(type(model).model_fields) - model.model_fields_set
            if missing:
                raise ValueError(f"请提交完整配置，{path} 缺少字段：{', '.join(sorted(missing))}")
            for name in type(model).model_fields:
                value = getattr(model, name)
                if isinstance(value, BaseModel):
                    check(value, f"{path}.{name}")

        check(self, "config")
        return self


class ConfigSchemaResponse(BaseModel):
    feature: Literal["security_inspection"] = INSPECTION_FEATURE
    default_config: InspectionConfig
    config_schema: dict


class HornChoiceResponse(BaseModel):
    """报警配置只需要设备选项，不暴露设备地址、凭据和控制接口。"""

    id: int
    name: str
    enable: bool


def get_config_manager():
    return feature_config_manager


def department_access(
    department: str,
    client: ExternalClientInfo = Depends(inspection_reader),
    service=Depends(get_department_service),
) -> str:
    """同时检查凭证授权与平台当前功能分配。"""
    return require_feature_department(department, client, INSPECTION_FEATURE, service)


def scoped_camera(
    shm_name: str,
    department: str = Depends(department_access),
    manager=Depends(get_camera_config_manager),
) -> dict:
    """以真实资源归属授权，外部接口只接受 shm_name，避免别名歧义。"""
    return find_scoped_camera(manager, shm_name, department)


@router.get("/departments", response_model=list[DepartmentResponse])
def departments(client: ExternalClientInfo = Depends(inspection_reader), service=Depends(get_department_service)):
    """返回此凭证当前可访问的安检事业部。"""
    access = service.feature_access()
    return [
        DepartmentResponse(name=name, display_name=spec.display_name)
        for name, spec in DEPARTMENT_SPECS.items()
        if name in client.departments and INSPECTION_FEATURE in access.get(name, [])
    ]


@router.get("/cameras", response_model=list[CameraResponse])
def cameras(
    department: str = Depends(department_access), enabled_only: bool = False, manager=Depends(get_camera_config_manager)
):
    """配置页可选择未开启安检的现有摄像头，监控页可只取已启用项。"""
    result = []
    for camera in manager.list_cameras(department=department):
        if camera["department"] != department:
            continue
        enabled = bool(camera["functions"].get(INSPECTION_FEATURE, False))
        if enabled_only and not (camera["enabled"] and enabled):
            continue
        order = camera["feature_sort_orders"].get(INSPECTION_FEATURE, camera["sort_order"])
        result.append(
            CameraResponse.model_validate(
                {
                    **camera,
                    "functions": {INSPECTION_FEATURE: enabled},
                    "feature_sort_orders": {INSPECTION_FEATURE: order},
                }
            )
        )
    return sorted(result, key=lambda camera: (camera.feature_sort_orders[INSPECTION_FEATURE], camera.camera_id))


@router.get("/status", response_model=StatusResponse)
def status(department: str = Depends(department_access), consumer=Depends(get_inspection_consumer)):
    return InspectionService.runtime_status(department, consumer)


@router.get("/history", response_model=HistoryResponse)
def history(
    department: str = Depends(department_access),
    camera_id: int | None = Query(None, gt=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service=Depends(get_inspection_service),
):
    """只查询获准事业部的历史；统计覆盖该范围全部记录，不受分页影响。"""
    return service.history(department, camera_id=camera_id, limit=limit, offset=offset)


@router.get("/history/{session_id}/image.jpg", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}}})
def history_image(
    session_id: str,
    department: str = Depends(department_access),
    service=Depends(get_inspection_service),
):
    """使用外部只读凭证获取会话证据，保留事业部隔离。"""
    return build_inspection_image_response(service, department, session_id)


@router.get("/cameras/{shm_name}/frame.jpg", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def frame(
    camera: dict = Depends(scoped_camera),
    annotated: bool = True,
    quality: int = Query(85, ge=1, le=100),
    max_width: int | None = Query(None, ge=1, le=4096),
    max_height: int | None = Query(None, ge=1, le=4096),
    orchestrator=Depends(get_current_orchestrator),
):
    """标注帧用于监控，annotated=false 的原始帧用于绘制归一化 ROI。"""
    return build_camera_frame_response(
        key=camera["shm_name"],
        feature=INSPECTION_FEATURE if annotated else None,
        quality=quality,
        max_width=max_width,
        max_height=max_height,
        orchestrator=orchestrator,
    )


@router.get("/cameras/{shm_name}/config", response_model=ConfigResponse)
def get_config(camera: dict = Depends(scoped_camera), manager=Depends(get_config_manager)):
    result = manager.get_config(get_spec(INSPECTION_FEATURE), camera["camera_id"])
    if result is None:
        raise HTTPException(404, "camera not found")
    return result


@router.put("/cameras/{shm_name}/config", response_model=ConfigResponse)
def save_config(
    payload: ConfigWrite,
    client: ExternalClientInfo = Depends(inspection_writer),
    camera: dict = Depends(scoped_camera),
    manager=Depends(get_config_manager),
):
    """复用正式配置事务和热更新；锁定后的归属检查防止跨部写入。"""
    try:
        result = manager.save_config(
            get_spec(INSPECTION_FEATURE),
            camera["camera_id"],
            payload.model_dump(),
            expected_department=camera["department"],
        )
    except FeatureCameraScopeConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "camera not found")
    logger.info(
        "外部安检配置已保存 client_id=%s department=%s camera_id=%s",
        client.id,
        camera["department"],
        camera["camera_id"],
    )
    return result


@router.get("/config-schema", response_model=ConfigSchemaResponse)
def config_schema(_client: ExternalClientInfo = Depends(inspection_reader)):
    return ConfigSchemaResponse(default_config=InspectionConfig(), config_schema=InspectionConfig.model_json_schema())


@router.get("/horns", response_model=list[HornChoiceResponse], dependencies=[Depends(inspection_writer)])
def horn_choices(department: str = Depends(department_access), service=Depends(get_horn_service)):
    """按已授权事业部返回喇叭选项，避免外部配置绑定其他事业部设备。"""
    return service.list_horns(department=department)
