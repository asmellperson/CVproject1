# 文件说明：定义`logistics_channels` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""物流通道 CRUD、成员、运行状态和拼接画面 API。"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ConfigDict

from api.auth import get_current_user, require_admin
from api.deps import (
    get_current_orchestrator,
    get_feature_config_service,
    get_logistics_channel_service,
)
from api.features import FeatureConfigResponse
from api.cameras import encode_frame_to_jpeg, frame_size_headers
from core.db import get_session
from features import all_specs
from platform.logistics_channel.constants import (
    LOGISTICS_FEATURE_DEPARTMENTS,
    LOGISTICS_FEATURES,
)
from platform.logistics_channel.schema import (
    LogisticsChannelAlarmListResponse,
    LogisticsCameraInventoryResponse,
    LogisticsChannelConfigUpdate,
    LogisticsChannelCreate,
    LogisticsChannelDetailResponse,
    LogisticsChannelListResponse,
    LogisticsChannelMemberCreate,
    LogisticsChannelMemberEnabledUpdate,
    LogisticsChannelMemberOrder,
    LogisticsChannelOkResponse,
    LogisticsChannelRuntimeStatusResponse,
    LogisticsChannelStatisticsResponse,
    LogisticsChannelUpdate,
)
from platform.violation.orm import AiViolationImage


router = APIRouter(prefix="/api/logistics-channels", tags=["logistics-channels"])


# 功能：通道元数据和通道级检测配置的一次更新；输入与输出详见下方说明
# 参数：
#   - `config`（LogisticsChannelConfigUpdate | None）：运行配置对象
# 返回：LogisticsChannelPutRequest；返回新建的 `LogisticsChannelPutRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelPutRequest(LogisticsChannelUpdate):
    """通道元数据和通道级检测配置的一次更新。"""

    model_config = ConfigDict(extra="forbid")
    config: LogisticsChannelConfigUpdate | None = None


# 功能：根据角色和多事业部授权，列出当前用户可读取的全部物流检测功能。
# 参数：
#   - `user`（dict）：当前用户或待处理用户对象
# 返回：list[str]；返回有权访问的物流功能标识，顺序与 `LOGISTICS_FEATURES` 一致。
# 调用关系：
#   - 调用方：`_require_feature_access` 与 `list_logistics_camera_inventory` 调用本符号
#   - 内部调用：`user.get`、`isinstance`、`str.strip`、`list`。
# 副作用/注意事项：无外部副作用；管理员或含 `all` 授权的用户返回全部物流功能。
def _accessible_logistics_features(user: dict) -> list[str]:
    """返回当前用户有权读取的物流功能集合。"""
    if user.get("role") == "admin":
        return list(LOGISTICS_FEATURES)
    raw_departments = user.get("departments")
    candidates = (
        raw_departments
        if isinstance(raw_departments, list) and raw_departments
        else [user.get("department")]
    )
    departments = {
        str(department or "").strip()
        for department in candidates
        if str(department or "").strip()
    }
    if "all" in departments:
        return list(LOGISTICS_FEATURES)
    return [
        feature
        for feature in LOGISTICS_FEATURES
        if LOGISTICS_FEATURE_DEPARTMENTS[feature] in departments
    ]


# 功能：校验用户是否有权访问指定物流功能，并返回通过校验的功能标识。
# 参数：
#   - `feature`（str）：待访问的物流功能标识
#   - `user`（dict）：当前用户或待处理用户对象
# 返回：str；返回通过权限校验的物流功能标识。
# 调用关系：
#   - 调用方：物流通道列表、详情、配置、成员、状态、画面和告警等路由调用本符号
#   - 内部调用：`_accessible_logistics_features`、`HTTPException`。
# 副作用/注意事项：功能不存在时抛出 404，无事业部权限时抛出 403。
def _require_feature_access(feature: str, user: dict) -> str:
    if feature not in LOGISTICS_FEATURES:
        raise HTTPException(status_code=404, detail="logistics feature not found")
    if feature not in _accessible_logistics_features(user):
        raise HTTPException(status_code=403, detail="feature department permission required")
    return feature


# 功能：实现 `_raise_service_error` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `exc`（ValueError）：`exc` 对应的业务输入值
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/logistics_channels.py` 的 `create_channel` 调用本符号；`AiVision/api/logistics_channels.py` 的
#         `update_channel` 调用本符号；`AiVision/api/logistics_channels.py` 的 `update_channel_config`
#         调用本符号；`AiVision/api/logistics_channels.py` 的 `add_camera` 调用本符号；另有 3 处静态调用
#   - 内部调用：`str`、`any`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _raise_service_error(exc: ValueError) -> None:
    detail = str(exc)
    if "不存在" in detail:
        code = status.HTTP_404_NOT_FOUND
    elif any(marker in detail for marker in ("已存在", "已绑定", "约束冲突", "最多", "上限")):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=detail) from exc


# 功能：读取或查询 `_get_channel_or_404` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service`（未显式标注）：`service` 对应的业务输入值
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/logistics_channels.py` 的 `get_channel` 调用本符号；`AiVision/api/logistics_channels.py` 的
#         `_require_channel_member` 调用本符号；`AiVision/api/logistics_channels.py` 的 `get_channel_status`
#         调用本符号；`AiVision/api/logistics_channels.py` 的 `get_channel_frame` 调用本符号；另有 2 处静态调用
#   - 内部调用：`service.get_channel`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _get_channel_or_404(service, feature: str, channel_id: int) -> dict:
    channel = service.get_channel(feature, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return channel


# 功能：汇总当前用户有权访问的物流通道摄像头，按物理摄像头 ID 去重并返回安全字段。
# 参数：
#   - `user`（dict）：当前登录用户，使用其多事业部权限筛选物流功能
#   - `service`：物流通道服务，用于读取通道及成员关系
#   - `orchestrator`：运行编排器，用于读取通道内单路摄像头在线状态
# 返回：LogisticsCameraInventoryResponse；不含 RTSP 地址的物流摄像头清单。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/inventory')` 注册；首页平台汇总通过前端物流 API 调用
#   - 内部调用：`_accessible_logistics_features`、`service.list_camera_inventory`、`orchestrator.get_logistics_channel_status`、`LogisticsCameraInventoryResponse.model_validate`。
# 副作用/注意事项：只读数据库与运行时快照；同一摄像头跨通道或跨功能出现时合并，绝不返回连接地址。
@router.get("/inventory", response_model=LogisticsCameraInventoryResponse)
def list_logistics_camera_inventory(
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
    orchestrator=Depends(get_current_orchestrator),
) -> LogisticsCameraInventoryResponse:
    items = service.list_camera_inventory(
        _accessible_logistics_features(user)
    )
    status_by_channel: dict[tuple[str, int], dict[str, Any]] = {}
    for item in items:
        item["online"] = False
        camera_id = item["camera_id"]
        for membership in item["memberships"]:
            feature = membership["feature_name"]
            channel_id = membership["channel_id"]
            channel_key = (feature, channel_id)
            if channel_key not in status_by_channel:
                status_by_channel[channel_key] = (
                    orchestrator.get_logistics_channel_status(feature, channel_id)
                    or {}
                )
            camera_states = status_by_channel[channel_key].get(
                "camera_states",
                {},
            )
            if not isinstance(camera_states, dict):
                camera_states = {}
            state = camera_states.get(
                str(camera_id),
                camera_states.get(camera_id, {}),
            )
            if not isinstance(state, dict):
                state = {}
            membership["online"] = bool(
                membership["enabled"] and state.get("online", False)
            )
            item["online"] = bool(
                item["online"] or membership["online"]
            )
    return LogisticsCameraInventoryResponse.model_validate({"items": items})


# 功能：读取或查询 `list_channels` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelListResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{feature}', response_model=LogisticsChannelListResponse)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`LogisticsChannelListResponse.model_validate`、`service.list_channels`、`_require_feature_access`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/{feature}", response_model=LogisticsChannelListResponse)
def list_channels(
    feature: str,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelListResponse:
    return LogisticsChannelListResponse.model_validate(
        service.list_channels(_require_feature_access(feature, user))
    )


# 功能：创建或构建 `create_channel` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `payload`（LogisticsChannelCreate）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.post('/{feature}', status_code=status.HTTP_201_CREATED,
#         response_model=LogisticsChannelDetailResponse)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`LogisticsChannelDetailResponse.model_validate`、`service.create_channel`、`_raise_service_error`、`router.post`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.post(
    "/{feature}",
    status_code=status.HTTP_201_CREATED,
    response_model=LogisticsChannelDetailResponse,
)
def create_channel(
    feature: str,
    payload: LogisticsChannelCreate,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.create_channel(feature, payload.name)
        )
    except ValueError as exc:
        _raise_service_error(exc)


# 功能：读取或查询 `get_channel` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{feature}/{channel_id}', response_model=LogisticsChannelDetailResponse)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`LogisticsChannelDetailResponse.model_validate`、`_get_channel_or_404`、`_require_feature_access`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/{feature}/{channel_id}", response_model=LogisticsChannelDetailResponse)
def get_channel(
    feature: str,
    channel_id: int,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    return LogisticsChannelDetailResponse.model_validate(
        _get_channel_or_404(service, _require_feature_access(feature, user), channel_id)
    )


# 功能：更新或保存 `update_channel` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `payload`（LogisticsChannelPutRequest）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{feature}/{channel_id}', response_model=LogisticsChannelDetailResponse)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`payload.model_dump`、`service.update_channel_and_config`、`HTTPException`、`LogisticsChannelDetailResponse.model_validate`、`_raise_service_error`、`router.put`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.put("/{feature}/{channel_id}", response_model=LogisticsChannelDetailResponse)
def update_channel(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelPutRequest,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    metadata = payload.model_dump(exclude_unset=True, exclude={"config"})
    try:
        result = service.update_channel_and_config(
            feature,
            channel_id,
            metadata,
            payload.config,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="logistics channel not found")
        return LogisticsChannelDetailResponse.model_validate(result)
    except ValueError as exc:
        _raise_service_error(exc)


# 功能：更新或保存 `update_channel_config` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `payload`（LogisticsChannelConfigUpdate）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{feature}/{channel_id}/config', response_model=LogisticsChannelDetailResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`service.update_config`、`_raise_service_error`、`HTTPException`、`LogisticsChannelDetailResponse.model_validate`、`router.put`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.put(
    "/{feature}/{channel_id}/config",
    response_model=LogisticsChannelDetailResponse,
)
def update_channel_config(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelConfigUpdate,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        result = service.update_config(feature, channel_id, payload)
    except ValueError as exc:
        _raise_service_error(exc)
    if result is None:
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return LogisticsChannelDetailResponse.model_validate(result)


# 功能：删除或清理 `delete_channel` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelOkResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.delete('/{feature}/{channel_id}', response_model=LogisticsChannelOkResponse)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`service.delete_channel`、`HTTPException`、`LogisticsChannelOkResponse`、`router.delete`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.delete("/{feature}/{channel_id}", response_model=LogisticsChannelOkResponse)
def delete_channel(
    feature: str,
    channel_id: int,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelOkResponse:
    feature = _require_feature_access(feature, user)
    if not service.delete_channel(feature, channel_id):
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return LogisticsChannelOkResponse(ok=True)


# 功能：创建或构建 `add_camera` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `payload`（LogisticsChannelMemberCreate）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.post('/{feature}/{channel_id}/cameras', response_model=LogisticsChannelDetailResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`service.add_existing_camera`、`service.create_camera_and_bind`、`LogisticsChannelDetailResponse.model_validate`、`_raise_service_error`、`router.post`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.post(
    "/{feature}/{channel_id}/cameras",
    response_model=LogisticsChannelDetailResponse,
)
def add_camera(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelMemberCreate,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        if payload.camera_id is not None:
            result = service.add_existing_camera(feature, channel_id, payload.camera_id)
        else:
            result = service.create_camera_and_bind(feature, channel_id, payload)
        return LogisticsChannelDetailResponse.model_validate(result)
    except ValueError as exc:
        _raise_service_error(exc)


# 功能：实现 `reorder_cameras` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `payload`（LogisticsChannelMemberOrder）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{feature}/{channel_id}/cameras/order', response_model=LogisticsChannelDetailResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`LogisticsChannelDetailResponse.model_validate`、`service.reorder_members`、`_raise_service_error`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put(
    "/{feature}/{channel_id}/cameras/order",
    response_model=LogisticsChannelDetailResponse,
)
def reorder_cameras(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelMemberOrder,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.reorder_members(feature, channel_id, payload.camera_ids)
        )
    except ValueError as exc:
        _raise_service_error(exc)


# 功能：实现 `move_camera` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{feature}/{channel_id}/cameras/{camera_id}', response_model=LogisticsChannelDetailResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`LogisticsChannelDetailResponse.model_validate`、`service.move_camera`、`_raise_service_error`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put(
    "/{feature}/{channel_id}/cameras/{camera_id}",
    response_model=LogisticsChannelDetailResponse,
)
def move_camera(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.move_camera(feature, camera_id, channel_id)
        )
    except ValueError as exc:
        _raise_service_error(exc)


# 功能：更新或保存 `set_camera_enabled` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
#   - `payload`（LogisticsChannelMemberEnabledUpdate）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelDetailResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{feature}/{channel_id}/cameras/{camera_id}/enabled',
#         response_model=LogisticsChannelDetailResponse)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`LogisticsChannelDetailResponse.model_validate`、`service.set_member_enabled`、`_raise_service_error`、`router.put`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.put(
    "/{feature}/{channel_id}/cameras/{camera_id}/enabled",
    response_model=LogisticsChannelDetailResponse,
)
def set_camera_enabled(
    feature: str,
    channel_id: int,
    camera_id: int,
    payload: LogisticsChannelMemberEnabledUpdate,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    feature = _require_feature_access(feature, user)
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.set_member_enabled(
                feature,
                channel_id,
                camera_id,
                payload.enabled,
            )
        )
    except ValueError as exc:
        _raise_service_error(exc)


# 功能：实现 `_require_channel_member` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `service`（未显式标注）：`service` 对应的业务输入值
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/logistics_channels.py` 的 `get_member_camera_config` 调用本符号；`AiVision/api/logistics_channels.py` 的
#         `update_member_camera_config` 调用本符号
#   - 内部调用：`_get_channel_or_404`、`any`、`int`、`channel.get`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def _require_channel_member(service, feature: str, channel_id: int, camera_id: int) -> dict:
    channel = _get_channel_or_404(service, feature, channel_id)
    if not any(
        int(member["camera_id"]) == camera_id
        for member in channel.get("members", [])
    ):
        raise HTTPException(status_code=404, detail="channel camera membership not found")
    return channel


# 功能：读取或查询 `get_member_camera_config` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：FeatureConfigResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{feature}/{channel_id}/cameras/{camera_id}/config', response_model=FeatureConfigResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`_require_channel_member`、`feature_service.get_config`、`all_specs`、`str`、`HTTPException`、`FeatureConfigResponse`、`router.get`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.get(
    "/{feature}/{channel_id}/cameras/{camera_id}/config",
    response_model=FeatureConfigResponse,
)
def get_member_camera_config(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
    feature_service=Depends(get_feature_config_service),
) -> FeatureConfigResponse:
    feature = _require_feature_access(feature, user)
    _require_channel_member(service, feature, channel_id, camera_id)
    result = feature_service.get_config(all_specs()[feature], str(camera_id))
    if result is None:
        raise HTTPException(status_code=404, detail="camera or config not found")
    return FeatureConfigResponse(**result)


# 功能：更新或保存 `update_member_camera_config` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
#   - `payload`（dict）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
#   - `feature_service`（未显式标注）：`feature_service` 对应的业务输入值；默认值为 `Depends(get_feature_config_service)`
# 返回：FeatureConfigResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{feature}/{channel_id}/cameras/{camera_id}/config', response_model=FeatureConfigResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`_require_channel_member`、`all_specs`、`spec.config_schema.model_validate(payload).model_dump`、`spec.config_schema.model_validate`、`HTTPException`、`feature_service.save_config`、`str`、`FeatureConfigResponse`
#          等共 11 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.put(
    "/{feature}/{channel_id}/cameras/{camera_id}/config",
    response_model=FeatureConfigResponse,
)
def update_member_camera_config(
    feature: str,
    channel_id: int,
    camera_id: int,
    payload: dict,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
    feature_service=Depends(get_feature_config_service),
) -> FeatureConfigResponse:
    feature = _require_feature_access(feature, user)
    _require_channel_member(service, feature, channel_id, camera_id)
    spec = all_specs()[feature]
    try:
        validated = spec.config_schema.model_validate(payload).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"validation error: {exc}") from exc
    result = feature_service.save_config(spec, str(camera_id), validated)
    if result is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return FeatureConfigResponse(**result)


# 功能：删除或清理 `remove_camera` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(require_admin)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelOkResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.delete('/{feature}/{channel_id}/cameras/{camera_id}', response_model=LogisticsChannelOkResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`service.remove_camera`、`HTTPException`、`LogisticsChannelOkResponse`、`router.delete`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.delete(
    "/{feature}/{channel_id}/cameras/{camera_id}",
    response_model=LogisticsChannelOkResponse,
)
def remove_camera(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(require_admin),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelOkResponse:
    feature = _require_feature_access(feature, user)
    if not service.remove_camera(feature, channel_id, camera_id):
        raise HTTPException(status_code=404, detail="channel camera membership not found")
    return LogisticsChannelOkResponse(ok=True)


# 功能：读取或查询 `get_channel_status` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值；默认值为 `Depends(get_current_orchestrator)`
# 返回：LogisticsChannelRuntimeStatusResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{feature}/{channel_id}/status', response_model=LogisticsChannelRuntimeStatusResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`_require_feature_access`、`_get_channel_or_404`、`orchestrator.get_logistics_channel_status`、`LogisticsChannelRuntimeStatusResponse.model_validate`、`channel.get`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get(
    "/{feature}/{channel_id}/status",
    response_model=LogisticsChannelRuntimeStatusResponse,
)
def get_channel_status(
    feature: str,
    channel_id: int,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
    orchestrator=Depends(get_current_orchestrator),
) -> LogisticsChannelRuntimeStatusResponse:
    feature = _require_feature_access(feature, user)
    channel = _get_channel_or_404(service, feature, channel_id)
    value = orchestrator.get_logistics_channel_status(feature, channel_id)
    if value is not None:
        return LogisticsChannelRuntimeStatusResponse.model_validate(value)
    return LogisticsChannelRuntimeStatusResponse.model_validate({
        "feature_name": feature,
        "channel_id": channel_id,
        "channel_name": channel["name"],
        "reason": "unknown",
        "alarm": False,
        "camera_ids": [member["camera_id"] for member in channel.get("members", [])],
        "camera_counts": {},
        "camera_states": {},
        "offending_camera_ids": [],
        "updated_at": None,
    })


# 功能：读取或查询 `get_channel_frame` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `quality`（int）：`quality` 对应的业务输入值；默认值为 `Query(85, ge=1, le=100)`
#   - `max_width`（int | None）：`max_width` 对应的业务输入值；默认值为 `Query(None, ge=1, le=4096)`
#   - `max_height`（int | None）：`max_height` 对应的业务输入值；默认值为 `Query(None, ge=1, le=4096)`
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值；默认值为 `Depends(get_current_orchestrator)`
# 返回：Response；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{feature}/{channel_id}/frame.jpg')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`Depends`、`_require_feature_access`、`_get_channel_or_404`、`orchestrator.get_logistics_channel_frame`、`HTTPException`、`encode_frame_to_jpeg`、`headers.update`、`frame_size_headers`、`Response`
#          等共 11 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.get("/{feature}/{channel_id}/frame.jpg")
def get_channel_frame(
    feature: str,
    channel_id: int,
    quality: int = Query(85, ge=1, le=100),
    max_width: int | None = Query(None, ge=1, le=4096),
    max_height: int | None = Query(None, ge=1, le=4096),
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
    orchestrator=Depends(get_current_orchestrator),
) -> Response:
    feature = _require_feature_access(feature, user)
    _get_channel_or_404(service, feature, channel_id)
    frame = orchestrator.get_logistics_channel_frame(feature, channel_id)
    if frame is None:
        raise HTTPException(status_code=503, detail="logistics channel frame not available")
    content = encode_frame_to_jpeg(
        frame,
        quality,
        max_width=max_width,
        max_height=max_height,
    )
    headers = {"Cache-Control": "no-store"}
    if max_width is None and max_height is None:
        headers.update(frame_size_headers(frame))
    return Response(
        content=content,
        media_type="image/jpeg",
        headers=headers,
    )


# 功能：实现 `_alarm_dict` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `row`（AiViolationImage）：`row` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/logistics_channels.py` 的 `list_channel_alarms` 调用本符号
#   - 内部调用：`str`、`(row.event_metadata or {}).get`、`int`、`row.create_time.isoformat`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _alarm_dict(row: AiViolationImage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "feature_name": (row.event_metadata or {}).get("feature_name"),
        "channel_id": int(row.subject_id),
        "channel_name": row.subject_name,
        "reason": row.reason,
        "created_at": row.create_time.isoformat(sep=" ") if row.create_time else None,
        "image_url": f"/api/alarms/{row.id}/image",
        "metadata": row.event_metadata or {},
    }


# 功能：读取或查询 `_channel_alarm_query` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `session`（未显式标注）：数据库会话或运行会话
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/logistics_channels.py` 的 `list_channel_alarms` 调用本符号；`AiVision/api/logistics_channels.py` 的
#         `channel_statistics` 调用本符号
#   - 内部调用：`session.query(AiViolationImage).filter`、`session.query`、`str`、`all_specs`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _channel_alarm_query(session, feature: str, channel_id: int):
    return session.query(AiViolationImage).filter(
        AiViolationImage.subject_type == "logistics_channel",
        AiViolationImage.subject_id == str(channel_id),
        AiViolationImage.violation_type == all_specs()[feature].violation_type,
    )


# 功能：读取或查询 `list_channel_alarms` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `limit`（int）：返回或处理的最大记录数；默认值为 `Query(200, ge=1, le=1000)`
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelAlarmListResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{feature}/{channel_id}/alarms', response_model=LogisticsChannelAlarmListResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`Depends`、`_require_feature_access`、`_get_channel_or_404`、`get_session`、`_channel_alarm_query(session, feature,
#          channel_id).order_by(AiViolationImage.create_time.desc(),
#          AiViolationImage.id.desc()).limit(limit).all`、`_channel_alarm_query(session, feature,
#          channel_id).order_by(AiViolationImage.create_time.desc(),
#          AiViolationImage.id.desc()).limit`、`_channel_alarm_query(session, feature,
#          channel_id).order_by`、`_channel_alarm_query`、`AiViolationImage.create_time.desc` 等共 15 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get(
    "/{feature}/{channel_id}/alarms",
    response_model=LogisticsChannelAlarmListResponse,
)
def list_channel_alarms(
    feature: str,
    channel_id: int,
    limit: int = Query(200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelAlarmListResponse:
    feature = _require_feature_access(feature, user)
    _get_channel_or_404(service, feature, channel_id)
    session = get_session()
    try:
        rows = _channel_alarm_query(session, feature, channel_id).order_by(
            AiViolationImage.create_time.desc(), AiViolationImage.id.desc()
        ).limit(limit).all()
        return LogisticsChannelAlarmListResponse.model_validate(
            {"items": [_alarm_dict(row) for row in rows]}
        )
    finally:
        session.close()


# 功能：实现 `channel_statistics` 对应的`logistics_channels` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `feature`（str）：`feature` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `days`（int）：`days` 对应的业务输入值；默认值为 `Query(7, ge=1, le=90)`
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `service`（未显式标注）：`service` 对应的业务输入值；默认值为 `Depends(get_logistics_channel_service)`
# 返回：LogisticsChannelStatisticsResponse；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{feature}/{channel_id}/statistics', response_model=LogisticsChannelStatisticsResponse)`
#         注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`Depends`、`_require_feature_access`、`_get_channel_or_404`、`dt.datetime.now`、`now.replace`、`dt.timedelta`、`get_session`、`_channel_alarm_query(session,
#          feature, channel_id).filter(AiViolationImage.create_time >=
#          range_start).order_by(AiViolationImage.create_time.asc()).all`、`_channel_alarm_query(session, feature,
#          channel_id).filter(AiViolationImage.create_time >= range_start).order_by` 等共 23 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
@router.get(
    "/{feature}/{channel_id}/statistics",
    response_model=LogisticsChannelStatisticsResponse,
)
def channel_statistics(
    feature: str,
    channel_id: int,
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelStatisticsResponse:
    feature = _require_feature_access(feature, user)
    _get_channel_or_404(service, feature, channel_id)
    now = dt.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = today_start - dt.timedelta(days=days - 1)
    session = get_session()
    try:
        rows = _channel_alarm_query(session, feature, channel_id).filter(
            AiViolationImage.create_time >= range_start
        ).order_by(AiViolationImage.create_time.asc()).all()
        counts: dict[str, int] = {}
        for row in rows:
            if row.create_time:
                key = row.create_time.strftime("%Y-%m-%d")
                counts[key] = counts.get(key, 0) + 1
        daily = []
        for offset in range(days):
            key = (range_start + dt.timedelta(days=offset)).strftime("%Y-%m-%d")
            daily.append({"day": key, "count": counts.get(key, 0)})
        return LogisticsChannelStatisticsResponse.model_validate({
            "summary": {
                "total": len(rows),
                "today": sum(1 for row in rows if row.create_time and row.create_time >= today_start),
            },
            "daily": daily,
        })
    finally:
        session.close()
