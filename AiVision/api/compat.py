"""
api/compat.py
旧前端路径兼容层。

目标:
1. 前端继续访问旧路径时不需要立刻改代码。
2. 内部只调用新 service，不复制业务逻辑。
3. 功能配置旧路径返回旧式主体: 直接返回 config，而不是 v2 的
   {camera, feature, config} 包装。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import require_admin, get_current_user
from api.deps import get_camera_service, get_current_orchestrator, get_feature_config_service, get_model_service, get_department_service
from api.v2.cameras import (
    build_camera_frame_response,
    camera_read_department,
    get_camera_for_user,
)
from api.v2.alarms import alarm_image, alarm_statistics, list_alarms
from core.db import session_scope
from platform.department.service import DepartmentService
from features import get_spec


router = APIRouter(tags=["compat"])


_LEGACY_FEATURE_MAP = {
    "blocks": "blocks",
    "door": "detect_door",
    "face": "detect_face",
    "phone": "detect_phone",
    "human": "detect_human",
    "logistics_single_person": "detect_logistics_single_person",
    "logistics_single_person_electronics_electrician": "detect_logistics_single_person_electronics_electrician",
    "logistics_single_person_electrical_components": "detect_logistics_single_person_electrical_components",
    "logistics_single_person_precious_metal_recycling": "detect_logistics_single_person_precious_metal_recycling",
}


def _require_legacy_spec(legacy_name: str):
    feature_name = _LEGACY_FEATURE_MAP.get(legacy_name)
    if feature_name is None:
        raise HTTPException(status_code=404, detail=f"unknown legacy feature: {legacy_name}")
    spec = get_spec(feature_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"feature not registered: {feature_name}")
    return spec


def _default_config_payload(spec) -> dict[str, Any]:
    """用 feature 的 Pydantic schema 生成完整默认配置。"""
    return spec.config_schema().model_dump()


def _value_field_names(spec) -> set[str]:
    """提取 value 子模型允许的字段名，用于兼容旧的扁平 PUT 入参。"""
    try:
        value_field = spec.config_schema.model_fields["value"]
        value_model = value_field.annotation
        return set(getattr(value_model, "model_fields", {}).keys())
    except Exception:
        return set()


def _merge_without_none(defaults: Any, incoming: Any) -> Any:
    """把旧数据里的 None/null 当作缺省值处理,避免 schema 校验失败。"""
    if incoming is None:
        return defaults
    if isinstance(defaults, dict) and isinstance(incoming, dict):
        merged = dict(defaults)
        for key, val in incoming.items():
            merged[key] = _merge_without_none(merged.get(key), val)
        return merged
    return incoming


def _normalize_legacy_payload(spec, payload: dict[str, Any]) -> dict[str, Any]:
    """
    兼容三种旧/新入参:
    - 新格式: {enable, value, alarm}
    - 包装格式: {config: {enable, value, alarm}}
    - 老扁平格式: {enable, roi_pos, threshold, sql_enable, horn_enable, ...}
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")

    if isinstance(payload.get("config"), dict):
        payload = payload["config"]

    # 已经是 v2 配置格式。
    if "value" in payload or "alarm" in payload:
        merged = _default_config_payload(spec)
        if "enable" in payload:
            merged["enable"] = payload["enable"]
        if "value" in payload:
            merged["value"] = _merge_without_none(merged.get("value") or {}, payload.get("value") or {})
        if "alarm" in payload:
            merged["alarm"] = _merge_without_none(merged.get("alarm") or {}, payload.get("alarm") or {})
        if "enabled" in payload and "enable" not in payload:
            merged["enable"] = payload["enabled"]
        return merged

    defaults = _default_config_payload(spec)
    value_names = _value_field_names(spec)

    value = dict(defaults.get("value") or {})
    for key in value_names:
        if key in payload:
            value[key] = payload[key]

    # 如果旧前端直接传了未知业务字段，也允许透传给 schema 做最终裁决。
    for key, val in payload.items():
        if key not in {
            "enable", "enabled",
            "sql_enable", "horn_enable", "horn_id", "horn_event_id",
            "wechat_enable", "wechat_user", "sql", "horn", "wechat",
        } and key not in value:
            value[key] = val

    alarm = dict(defaults.get("alarm") or {})
    if isinstance(payload.get("alarm"), dict):
        alarm.update(payload["alarm"])

    if "sql_enable" in payload:
        alarm.setdefault("sql", {}).update({"enable": bool(payload["sql_enable"])})
    if "horn_enable" in payload or "horn_id" in payload or "horn_event_id" in payload:
        horn = alarm.setdefault("horn", {"enable": False, "parm": {}})
        if "horn_enable" in payload:
            horn["enable"] = bool(payload["horn_enable"])
        parm = horn.setdefault("parm", {})
        if "horn_id" in payload:
            parm["horn_id"] = payload["horn_id"]
        if "horn_event_id" in payload:
            parm["horn_event_id"] = payload["horn_event_id"]
    if "wechat_enable" in payload or "wechat_user" in payload:
        wechat = alarm.setdefault("wechat", {"enable": False, "parm": {"user": ""}})
        if "wechat_enable" in payload:
            wechat["enable"] = bool(payload["wechat_enable"])
        wechat.setdefault("parm", {})["user"] = payload.get("wechat_user", wechat.get("parm", {}).get("user", ""))

    return {
        "enable": bool(payload.get("enable", payload.get("enabled", defaults.get("enable", False)))),
        "value": value,
        "alarm": alarm,
    }


def _get_legacy_config(legacy_name: str, shm_name: str, feature_service) -> dict[str, Any]:
    spec = _require_legacy_spec(legacy_name)
    result = feature_service.get_config(spec, shm_name)
    if result is None:
        raise HTTPException(status_code=404, detail="camera or config not found")
    return result["config"]


def _put_legacy_config(legacy_name: str, shm_name: str, payload: dict[str, Any], feature_service) -> dict[str, Any]:
    spec = _require_legacy_spec(legacy_name)
    normalized = _normalize_legacy_payload(spec, payload)
    try:
        validated = spec.config_schema.model_validate(normalized).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"validation error: {exc}") from exc
    result = feature_service.save_config(spec, shm_name, validated)
    if result is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return result["config"]

# ----- 旧 feature config 路径 -----


@router.get("/api/ai/blocks-config/{shm_name}")
def get_blocks_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("blocks", shm_name, feature_service)


@router.put("/api/ai/blocks-config/{shm_name}")
def put_blocks_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("blocks", shm_name, payload, feature_service)


@router.get("/api/ai/door-config/{shm_name}")
def get_door_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("door", shm_name, feature_service)


@router.put("/api/ai/door-config/{shm_name}")
def put_door_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("door", shm_name, payload, feature_service)


@router.get("/api/ai/face-config/{shm_name}")
def get_face_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("face", shm_name, feature_service)


@router.put("/api/ai/face-config/{shm_name}")
def put_face_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("face", shm_name, payload, feature_service)


@router.get("/api/ai/phone-config/{shm_name}")
def get_phone_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("phone", shm_name, feature_service)


@router.put("/api/ai/phone-config/{shm_name}")
def put_phone_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("phone", shm_name, payload, feature_service)


@router.get("/api/ai/human-config/{shm_name}")
def get_human_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("human", shm_name, feature_service)


@router.put("/api/ai/human-config/{shm_name}")
def put_human_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("human", shm_name, payload, feature_service)


@router.get("/api/ai/logistics-single-person-config/{shm_name}")
def get_logistics_single_person_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("logistics_single_person", shm_name, feature_service)


@router.put("/api/ai/logistics-single-person-config/{shm_name}")
def put_logistics_single_person_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person", shm_name, payload, feature_service)


@router.get("/api/ai/logistics-single-person-electronics-electrician-config/{shm_name}")
def get_logistics_single_person_electronics_electrician_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("logistics_single_person_electronics_electrician", shm_name, feature_service)


@router.put("/api/ai/logistics-single-person-electronics-electrician-config/{shm_name}")
def put_logistics_single_person_electronics_electrician_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person_electronics_electrician", shm_name, payload, feature_service)


@router.get("/api/ai/logistics-single-person-electrical-components-config/{shm_name}")
def get_logistics_single_person_electrical_components_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("logistics_single_person_electrical_components", shm_name, feature_service)


@router.put("/api/ai/logistics-single-person-electrical-components-config/{shm_name}")
def put_logistics_single_person_electrical_components_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person_electrical_components", shm_name, payload, feature_service)


@router.get("/api/ai/logistics-single-person-precious-metal-recycling-config/{shm_name}")
def get_logistics_single_person_precious_metal_recycling_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("logistics_single_person_precious_metal_recycling", shm_name, feature_service)


@router.put("/api/ai/logistics-single-person-precious-metal-recycling-config/{shm_name}")
def put_logistics_single_person_precious_metal_recycling_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person_precious_metal_recycling", shm_name, payload, feature_service)


# ----- 旧 camera 路径 -----


@router.get("/api/aivision/cameras")
def compat_list_cameras(
    department: str | None = Query(None, description="可选按部门过滤"),
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
):
    return camera_service.list_cameras(
        department=camera_read_department(user, department)
    )


@router.post("/api/aivision/cameras", status_code=status.HTTP_201_CREATED)
def compat_create_camera(
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
):
    try:
        return camera_service.create_camera(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/aivision/cameras/{key}")
def compat_get_camera(
    key: str,
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
):
    return get_camera_for_user(camera_service, key, user)


@router.put("/api/aivision/cameras/{key}")
def compat_update_camera(
    key: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
):
    camera = camera_service.update_camera(key, payload)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


@router.delete("/api/aivision/cameras/{key}")
def compat_delete_camera(
    key: str,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
):
    ok = camera_service.delete_camera(key)
    if not ok:
        raise HTTPException(status_code=404, detail="camera not found")
    return {"ok": True}


@router.get("/api/aivision/cameras/{key}/frame.jpg")
def compat_get_camera_frame_jpg(
    key: str,
    feature: str | None = Query(None),
    quality: int = Query(85, ge=1, le=100),
    max_width: int | None = Query(None, ge=1, le=4096),
    max_height: int | None = Query(None, ge=1, le=4096),
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
    orchestrator=Depends(get_current_orchestrator),
):
    get_camera_for_user(camera_service, key, user)
    return build_camera_frame_response(
        key=key,
        feature=feature,
        quality=quality,
        max_width=max_width,
        max_height=max_height,
        orchestrator=orchestrator,
    )


@router.get("/api/aivision/cameras/{key}/features/{feature}/status")
def compat_get_camera_feature_status(
    key: str,
    feature: str,
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
    orchestrator=Depends(get_current_orchestrator),
):
    get_camera_for_user(camera_service, key, user)
    return orchestrator.get_feature_monitor_status(key, feature)


# ----- AiVision alarm/statistics 路径 -----


@router.get("/api/aivision/alarms")
def compat_list_alarms(limit: int = Query(200, ge=1, le=1000)):
    return list_alarms(limit=limit)


@router.get("/api/aivision/alarms/{alarm_id}/image")
def compat_alarm_image(alarm_id: int):
    return alarm_image(alarm_id)


@router.get("/api/public/aivision/alarms/{alarm_id}/image")
def public_aivision_alarm_image(alarm_id: int):
    return alarm_image(alarm_id)


@router.get("/api/aivision/statistics")
def compat_alarm_statistics(days: int = Query(7, ge=1, le=90)):
    return alarm_statistics(days=days)


# ----- 旧 model 路径 -----


@router.get("/api/aivision/models")
def compat_list_models(model_service=Depends(get_model_service)):
    return model_service.list_models(enabled_only=False)


@router.post("/api/aivision/models", status_code=status.HTTP_201_CREATED)
def compat_create_model(
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    model_service=Depends(get_model_service),
):
    try:
        return model_service.create_model(payload)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"missing field: {exc}") from exc


@router.put("/api/aivision/models/{model_id}")
def compat_update_model(
    model_id: int,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    model_service=Depends(get_model_service),
):
    model = model_service.update_model(model_id, payload)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


@router.patch("/api/aivision/models/{model_id}")
def compat_patch_model(
    model_id: int,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    model_service=Depends(get_model_service),
):
    return compat_update_model(model_id, payload, _user, model_service)


# ----- AiVision departments 路径 -----

@router.get("/api/aivision/departments")
def compat_list_departments(
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    with session_scope() as session:
        depts = dept_service.list_departments(session)
        return [{"name": d.name, "display_name": d.display_name} for d in depts]


@router.get("/api/aivision/departments/{name}/features")
def compat_get_department_features(
    name: str,
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    with session_scope() as session:
        return dept_service.get_features_by_department(session, name)
