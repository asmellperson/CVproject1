"""
features/_base/api.py
通用功能配置 API — 替代旧代码里 5 个重复的 *_config_api.py。

旧代码: blocks_config_api.py / door_config_api.py / face_config_api.py / phone_config_api.py / human_config_api.py
        每个文件 100+ 行,只有功能名不同,实质代码一字不差。

新代码: 1 个路由处理所有功能。前端访问:
    GET  /api/v2/features                         → 列出所有 feature 元数据
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


# ---------- Response models ----------

class FeatureMetaResponse(BaseModel):
    """单个 feature 的元数据(供前端动态生成菜单)"""
    name: str
    display_name: str
    required_models: list[str]
    violation_type: int
    config_schema: dict  # JSON Schema,前端可据此自动生成表单


class FeaturesListResponse(BaseModel):
    features: list[FeatureMetaResponse]


class FeatureConfigResponse(BaseModel):
    """统一的配置响应格式 — 替代旧代码 5 个不同的响应类型"""
    camera: dict   # {id, name, shm_name, enable}
    feature: str   # "blocks" / "detect_face" / ...
    config: dict   # {enable, value: {...}, alarm: {sql, horn, wechat}}


# ---------- Helpers ----------

def _spec_to_meta(spec: FeatureSpec) -> FeatureMetaResponse:
    return FeatureMetaResponse(
        name=spec.name,
        display_name=spec.display_name,
        required_models=list(spec.required_models),
        violation_type=spec.violation_type,
        config_schema=spec.config_schema.model_json_schema(),
    )


def _require_spec(feature: str) -> FeatureSpec:
    spec = get_spec(feature)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown feature: {feature}")
    return spec


# ---------- Router ----------

def create_features_router(feature_service) -> APIRouter:
    """构造功能元数据 + 配置读写的统一路由。
    
    feature_service 是 features._base.service.FeatureConfigService 实例,
    封装了所有跨功能的配置读写逻辑。
    """
    router = APIRouter(prefix="/api/v2/features", tags=["features"])

    @router.get("", response_model=FeaturesListResponse)
    def list_features():
        """列出所有可用功能 — 前端用来动态生成菜单"""
        return FeaturesListResponse(
            features=[_spec_to_meta(s) for s in all_specs().values()]
        )

    @router.get("/{feature}", response_model=FeatureMetaResponse)
    def get_feature_meta(feature: Annotated[str, Path()]):
        return _spec_to_meta(_require_spec(feature))

    @router.get(
        "/{feature}/configs/{shm_name}",
        response_model=FeatureConfigResponse,
    )
    def get_feature_config(feature: str, shm_name: str):
        spec = _require_spec(feature)
        result = feature_service.get_config(spec, shm_name)
        if result is None:
            raise HTTPException(status_code=404, detail="camera or config not found")
        return FeatureConfigResponse(**result)

    @router.put(
        "/{feature}/configs/{shm_name}",
        response_model=FeatureConfigResponse,
    )
    def save_feature_config(feature: str, shm_name: str, payload: dict, _user: dict = Depends(require_admin)):
        spec = _require_spec(feature)
        # 用 spec.config_schema 校验入参
        try:
            validated = spec.config_schema.model_validate(payload).model_dump()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"validation error: {e}")
        result = feature_service.save_config(spec, shm_name, validated)
        if result is None:
            raise HTTPException(status_code=404, detail="camera not found")
        return FeatureConfigResponse(**result)

    return router
