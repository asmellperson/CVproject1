"""
api/routes/features.py
通用功能配置 API

1 个路由处理所有功能。前端访问:
    GET  /api/features                         → 列出所有 feature 元数据
    GET  /api/features/{feature}               → 单个 feature 元数据
    GET  /api/features/{feature}/configs/{cam} → 读单个摄像头的配置
    PUT  /api/features/{feature}/configs/{cam} → 写单个摄像头的配置
    GET  /api/features/{feature}/cameras/{cam}/status → 读功能运行状态
"""
from __future__ import annotations
from typing import Annotated                                # 给一个普通Python类型额外附加FastAPI参数说明
from fastapi import APIRouter, Depends, HTTPException, Path # Path：定义URL路径参数
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import feature_departments, require_feature_access
from AiVision.api.routes.cameras import get_camera_for_user
from AiVision.api.deps import get_camera_config_manager, get_current_orchestrator
from AiVision.alarms.types import VIOLATION_TYPE_META

from AiVision.features.registry import all_specs, get_spec            # 系统当前已经注册过的所有检测功能以及查询某个具体的功能
from AiVision.features._shared.spec import FeatureSpec
from AiVision.features._shared.config_manager import FeatureCameraOrderConflict, feature_config_manager
from AiVision.cameras.config_manager import camera_config_manager           # 摄像头配置服务

class FeatureAlarmTypeResponse(BaseModel):
    """功能声明的正式报警元数据。"""
    violation_type: int
    event_type: str
    label: str


class FeatureMetaResponse(BaseModel):
    """单个检测功能和前端交互的字段"""
    name: str
    display_name: str
    required_models: list[str]
    alarm_types: list[FeatureAlarmTypeResponse]
    default_config: dict
    config_schema: dict                     # 这个功能有哪些可配置参数

class FeaturesListResponse(BaseModel):
    """所有功能"""
    features: list[FeatureMetaResponse]

class FeatureConfigResponse(BaseModel):
    """单个摄像头的单个功能配置"""
    camera: dict
    feature: str
    config: dict

class FeatureCameraOrderRequest(BaseModel):
    """提交当前功能已启用摄像头的完整顺序。"""

    model_config = ConfigDict(extra="forbid")
    department: str
    camera_ids: list[Annotated[int, Field(strict=True, gt=0)]]


class FeatureCameraCreateRequest(BaseModel):
    """功能页面新增摄像头"""

    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    shm_name: str | None = Field(None, min_length=1)
    fps: int = Field(5, gt=0)
    enabled: bool = True                            # 新增加的摄像头直接开启当前功能
    department: str = Field(..., min_length=1)

def _require_spec(feature: str) -> FeatureSpec:
    """找功能并保证他存在"""
    spec = get_spec(feature)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown feature: {feature}")
    return spec


def get_feature_status(
    feature: str,
    key: str,
    user: dict = Depends(get_current_user),
    camera_config_manager=Depends(get_camera_config_manager),
    orchestrator=Depends(get_current_orchestrator),
):
    """读取指定摄像头的功能运行状态。"""
    _require_spec(feature)
    camera = get_camera_for_user(camera_config_manager, key, user)
    require_feature_access(user, feature, camera["department"])
    return orchestrator.get_feature_monitor_status(key, feature)          # 去调度器查询功能的运行状态

def create_features_router(
    feature_config_manager,
    camera_config_manager=None,
) -> APIRouter:
    """一次性创建整套/api/features API,并把所有检测功能都挂在这一套路由下面"""
    # 没有传camera_config_manager,就使用系统默认的全局实例
    if camera_config_manager is None:
        from AiVision.cameras.config_manager import camera_config_manager as default_camera_config_manager
        camera_config_manager = default_camera_config_manager

    router = APIRouter(prefix="/api/features", tags=["features"])
    # 注册运行状态接口
    router.add_api_route(
        "/{feature}/cameras/{key}/status",
        get_feature_status,
        methods=["GET"],
    )

    def _spec_to_meta(spec: FeatureSpec) -> FeatureMetaResponse:
        """将 FeatureSpec 对象转换为 API 响应模型，集中处理 JSON Schema 序列化。"""
        return FeatureMetaResponse(
            name=spec.name,
            display_name=spec.display_name,
            required_models=list(spec.required_models),
            alarm_types=[
                FeatureAlarmTypeResponse(violation_type=alarm_type, **VIOLATION_TYPE_META[alarm_type])
                for alarm_type in spec.alarm_types
            ],
            config_schema=spec.config_schema.model_json_schema(),
            default_config=spec.config_schema().model_dump(),
        )

    @router.get("", response_model=FeaturesListResponse)
    def list_features(user: dict = Depends(get_current_user)):
        """仅返回账号至少在一个事业部可访问的功能。"""
        return FeaturesListResponse(
            features=[_spec_to_meta(s) for s in all_specs().values() if feature_departments(user, s.name)]
        )

    @router.get("/{feature}", response_model=FeatureMetaResponse)
    def get_feature_meta(feature: Annotated[str, Path()], user: dict = Depends(get_current_user)):
        """返回单个功能的元数据，包含 JSON Schema 供前端按需渲染表单。"""
        spec = _require_spec(feature)
        require_feature_access(user, feature)
        return _spec_to_meta(spec)

    @router.post("/{feature}/cameras")
    def create_feature_camera(
        feature: str,
        payload: FeatureCameraCreateRequest,
        _user: dict = Depends(require_admin),
    ) -> dict:
        """在具体功能的检测页面新增摄像头"""
        spec = _require_spec(feature)
        try:
            # create_camera_for_feature:创建摄像头并且启用当前的功能
            return camera_config_manager.create_camera_for_feature(
                spec.name,
                payload.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/{feature}/cameras/order", status_code=204)
    def reorder_feature_cameras(
        feature: str,
        payload: FeatureCameraOrderRequest,
        _user: dict = Depends(require_admin),
    ) -> None:
        """保存当前事业部内指定功能的摄像头顺序。"""
        spec = _require_spec(feature)
        try:
            feature_config_manager.reorder_cameras(spec, payload.department, payload.camera_ids)
        except FeatureCameraOrderConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get(
        "/{feature}/configs/{shm_name}",
        response_model=FeatureConfigResponse,
    )
    def get_feature_config(
        feature: str,
        shm_name: str,
        user: dict = Depends(get_current_user),
    ):
        """
        读取指定摄像头的功能配置。

        shm_name 为摄像头共享内存标识（即 ai_camera_config.shm_name），
        摄像头或对应功能配置不存在时返回 404。
        """
        spec = _require_spec(feature)
        from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES
        if feature in LOGISTICS_FEATURES:
            raise HTTPException(status_code=404, detail="物流摄像头配置只通过通道 ROI 接口访问")
        # 读取指定摄像头的功能配置
        camera = get_camera_for_user(camera_config_manager, shm_name, user)
        require_feature_access(user, feature, camera["department"])
        result = feature_config_manager.get_config(spec, shm_name)
        if result is None:
            raise HTTPException(status_code=404, detail="camera or config not found")
        return FeatureConfigResponse(**result)
    
    @router.put(
        "/{feature}/configs/{shm_name}",
        response_model=FeatureConfigResponse,
    )
    def save_feature_config(
        feature: str,
        shm_name: str,
        payload: dict,
        _user: dict = Depends(require_admin),  # 写操作需管理员权限
    ):
        """
        保存指定摄像头的功能配置（需管理员权限）。

        校验流程:
            1. 通过 spec.config_schema（Pydantic 模型）校验 payload 结构与类型。
            2. 校验通过后调用 feature_config_manager.save_config() 持久化到数据库。
            3. 返回保存后的最新配置，供前端直接刷新本地状态。

        校验失败返回 400，摄像头不存在返回 404。
        """
        spec = _require_spec(feature)
        from AiVision.features.logistics_channel.constants import LOGISTICS_FEATURES
        if feature in LOGISTICS_FEATURES:
            raise HTTPException(status_code=404, detail="物流摄像头配置只通过通道 ROI 接口访问")
        try:
            # 用各功能自定义的 Pydantic schema 校验入参，类型错误或缺字段时抛异常
            validated = spec.config_schema.model_validate(payload).model_dump()
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=f"validation error: {e}")

        try:
            result = feature_config_manager.save_config(spec, shm_name, validated)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="camera not found")
        return FeatureConfigResponse(**result)

    return router


# 将功能配置服务、摄像头服务交给统一路由工厂处理，让其生成普通检测功能所需要的一整套HTTP API
router = create_features_router(
    feature_config_manager,
    camera_config_manager,
)
