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
from pydantic import BaseModel, Field, ValidationError

from auth.auth import get_current_user, require_admin
from AiVision.api.routes.cameras import get_camera_for_user         # 检查某个用户有没有权限查看这个摄像头
from AiVision.api.deps import get_camera_config_manager, get_current_orchestrator

from AiVision.features.registry import all_specs, get_spec            # 系统当前已经注册过的所有检测功能以及查询某个具体的功能
from AiVision.features._shared.spec import FeatureSpec
from AiVision.features._shared.config_manager import feature_config_manager    # 普通检测功能配置管理函数
from AiVision.cameras.config_manager import camera_config_manager           # 摄像头配置服务

class FeatureMetaResponse(BaseModel):
    """单个检测功能和前端交互的字段"""
    name: str
    display_name: str
    required_models: list[str]
    violation_type: int                     # 违规数量
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
    get_camera_for_user(camera_config_manager, key, user)                 # 检查用户有没有权限查看这台摄像头：摄像头不存在返回404，用户没有权限访问返回403
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
        # 当前元数据接口只表达单报警功能，不能替复合功能选择类型。
        (violation_type,) = spec.alarm_types
        # 返回FeatureMetaResponse
        return FeatureMetaResponse(
            name=spec.name,
            display_name=spec.display_name,
            required_models=list(spec.required_models),
            violation_type=violation_type,
            config_schema=spec.config_schema.model_json_schema(),
            default_config=spec.config_schema().model_dump(),
        )

    @router.get("", response_model=FeaturesListResponse)
    def list_features():
        """返回所有注册功能，形成前端功能菜单"""
        return FeaturesListResponse(
            features=[_spec_to_meta(s) for s in all_specs().values()]
        )

    @router.get("/{feature}", response_model=FeatureMetaResponse)
    def get_feature_meta(feature: Annotated[str, Path()]):
        """返回单个功能的元数据，包含 JSON Schema 供前端按需渲染表单。"""
        return _spec_to_meta(_require_spec(feature))        # _require_spec:找到具体检测功能的FeatureSpec

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
        if user.get("role") != "admin":
            get_camera_for_user(camera_config_manager, shm_name, user)
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
