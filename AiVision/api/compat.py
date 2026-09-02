# 文件说明：定义`compat` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/compat.py
旧前端路径兼容层。

目标:
1. 前端继续访问旧路径时不需要立刻改代码。
2. 内部只调用新 service，不复制业务逻辑。
3. 功能配置旧路径返回旧式主体: 直接返回 config，而不是正式 API 的
   {camera, feature, config} 包装。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import require_admin, get_current_user
from api.deps import (
    get_camera_service,
    get_current_orchestrator,
    get_department_service,
    get_feature_config_service,
    get_logistics_channel_service,
    get_model_service,
)
from api.cameras import (
    build_camera_frame_response,
    camera_list_response_for_user,
    camera_read_department,
    get_camera_for_user,
)
from api.alarms import alarm_image, alarm_statistics, alarm_video, list_alarms
from api.logistics_channels import _require_feature_access
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


# 功能：实现 `_require_legacy_spec` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `legacy_name`（str）：`legacy_name` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `_get_legacy_config` 调用本符号；`AiVision/api/compat.py` 的 `_get_legacy_logistics_config`
#         调用本符号；`AiVision/api/compat.py` 的 `_put_legacy_config` 调用本符号
#   - 内部调用：`_LEGACY_FEATURE_MAP.get`、`HTTPException`、`get_spec`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _require_legacy_spec(legacy_name: str):
    feature_name = _LEGACY_FEATURE_MAP.get(legacy_name)
    if feature_name is None:
        raise HTTPException(status_code=404, detail=f"unknown legacy feature: {legacy_name}")
    spec = get_spec(feature_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"feature not registered: {feature_name}")
    return spec


# 功能：用 feature 的 Pydantic schema 生成完整默认配置；输入与输出详见下方说明
# 参数：
#   - `spec`（未显式标注）：`spec` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `_normalize_legacy_payload` 调用本符号
#   - 内部调用：`spec.config_schema().model_dump`、`spec.config_schema`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _default_config_payload(spec) -> dict[str, Any]:
    """用 feature 的 Pydantic schema 生成完整默认配置。"""
    return spec.config_schema().model_dump()


# 功能：提取 value 子模型允许的字段名，用于兼容旧的扁平 PUT 入参；输入与输出详见下方说明
# 参数：
#   - `spec`（未显式标注）：`spec` 对应的业务输入值
# 返回：set[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `_normalize_legacy_payload` 调用本符号
#   - 内部调用：`set`、`getattr(value_model, 'model_fields', {}).keys`、`getattr`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _value_field_names(spec) -> set[str]:
    """提取 value 子模型允许的字段名，用于兼容旧的扁平 PUT 入参。"""
    try:
        value_field = spec.config_schema.model_fields["value"]
        value_model = value_field.annotation
        return set(getattr(value_model, "model_fields", {}).keys())
    except Exception:
        return set()


# 功能：把旧数据里的 None/null 当作缺省值处理,避免 schema 校验失败；输入与输出详见下方说明
# 参数：
#   - `defaults`（Any）：`defaults` 对应的业务输入值
#   - `incoming`（Any）：`incoming` 对应的业务输入值
# 返回：Any；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `_normalize_legacy_payload` 调用本符号
#   - 内部调用：`isinstance`、`dict`、`incoming.items`、`_merge_without_none`、`merged.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：兼容三种旧/新入参:；输入与输出详见下方说明
# 参数：
#   - `spec`（未显式标注）：`spec` 对应的业务输入值
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `_put_legacy_config` 调用本符号
#   - 内部调用：`isinstance`、`HTTPException`、`payload.get`、`_default_config_payload`、`_merge_without_none`、`merged.get`、`_value_field_names`、`dict`、`defaults.get`、`payload.items`
#          等共 18 个调用。
# 副作用/注意事项：可能发起网络请求或发送外部消息；校验或执行失败时会主动抛出异常。
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

    # 已经是正式 API 配置格式。
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


# 功能：读取或查询 `_get_legacy_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `legacy_name`（str）：`legacy_name` 对应的业务输入值
#   - `shm_name`（str）：摄像头共享内存名称
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `get_blocks_config` 调用本符号；`AiVision/api/compat.py` 的 `get_door_config`
#         调用本符号；`AiVision/api/compat.py` 的 `get_face_config` 调用本符号；`AiVision/api/compat.py` 的 `get_phone_config` 调用本符号；另有 1 处静态调用
#   - 内部调用：`_require_legacy_spec`、`feature_service.get_config`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _get_legacy_config(legacy_name: str, shm_name: str, feature_service) -> dict[str, Any]:
    spec = _require_legacy_spec(legacy_name)
    result = feature_service.get_config(spec, shm_name)
    if result is None:
        raise HTTPException(status_code=404, detail="camera or config not found")
    return result["config"]


# 功能：兼容读取物流逐路配置，同时执行部门和通道成员权限校验；输入与输出详见下方说明
# 参数：
#   - `legacy_name`（str）：`legacy_name` 对应的业务输入值
#   - `shm_name`（str）：摄像头共享内存名称
#   - `user`（dict）：当前用户或待处理用户对象
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值
#   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `get_logistics_single_person_config` 调用本符号；`AiVision/api/compat.py` 的
#         `get_logistics_single_person_electronics_electrician_config` 调用本符号；`AiVision/api/compat.py` 的
#         `get_logistics_single_person_electrical_components_config` 调用本符号；`AiVision/api/compat.py` 的
#         `get_logistics_single_person_precious_metal_recycling_config` 调用本符号
#   - 内部调用：`_require_legacy_spec`、`_require_feature_access`、`feature_service.get_config`、`HTTPException`、`user.get`、`int`、`(channel_service.list_channels(spec.name)
#          or {}).get`、`channel_service.list_channels`、`channel_service.get_channel`、`any` 等共 11 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _get_legacy_logistics_config(
    legacy_name: str,
    shm_name: str,
    user: dict,
    feature_service,
    channel_service,
) -> dict[str, Any]:
    """兼容读取物流逐路配置，同时执行部门和通道成员权限校验。"""
    spec = _require_legacy_spec(legacy_name)
    _require_feature_access(spec.name, user)
    result = feature_service.get_config(spec, shm_name)
    if result is None:
        raise HTTPException(status_code=404, detail="camera or config not found")
    if user.get("role") != "admin":
        camera_id = int(result["camera"]["id"])
        channels = (channel_service.list_channels(spec.name) or {}).get("items") or []
        for channel in channels:
            detail = channel_service.get_channel(spec.name, int(channel["id"]))
            if detail is not None and any(
                int(member["camera_id"]) == camera_id
                for member in detail.get("members", [])
            ):
                break
        else:
            raise HTTPException(
                status_code=403,
                detail="logistics channel membership permission required",
            )
    return result["config"]


# 功能：更新或保存 `_put_legacy_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `legacy_name`（str）：`legacy_name` 对应的业务输入值
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/compat.py` 的 `put_blocks_config` 调用本符号；`AiVision/api/compat.py` 的 `put_door_config`
#         调用本符号；`AiVision/api/compat.py` 的 `put_face_config` 调用本符号；`AiVision/api/compat.py` 的 `put_phone_config` 调用本符号；另有 5 处静态调用
#   - 内部调用：`_require_legacy_spec`、`_normalize_legacy_payload`、`spec.config_schema.model_validate(normalized).model_dump`、`spec.config_schema.model_validate`、`HTTPException`、`feature_service.save_config`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：读取或查询 `get_blocks_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/blocks-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/blocks-config/{shm_name}")
def get_blocks_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("blocks", shm_name, feature_service)


# 功能：更新或保存 `put_blocks_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/blocks-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/blocks-config/{shm_name}")
def put_blocks_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("blocks", shm_name, payload, feature_service)


# 功能：读取或查询 `get_door_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/door-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/door-config/{shm_name}")
def get_door_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("door", shm_name, feature_service)


# 功能：更新或保存 `put_door_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/door-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/door-config/{shm_name}")
def put_door_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("door", shm_name, payload, feature_service)


# 功能：读取或查询 `get_face_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/face-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/face-config/{shm_name}")
def get_face_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("face", shm_name, feature_service)


# 功能：更新或保存 `put_face_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/face-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/face-config/{shm_name}")
def put_face_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("face", shm_name, payload, feature_service)


# 功能：读取或查询 `get_phone_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/phone-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/phone-config/{shm_name}")
def get_phone_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("phone", shm_name, feature_service)


# 功能：更新或保存 `put_phone_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/phone-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/phone-config/{shm_name}")
def put_phone_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("phone", shm_name, payload, feature_service)


# 功能：读取或查询 `get_human_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/human-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/human-config/{shm_name}")
def get_human_config(shm_name: str, feature_service=Depends(get_feature_config_service)):
    return _get_legacy_config("human", shm_name, feature_service)


# 功能：更新或保存 `put_human_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/human-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/human-config/{shm_name}")
def put_human_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("human", shm_name, payload, feature_service)


# 功能：读取或查询 `get_logistics_single_person_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
#   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/logistics-single-person-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_logistics_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/logistics-single-person-config/{shm_name}")
def get_logistics_single_person_config(
    shm_name: str,
    user: dict = Depends(get_current_user),
    feature_service=Depends(get_feature_config_service),
    channel_service=Depends(get_logistics_channel_service),
):
    return _get_legacy_logistics_config(
        "logistics_single_person", shm_name, user, feature_service, channel_service
    )


# 功能：更新或保存 `put_logistics_single_person_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/logistics-single-person-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/logistics-single-person-config/{shm_name}")
def put_logistics_single_person_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person", shm_name, payload, feature_service)


# 功能：读取或查询 `get_logistics_single_person_electronics_electrician_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
#   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/logistics-single-person-electronics-electrician-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_logistics_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/logistics-single-person-electronics-electrician-config/{shm_name}")
def get_logistics_single_person_electronics_electrician_config(
    shm_name: str,
    user: dict = Depends(get_current_user),
    feature_service=Depends(get_feature_config_service),
    channel_service=Depends(get_logistics_channel_service),
):
    return _get_legacy_logistics_config(
        "logistics_single_person_electronics_electrician",
        shm_name,
        user,
        feature_service,
        channel_service,
    )


# 功能：更新或保存 `put_logistics_single_person_electronics_electrician_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/logistics-single-person-electronics-electrician-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/logistics-single-person-electronics-electrician-config/{shm_name}")
def put_logistics_single_person_electronics_electrician_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person_electronics_electrician", shm_name, payload, feature_service)


# 功能：读取或查询 `get_logistics_single_person_electrical_components_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
#   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/logistics-single-person-electrical-components-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_logistics_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/logistics-single-person-electrical-components-config/{shm_name}")
def get_logistics_single_person_electrical_components_config(
    shm_name: str,
    user: dict = Depends(get_current_user),
    feature_service=Depends(get_feature_config_service),
    channel_service=Depends(get_logistics_channel_service),
):
    return _get_legacy_logistics_config(
        "logistics_single_person_electrical_components",
        shm_name,
        user,
        feature_service,
        channel_service,
    )


# 功能：更新或保存 `put_logistics_single_person_electrical_components_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/logistics-single-person-electrical-components-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/logistics-single-person-electrical-components-config/{shm_name}")
def put_logistics_single_person_electrical_components_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person_electrical_components", shm_name, payload, feature_service)


# 功能：读取或查询 `get_logistics_single_person_precious_metal_recycling_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
#   - `channel_service`（未显式标注）：`channel_service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/ai/logistics-single-person-precious-metal-recycling-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_get_legacy_logistics_config`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/ai/logistics-single-person-precious-metal-recycling-config/{shm_name}")
def get_logistics_single_person_precious_metal_recycling_config(
    shm_name: str,
    user: dict = Depends(get_current_user),
    feature_service=Depends(get_feature_config_service),
    channel_service=Depends(get_logistics_channel_service),
):
    return _get_legacy_logistics_config(
        "logistics_single_person_precious_metal_recycling",
        shm_name,
        user,
        feature_service,
        channel_service,
    )


# 功能：更新或保存 `put_logistics_single_person_precious_metal_recycling_config` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `shm_name`（str）：摄像头共享内存名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/ai/logistics-single-person-precious-metal-recycling-config/{shm_name}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_put_legacy_config`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put("/api/ai/logistics-single-person-precious-metal-recycling-config/{shm_name}")
def put_logistics_single_person_precious_metal_recycling_config(
    shm_name: str,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    feature_service=Depends(get_feature_config_service),
):
    return _put_legacy_config("logistics_single_person_precious_metal_recycling", shm_name, payload, feature_service)


# ----- 旧 camera 路径 -----


# 功能：读取或查询 `compat_list_cameras` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `department`（str | None）：业务部门名称或标识；默认值为 `Query(None, description='可选按部门过滤')`
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/cameras')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`Depends`、`camera_list_response_for_user`、`camera_service.list_cameras`、`camera_read_department`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/cameras")
def compat_list_cameras(
    department: str | None = Query(None, description="可选按部门过滤"),
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
):
    return camera_list_response_for_user(
        camera_service.list_cameras(
            department=camera_read_department(user, department)
        ),
        user,
    )


# 功能：创建或构建 `compat_create_camera` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.post('/api/aivision/cameras', status_code=status.HTTP_201_CREATED)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`camera_service.create_camera`、`HTTPException`、`str`、`router.post`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：读取或查询 `compat_get_camera` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/cameras/{key}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`get_camera_for_user`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/cameras/{key}")
def compat_get_camera(
    key: str,
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
):
    return get_camera_for_user(camera_service, key, user)


# 功能：更新或保存 `compat_update_camera` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/api/aivision/cameras/{key}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`camera_service.update_camera`、`HTTPException`、`router.put`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：删除或清理 `compat_delete_camera` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.delete('/api/aivision/cameras/{key}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`camera_service.delete_camera`、`HTTPException`、`router.delete`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：读取或查询 `compat_get_camera_frame_jpg` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `feature`（str | None）：`feature` 对应的业务输入值；默认值为 `Query(None)`
#   - `quality`（int）：`quality` 对应的业务输入值；默认值为 `Query(85, ge=1, le=100)`
#   - `max_width`（int | None）：`max_width` 对应的业务输入值；默认值为 `Query(None, ge=1, le=4096)`
#   - `max_height`（int | None）：`max_height` 对应的业务输入值；默认值为 `Query(None, ge=1, le=4096)`
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值；默认值为 `Depends(get_current_orchestrator)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/cameras/{key}/frame.jpg')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`Depends`、`get_camera_for_user`、`build_camera_frame_response`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：读取或查询 `compat_get_camera_feature_status` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值；默认值为 `Depends(get_current_orchestrator)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/cameras/{key}/features/{feature}/status')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`get_camera_for_user`、`orchestrator.get_feature_monitor_status`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：读取或查询 `compat_list_alarms` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `limit`（int）：返回或处理的最大记录数；默认值为 `Query(200, ge=1, le=1000)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/alarms')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`list_alarms`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/alarms")
def compat_list_alarms(limit: int = Query(200, ge=1, le=1000)):
    return list_alarms(limit=limit)


# 功能：实现 `compat_alarm_image` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm_id`（int）：`alarm_id` 对应业务对象的唯一标识
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/alarms/{alarm_id}/image')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`alarm_image`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/alarms/{alarm_id}/image")
def compat_alarm_image(alarm_id: int):
    return alarm_image(alarm_id)


# 功能：实现 `compat_alarm_video` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm_id`（int）：`alarm_id` 对应业务对象的唯一标识
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/alarms/{alarm_id}/video')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`alarm_video`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/alarms/{alarm_id}/video")
def compat_alarm_video(alarm_id: int):
    return alarm_video(alarm_id)


# 功能：实现 `public_aivision_alarm_image` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm_id`（int）：`alarm_id` 对应业务对象的唯一标识
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/public/aivision/alarms/{alarm_id}/image')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`alarm_image`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/public/aivision/alarms/{alarm_id}/image")
def public_aivision_alarm_image(alarm_id: int):
    return alarm_image(alarm_id)


# 功能：实现 `compat_alarm_statistics` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `days`（int）：`days` 对应的业务输入值；默认值为 `Query(7, ge=1, le=90)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/statistics')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`alarm_statistics`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/statistics")
def compat_alarm_statistics(days: int = Query(7, ge=1, le=90)):
    return alarm_statistics(days=days)


# ----- 旧 model 路径 -----


# 功能：读取或查询 `compat_list_models` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `model_service`（未显式标注）：`model_service` 对应的业务输入值；默认值为 `Depends(get_model_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/models')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`model_service.list_models`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/models")
def compat_list_models(model_service=Depends(get_model_service)):
    return model_service.list_models(enabled_only=False)


# 功能：创建或构建 `compat_create_model` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `model_service`（未显式标注）：`model_service` 对应的业务输入值；默认值为 `Depends(get_model_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.post('/api/aivision/models', status_code=status.HTTP_201_CREATED)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`model_service.create_model`、`HTTPException`、`router.post`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
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


# 功能：实现 `compat_patch_model` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `model_id`（int）：模型唯一标识
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `model_service`（未显式标注）：`model_service` 对应的业务输入值；默认值为 `Depends(get_model_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.patch('/api/aivision/models/{model_id}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`model_service.update_model`、`HTTPException`、`router.patch`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.patch("/api/aivision/models/{model_id}")
def compat_patch_model(
    model_id: int,
    payload: dict[str, Any],
    _user: dict = Depends(require_admin),
    model_service=Depends(get_model_service),
):
    model = model_service.update_model(model_id, payload)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


# ----- AiVision departments 路径 -----

# 功能：读取或查询 `compat_list_departments` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/departments')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`session_scope`、`dept_service.list_departments`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/departments")
def compat_list_departments(
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    with session_scope() as session:
        depts = dept_service.list_departments(session)
        return [{"name": d.name, "display_name": d.display_name} for d in depts]


# 功能：读取或查询 `compat_get_department_features` 对应的`compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/api/aivision/departments/{name}/features')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`session_scope`、`dept_service.get_features_by_department`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/api/aivision/departments/{name}/features")
def compat_get_department_features(
    name: str,
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    with session_scope() as session:
        return dept_service.get_features_by_department(session, name)
