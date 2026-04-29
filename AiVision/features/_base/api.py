"""
features/_base/api.py
通用功能配置 API — 替代旧代码里 5 个重复的 *_config_api.py。

旧代码: blocks_config_api.py / door_config_api.py / face_config_api.py / phone_config_api.py / human_config_api.py
        每个文件 100+ 行,只有功能名不同,实质代码一字不差。

新代码: 1 个路由处理所有功能。前端访问:
    GET  /api/v2/features                         → 列出所有 feature 元数据
    GET  /api/v2/features/{feature}               → 单个 feature 元数据
    GET  /api/v2/features/{feature}/configs/{cam} → 读单个摄像头的配置
    PUT  /api/v2/features/{feature}/configs/{cam} → 写单个摄像头的配置
"""
from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from api.auth import require_admin
from features import all_specs, get_spec
from features._base.spec import FeatureSpec


# ------------------------------------------------------------------ #
#  响应模型                                                             #
# ------------------------------------------------------------------ #

class FeatureMetaResponse(BaseModel):
    """
    单个功能的元数据，供前端动态生成导航菜单与功能入口。

    config_schema: 由 spec.config_schema.model_json_schema() 生成的 JSON Schema，
                   前端可据此自动渲染配置表单，无需为每个功能单独编写 UI。
    """
    name: str
    display_name: str
    required_models: list[str]
    violation_type: int
    config_schema: dict


class FeaturesListResponse(BaseModel):
    """所有已注册功能的元数据列表，对应 GET /api/v2/features 的响应体。"""
    features: list[FeatureMetaResponse]


class FeatureConfigResponse(BaseModel):
    """
    统一的功能配置响应格式，替代旧代码中 5 个各自定义的响应类型。

    字段说明:
        camera : 摄像头基础信息 {id, name, shm_name, enable}。
        feature: 功能名称，如 "blocks" / "detect_face"。
        config : 功能配置体 {enable, value: {...}, alarm: {sql, horn, wechat}}，
                 结构与数据库中 function_config JSON 的单功能节点一致。
    """
    camera: dict
    feature: str
    config: dict


# ------------------------------------------------------------------ #
#  内部工具函数                                                         #
# ------------------------------------------------------------------ #

def _spec_to_meta(spec: FeatureSpec) -> FeatureMetaResponse:
    """将 FeatureSpec 对象转换为 API 响应模型，集中处理 JSON Schema 序列化。"""
    return FeatureMetaResponse(
        name=spec.name,
        display_name=spec.display_name,
        required_models=list(spec.required_models),
        violation_type=spec.violation_type,
        config_schema=spec.config_schema.model_json_schema(),
    )


def _require_spec(feature: str) -> FeatureSpec:
    """
    按功能名查找已注册的 FeatureSpec，未找到时抛出 404。

    集中处理"功能不存在"的错误响应，避免每个路由重复判断。
    """
    spec = get_spec(feature)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown feature: {feature}")
    return spec


# ------------------------------------------------------------------ #
#  路由工厂                                                             #
# ------------------------------------------------------------------ #

def create_features_router(feature_service) -> APIRouter:
    """
    构造功能元数据查询 + 配置读写的统一 APIRouter。

    采用工厂函数而非模块级路由实例，原因是 feature_service 需在应用启动时
    由外部注入（依赖 DB 连接与缓存），避免模块导入时产生副作用。

    Args:
        feature_service: FeatureConfigService 实例，封装跨功能的配置读写逻辑，
                         由调用方（通常是 Orchestrator 或 app 工厂）负责创建并传入。

    Returns:
        挂载在 /api/v2/features 下的 APIRouter，可直接 app.include_router()。
    """
    router = APIRouter(prefix="/api/v2/features", tags=["features"])

    @router.get("", response_model=FeaturesListResponse)
    def list_features():
        """
        列出所有已注册功能的元数据。

        前端通过此接口动态生成功能菜单，新增功能只需在 features 注册表注册，
        无需修改前端路由或后端路由代码。
        """
        return FeaturesListResponse(
            features=[_spec_to_meta(s) for s in all_specs().values()]
        )

    @router.get("/{feature}", response_model=FeatureMetaResponse)
    def get_feature_meta(feature: Annotated[str, Path()]):
        """返回单个功能的元数据，包含 JSON Schema 供前端按需渲染表单。"""
        return _spec_to_meta(_require_spec(feature))

    @router.get(
        "/{feature}/configs/{shm_name}",
        response_model=FeatureConfigResponse,
    )
    def get_feature_config(feature: str, shm_name: str):
        """
        读取指定摄像头的功能配置。

        shm_name 为摄像头共享内存标识（即 ai_camera_config.shm_name），
        摄像头或对应功能配置不存在时返回 404。
        """
        spec = _require_spec(feature)
        result = feature_service.get_config(spec, shm_name)
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
            2. 校验通过后调用 feature_service.save_config() 持久化到数据库。
            3. 返回保存后的最新配置，供前端直接刷新本地状态。

        校验失败返回 400，摄像头不存在返回 404。
        """
        spec = _require_spec(feature)
        try:
            # 用各功能自定义的 Pydantic schema 校验入参，类型错误或缺字段时抛异常
            validated = spec.config_schema.model_validate(payload).model_dump()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"validation error: {e}")

        result = feature_service.save_config(spec, shm_name, validated)
        if result is None:
            raise HTTPException(status_code=404, detail="camera not found")
        return FeatureConfigResponse(**result)

    return router