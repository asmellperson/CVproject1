"""物流通道 CRUD、成员、运行状态和拼接画面 API。"""
from __future__ import annotations
from AiVision.departments.department_registry import require_department

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from auth.auth import get_current_user, require_config_manager
from auth.feature_permissions import feature_departments, require_feature_access
from AiVision.api.deps import (
    get_current_orchestrator,
    get_logistics_channel_service,      # 物流通道配置和成员关系管理器
    get_camera_config_manager,
)
from AiVision.api.routes.cameras import encode_frame_to_jpeg, frame_size_headers, get_camera_for_user
from AiVision.core.db import get_session
from AiVision.features.logistics_channel.constants import (
    LOGISTICS_FEATURES,                                 # # 系统哪些功能属于物流通道类功能                             
)
from AiVision.features.logistics_channel.schedule import LogisticsSchedule, is_scheduled_time
from AiVision.features.logistics_channel.schema import (
    LogisticsChannelAlarmListResponse,                  # 物流通道报警数据模型
    LogisticsCameraInventoryResponse,                   # 用户有权看到的物流摄像头汇总
    LogisticsChannelCreate,                             # 创建通道的数据模型
    LogisticsChannelDetailResponse,                     # 通道的详情信息的数据模型
    LogisticsChannelListResponse,                       # 一组通道的数据模型
    LogisticsChannelMemberCreate,                       # 添加摄像头的数据模型
    LogisticsChannelMemberEnabledUpdate,                # 启用和禁用摄像头的数据模型
    LogisticsChannelMemberOrder,                        # 调整摄像头顺序的数据模型
    LogisticsChannelOkResponse,                         # 
    LogisticsChannelRuntimeStatusResponse,              # 通道当前运行状态的数据模型
    LogisticsChannelStatisticsResponse,                 # 通道告警统计的数据模型
    LogisticsCameraRoiResponse, LogisticsCameraRoiUpdate,
    LogisticsChannelPatchRequest,                       # 修改通道时
)
from AiVision.alarms.records.orm import AiAlarmEvent


router = APIRouter(prefix="/api/logistics-channels", tags=["logistics-channels"])

def _accessible_departments(user: dict) -> tuple[str, ...]:
    """只返回已分配物流功能的事业部，空元组表示无访问权限。"""
    return tuple(feature_departments(user, "detect_logistics_single_person"))


def _require_feature_access(feature: str) -> str:
    """只校验物流功能是否合法；事业部授权以 Channel 为准。"""
    if feature not in LOGISTICS_FEATURES:
        raise HTTPException(status_code=404, detail="logistics feature not found")
    return feature


def _query_departments(user: dict, department: str | None) -> tuple[str, ...]:
    """页面事业部与用户授权取交集，交给 service 在数据库层过滤。"""
    accessible = _accessible_departments(user)
    if department is None:
        return accessible
    try:
        require_department(department)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if department not in accessible:
        raise HTTPException(status_code=403, detail="department permission required")
    return (department,)


def _require_channel_access(service, feature: str, channel_id: int, user: dict) -> dict:
    """先校验物流功能和通道存在，再核对通道事业部的功能授权。"""
    _require_feature_access(feature)
    channel = _get_channel_or_404(service, feature, channel_id)
    departments = _accessible_departments(user)
    if channel["department"] not in departments:
        raise HTTPException(status_code=403, detail="channel department permission required")
    return channel

def _raise_service_error(exc: ValueError) -> None:
    """把service层抛出来的ValueError，转换成合适的HTTP错误
        物流通道不存在转成404
        当前请求和已有资源冲突，转成409
        其他的统一400
    """
    detail = str(exc)
    if "不存在" in detail:
        code = status.HTTP_404_NOT_FOUND
    elif any(marker in detail for marker in ("已存在", "已绑定", "约束冲突", "最多", "上限")):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=detail) from exc

def _get_channel_or_404(service, feature: str, channel_id: int) -> dict:
    """查询指定通道，不存在统一返回404"""
    channel = service.get_channel(feature, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return channel

# inventory:摄像头总清单
@router.get("/inventory", response_model=LogisticsCameraInventoryResponse)
def list_logistics_camera_inventory(
    user: dict = Depends(get_current_user),             # 当前登录用户
    service=Depends(get_logistics_channel_service),     # 物流通道管理服务
    orchestrator=Depends(get_current_orchestrator),     
    department: Annotated[str | None, Query()] = None,
) -> LogisticsCameraInventoryResponse:
    """返回授权范围内的物流摄像头及通道运行状态。"""
    items = service.camera_inventory_status(_query_departments(user, department), orchestrator)
    return LogisticsCameraInventoryResponse.model_validate({"items": items})

@router.get("/{feature}", response_model=LogisticsChannelListResponse)
def list_channels(
    feature: str,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
    department: Annotated[str | None, Query()] = None,
) -> LogisticsChannelListResponse:
    """查询一个物流feature下的通道列表"""
    return LogisticsChannelListResponse.model_validate(
        service.list_channels(_require_feature_access(feature), departments=_query_departments(user, department))
    )

@router.post(
    "/{feature}",
    status_code=status.HTTP_201_CREATED,              # 新建资源的响应是201 Created
    response_model=LogisticsChannelDetailResponse,
)
def create_channel(
    feature: str,
    payload: LogisticsChannelCreate,                  # 前端创建提交的数据
    user: dict = Depends(require_config_manager),              # 必须是管理员（get_current_user这个是查询，登录就有）
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    """新建一个物流通道"""
    # 功能权限校验
    feature = _require_feature_access(feature)
    require_feature_access(user, feature, payload.department)
    try:
        # 调用通道管理服务去新建通道，并且做参数校验
        return LogisticsChannelDetailResponse.model_validate(
            service.create_channel(feature, payload.name, payload.department)
        )
    except ValueError as exc:
        _raise_service_error(exc)

@router.get("/{feature}/{channel_id}", response_model=LogisticsChannelDetailResponse)
def get_channel(
    feature: str,
    channel_id: int,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    """查询一个具体通道的完整详情"""
    return LogisticsChannelDetailResponse.model_validate(
        _require_channel_access(service, feature, channel_id, user)
    )

@router.patch("/{feature}/{channel_id}", response_model=LogisticsChannelDetailResponse)
def update_channel(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelPatchRequest,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    """修改物流通道基础信息和通道级检测配置"""
    # 功能权限
    _require_channel_access(service, feature, channel_id, user)
    # metadata：exclude_unset=True：前端没有主动提交的字段，不要拿默认值去覆盖数据库(局部更新语义)
    metadata = payload.model_dump(exclude_unset=True, exclude={"config"})
    try:
        # 更新通道的基础信息
        result = service.update_channel_and_config(
            feature,
            channel_id,
            metadata,
            payload.config,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="logistics channel not found")
        # 做数据校验
        return LogisticsChannelDetailResponse.model_validate(result)
    except ValueError as exc:
        _raise_service_error(exc)

@router.delete("/{feature}/{channel_id}", response_model=LogisticsChannelOkResponse)
def delete_channel(
    feature: str,
    channel_id: int,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelOkResponse:
    """删除指定物流通道"""
    _require_channel_access(service, feature, channel_id, user)
    if not service.delete_channel(feature, channel_id):      # 删除指定物流通道返回布尔值
        raise HTTPException(status_code=404, detail="logistics channel not found")
    return LogisticsChannelOkResponse(ok=True)

@router.post(
    "/{feature}/{channel_id}/cameras",
    response_model=LogisticsChannelDetailResponse,
)
def add_camera(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelMemberCreate,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
    manager=Depends(get_camera_config_manager),
) -> LogisticsChannelDetailResponse:
    """
    给某个物流通道添加成员摄像头
    支持两种方式：
        1、把已经存在的摄像头加入通道
        2、直接新建一台摄像头，并立即加入通道
    """
    channel = _require_channel_access(service, feature, channel_id, user)
    if payload.camera_id is not None:
        camera = get_camera_for_user(manager, payload.camera_id, user)
        if camera["department"] != channel["department"]:
            raise HTTPException(403, "摄像头和通道必须属于同一事业部")
    try:
        if payload.camera_id is not None:
            # 已经存在的摄像头加入通道
            result = service.add_existing_camera(feature, channel_id, payload.camera_id)
        else:
            # 新建一台摄像头立即加入通道
            result = service.create_camera_and_bind(feature, channel_id, payload)
        return LogisticsChannelDetailResponse.model_validate(result)
    except ValueError as exc:
        _raise_service_error(exc)

@router.put(
    "/{feature}/{channel_id}/cameras/order",
    response_model=LogisticsChannelDetailResponse,
)
def reorder_cameras(
    feature: str,
    channel_id: int,
    payload: LogisticsChannelMemberOrder,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    """
    重新调整某个物流通道内成员摄像头的顺序，拼接画面的顺序
    """
    _require_channel_access(service, feature, channel_id, user)
    try:
        # 调整顺序并校验
        return LogisticsChannelDetailResponse.model_validate(
            service.reorder_members(feature, channel_id, payload.camera_ids)
        )
    except ValueError as exc:
        _raise_service_error(exc)

@router.put(
    "/{feature}/{channel_id}/cameras/{camera_id}",
    response_model=LogisticsChannelDetailResponse,
)
def move_camera(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
    manager=Depends(get_camera_config_manager),
) -> LogisticsChannelDetailResponse:
    "把一个摄像头从一个通道搬到另一个通道"
    channel = _require_channel_access(service, feature, channel_id, user)
    camera = get_camera_for_user(manager, camera_id, user)
    if camera["department"] != channel["department"]:
        raise HTTPException(403, "摄像头和通道必须属于同一事业部")
    try:
        return LogisticsChannelDetailResponse.model_validate(
            service.move_camera(feature, camera_id, channel_id)
        )
    except ValueError as exc:
        _raise_service_error(exc)

@router.put(
    "/{feature}/{channel_id}/cameras/{camera_id}/enabled",
    response_model=LogisticsChannelDetailResponse,
)
def set_camera_enabled(
    feature: str,
    channel_id: int,
    camera_id: int,
    payload: LogisticsChannelMemberEnabledUpdate,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelDetailResponse:
    "设置摄像头在当前物流通道开启工作还是不开启工作"
    _require_channel_access(service, feature, channel_id, user)
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

@router.get(
    "/{feature}/{channel_id}/cameras/{camera_id}/roi",
    response_model=LogisticsCameraRoiResponse,
)
def get_member_camera_roi(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(get_current_user),
    service=Depends(get_logistics_channel_service),
) -> LogisticsCameraRoiResponse:
    """校验通道访问权后返回成员摄像头的唯一 ROI。"""
    _require_channel_access(service, feature, channel_id, user)
    try:
        return LogisticsCameraRoiResponse.model_validate(service.get_camera_roi(feature, channel_id, camera_id))
    except ValueError as exc:
        _raise_service_error(exc)


@router.put(
    "/{feature}/{channel_id}/cameras/{camera_id}/roi",
    response_model=LogisticsCameraRoiResponse,
)
def update_member_camera_roi(
    feature: str,
    channel_id: int,
    camera_id: int,
    payload: LogisticsCameraRoiUpdate,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
) -> LogisticsCameraRoiResponse:
    """管理员校验通道访问权后更新成员 ROI，业务冲突按统一规则返回。"""
    _require_channel_access(service, feature, channel_id, user)
    try:
        return LogisticsCameraRoiResponse.model_validate(
            service.update_camera_roi(feature, channel_id, camera_id, payload.model_dump()),
        )
    except ValueError as exc:
        _raise_service_error(exc)


@router.delete(
    "/{feature}/{channel_id}/cameras/{camera_id}",
    response_model=LogisticsChannelOkResponse,
)
def remove_camera(
    feature: str,
    channel_id: int,
    camera_id: int,
    user: dict = Depends(require_config_manager),
    service=Depends(get_logistics_channel_service),
) -> LogisticsChannelOkResponse:
    """把摄像头从当前物流通道中移除"""
    _require_channel_access(service, feature, channel_id, user)
    if not service.remove_camera(feature, channel_id, camera_id):
        raise HTTPException(status_code=404, detail="channel camera membership not found")
    return LogisticsChannelOkResponse(ok=True)

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
    """获取物流通道实时状态，尚无快照时仍返回完整的状态结构。"""
    channel = _require_channel_access(service, feature, channel_id, user)
    value = orchestrator.get_logistics_channel_status(feature, channel_id)
    if value is not None:
        return LogisticsChannelRuntimeStatusResponse.model_validate(value)
    return LogisticsChannelRuntimeStatusResponse.model_validate({
        "feature_name": feature,
        "channel_id": channel_id,
        "channel_name": channel["name"],
        "department": channel["department"],
        "reason": "unknown",
        "alarm": False,
        "alarm_suppressed": not channel["enabled"] or not is_scheduled_time(
            LogisticsSchedule.model_validate(channel["config"]["schedule"])
        ),
        "camera_ids": [member["camera_id"] for member in channel.get("members", [])],
        "camera_counts": {},
        "camera_states": {},
        "offending_camera_ids": [],
        "updated_at": None,
    })

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
    """返回整个物流通道多摄像头拼接预览画面"""
    _require_channel_access(service, feature, channel_id, user)
    frame = orchestrator.get_logistics_channel_frame(feature, channel_id)
    if frame is None:
        raise HTTPException(status_code=503, detail="logistics channel frame not available")
    content = encode_frame_to_jpeg(
        frame,
        quality,
        max_width=max_width,
        max_height=max_height,
    )
    # 浏览器不要缓存这张实时预览图
    headers = {"Cache-Control": "no-store"}
    if max_width is None and max_height is None:
        headers.update(frame_size_headers(frame))
    return Response(
        content=content,
        media_type="image/jpeg",
        headers=headers,
    )

def _alarm_dict(row: AiAlarmEvent) -> dict[str, Any]:
    """把数据库的一条物流通道告警转换成物流API返回格式"""
    metadata = row.event_metadata or {}
    return {
        "id": str(row.id),
        "feature_name": row.feature_name,
        "department": row.department,
        "channel_id": int(row.subject_id),
        "channel_name": row.subject_name,
        "reason": row.reason,
        "created_at": row.create_time.isoformat(sep=" ") if row.create_time else None,
        "image_url": f"/api/alarms/{row.id}/image",
        "metadata": metadata,
    }

def _channel_alarm_query(session, feature: str, channel_id: int):
    """只查询当前物流通道当前这个物流功能的告警"""
    return session.query(AiAlarmEvent).filter(
        AiAlarmEvent.subject_type == "logistics_channel",
        AiAlarmEvent.subject_id == str(channel_id),
        AiAlarmEvent.feature_name == feature,
    )

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
    """查询一个物流通道自己的历史告警记录"""
    _require_channel_access(service, feature, channel_id, user)
    session = get_session()
    try:
        rows = _channel_alarm_query(session, feature, channel_id).order_by(
            AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()
        ).limit(limit).all()
        return LogisticsChannelAlarmListResponse.model_validate(
            {"items": [_alarm_dict(row) for row in rows]}
        )
    finally:
        session.close()

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
    """统计某个物流通道最近N天的告警趋势"""
    _require_channel_access(service, feature, channel_id, user)
    now = dt.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = today_start - dt.timedelta(days=days - 1)
    session = get_session()
    try:
        rows = _channel_alarm_query(session, feature, channel_id).filter(
            AiAlarmEvent.create_time >= range_start
        ).order_by(AiAlarmEvent.create_time.asc()).all()
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
