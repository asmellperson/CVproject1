# 文件说明：定义告警的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""报警记录与统计聚合接口。"""
from __future__ import annotations

import datetime as dt
import os
from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from AiVision.core.db import get_session
from AiVision.core.logger import logger
from AiVision.core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4
from AiVision.platform.camera.orm import AiCameraConfig
from AiVision.platform.violation.orm import AiAlarmEvent
from AiVision.platform.violation.types import (
    DEFAULT_ALARM_TYPE_META,
    VIOLATION_TYPE_META,
    department_for_feature,
    department_for_violation_type,
    feature_name_for_violation_type,
    normalize_violation_type,
)


router = APIRouter(prefix="/api/alarms", tags=["alarms"])
public_router = APIRouter(prefix="/api/public/alarms", tags=["alarms"])

# 告警类型只描述发生了什么；部门、公司和通道归属由独立字段表达。
_TYPE_META = VIOLATION_TYPE_META
_DEFAULT_META = DEFAULT_ALARM_TYPE_META
_MAX_CAMERA_ID = 2**31 - 1  # AiCameraConfig.id 使用有符号 SQL Integer。


# 功能：统一告警列表项，同时兼容旧摄像头告警和通道告警；输入与输出详见下方说明
# 参数：
#   - `id`（str）：`id` 对应业务对象的唯一标识
#   - `event_type`（str）：事件类型标识
#   - `event_label`（str）：`event_label` 对应的业务输入值
#   - `violation_type`（int | None）：`violation_type` 对应的业务输入值
#   - `feature_name`（str | None）：触发告警的具体检测功能
#   - `department`（str | None）：告警归属部门或公司
#   - `camera_no`（str）：`camera_no` 对应的业务输入值
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `subject_type`（str）：`subject_type` 对应的业务输入值
#   - `subject_id`（str | None）：`subject_id` 对应业务对象的唯一标识
#   - `subject_name`（str | None）：`subject_name` 对应的业务输入值
#   - `channel_id`（str | None）：`channel_id` 对应业务对象的唯一标识
#   - `channel_name`（str | None）：`channel_name` 对应的业务输入值
#   - `reason`（str）：`reason` 对应的业务输入值
#   - `status`（str | None）：当前或目标状态值
#   - `confidence`（float）：模型预测或规则判断的置信度
#   - `created_at`（str | None）：`created_at` 对应的业务输入值
#   - `image_path`（str | None）：`image_path` 对应的业务输入值
#   - `image_url`（str）：`image_url` 对应的业务输入值
#   - `video_path`（str | None）：`video_path` 对应的业务输入值
#   - `video_status`（str | None）：`video_status` 对应的业务输入值
#   - `camera_ids`（list[int]）：`camera_ids` 对应的业务输入值
#   - `camera_names`（dict[str, str]）：`camera_names` 对应的业务输入值
#   - `camera_counts`（dict[str, int | None]）：`camera_counts` 对应的业务输入值
#   - `camera_states`（dict[str, dict[str, Any]]）：`camera_states` 对应的业务输入值
#   - `offending_camera_ids`（list[int]）：`offending_camera_ids` 对应的业务输入值
#   - `evidence_error`（str | None）：`evidence_error` 对应的业务输入值
#   - `metadata`（dict[str, Any]）：`metadata` 对应的业务输入值
# 返回：AlarmEventResponse；返回新建的 `AlarmEventResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AlarmEventResponse(BaseModel):
    """统一告警列表项，同时兼容旧摄像头告警和通道告警。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    event_type: str
    event_label: str
    violation_type: int | None = None
    feature_name: str | None = None
    department: str | None = None
    camera_no: str | None = None
    camera_name: str | None = None
    subject_type: str
    subject_id: str | None = None
    subject_name: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    reason: str
    status: str | None = None
    confidence: float = 1
    created_at: str | None = None
    image_path: str | None = None
    image_url: str
    video_path: str | None = None
    video_status: str | None = None
    camera_ids: list[int] = Field(default_factory=list)
    camera_names: dict[str, str] = Field(default_factory=dict)
    camera_counts: dict[str, int | None] = Field(default_factory=dict)
    camera_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    offending_camera_ids: list[int] = Field(default_factory=list)
    evidence_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# 功能：定义 `AlarmListResponse` 类，封装告警相关的状态、约束与操作
# 参数：
#   - `items`（list[AlarmEventResponse]）：`items` 对应的业务输入值
# 返回：AlarmListResponse；返回新建的 `AlarmListResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AlarmListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AlarmEventResponse] = Field(default_factory=list)


# 功能：实现 `_meta` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `violation_type`（int | None）：`violation_type` 对应的业务输入值
# 返回：dict[str, str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/alarms.py` 的 `_event_dict` 调用本符号；`AiVision/api/alarms.py` 的 `alarm_statistics` 调用本符号
#   - 内部调用：`_TYPE_META.get`、`int`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _meta(violation_type: int | None) -> dict[str, str]:
    return _TYPE_META.get(normalize_violation_type(violation_type), _DEFAULT_META)


# 功能：查询摄像头主体详情，用于补齐历史告警；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `session`（未显式标注）：数据库会话或运行会话
# 返回：dict[str, dict[str, str | None]]；返回摄像头名称与部门映射。
# 调用关系：
#   - 调用方：`AiVision/api/alarms.py` 的 `list_alarms` 调用本符号；`AiVision/api/alarms.py` 的 `alarm_statistics` 调用本符号
#   - 内部调用：`session.query(AiCameraConfig.shm_name, AiCameraConfig.name).all`、`session.query`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _camera_details(session) -> dict[str, dict[str, str | None]]:
    rows = session.query(
        AiCameraConfig.shm_name,
        AiCameraConfig.name,
        AiCameraConfig.department,
    ).all()
    return {
        shm: {"name": name, "department": department}
        for shm, name, department in rows
        if shm
    }


def _camera_detail(cameras: dict[str, Any], camera_no: str) -> dict[str, str | None]:
    """兼容测试与旧调用方传入的 camera_no→name 简写映射。"""
    detail = cameras.get(camera_no)
    if isinstance(detail, dict):
        return {
            "name": str(detail.get("name")) if detail.get("name") is not None else None,
            "department": (
                str(detail.get("department"))
                if detail.get("department") is not None
                else None
            ),
        }
    if detail is not None:
        return {"name": str(detail), "department": None}
    return {"name": None, "department": None}


# 功能：实现 `_dict_value` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/alarms.py` 的 `_channel_alarm_fields` 调用本符号
#   - 内部调用：`isinstance`、`str`、`value.items`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _dict_value(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


# 功能：读取或查询 `_int_list` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（object）：待转换、校验或写入的值
# 返回：list[int]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/alarms.py` 的 `_channel_alarm_fields` 调用本符号
#   - 内部调用：`isinstance`、`set`、`item.strip`、`any`、`int`、`seen.add`、`result.append`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            camera_id = item
        elif isinstance(item, str):
            normalized = item.strip()
            if not normalized or any(char not in "0123456789" for char in normalized):
                continue
            try:
                camera_id = int(normalized)
            except (ValueError, OverflowError):
                continue
        else:
            continue
        if not 1 <= camera_id <= _MAX_CAMERA_ID or camera_id in seen:
            continue
        seen.add(camera_id)
        result.append(camera_id)
    return result


# 功能：实现 `_channel_alarm_fields` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `metadata`（dict[str, Any]）：`metadata` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/alarms.py` 的 `_event_dict` 调用本符号
#   - 内部调用：`_dict_value`、`metadata.get`、`dict`、`raw_states.items`、`isinstance`、`raw_counts.items`、`str`、`explicit_names.items`、`camera_states.items`、`state.get`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _channel_alarm_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    raw_states = _dict_value(metadata.get("camera_states"))
    camera_states = {
        key: dict(value)
        for key, value in raw_states.items()
        if isinstance(value, dict)
    }
    raw_counts = _dict_value(metadata.get("camera_counts"))
    camera_counts: dict[str, int | None] = {}
    for key, value in raw_counts.items():
        if value is None:
            camera_counts[key] = None
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            camera_counts[key] = value

    explicit_names = _dict_value(metadata.get("camera_names"))
    camera_names = {
        key: str(value)
        for key, value in explicit_names.items()
        if value is not None
    }
    for key, state in camera_states.items():
        if state.get("camera_name") is not None:
            camera_names.setdefault(key, str(state["camera_name"]))
    evidence_error = metadata.get("evidence_error")
    return {
        "camera_ids": _int_list(metadata.get("camera_ids")),
        "camera_names": camera_names,
        "camera_counts": camera_counts,
        "camera_states": camera_states,
        "offending_camera_ids": _int_list(metadata.get("offending_camera_ids")),
        "evidence_error": str(evidence_error) if evidence_error is not None else None,
    }


# 功能：实现 `_event_dict` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `row`（AiAlarmEvent）：`row` 对应的业务输入值
#   - `cameras`（dict[str, Any]）：摄像头主体详情映射
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/alarms.py` 的 `list_alarms` 调用本符号；`AiVision/api/alarms.py` 的 `alarm_statistics` 调用本符号
#   - 内部调用：`_meta`、`getattr`、`isinstance`、`dict`、`str`、`metadata.get`、`cameras.get`、`create_time.isoformat`、`_channel_alarm_fields`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _event_dict(row: AiAlarmEvent, cameras: dict[str, Any]) -> dict[str, Any]:
    """把数据库告警事件转换成以 subject 为主语义的接口记录。"""
    raw_violation_type = getattr(row, "violation_type", None)
    violation_type = normalize_violation_type(raw_violation_type)
    meta = _meta(raw_violation_type)
    raw_metadata = getattr(row, "event_metadata", None)
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    subject_type = str(getattr(row, "subject_type", None) or "camera")
    subject_id = getattr(row, "subject_id", None)
    subject_name = getattr(row, "subject_name", None)
    persisted_reason = getattr(row, "reason", None)
    raw_camera_no = str(getattr(row, "camera_no", None) or "")
    camera_detail = _camera_detail(cameras, raw_camera_no)
    is_channel = subject_type == "logistics_channel"

    feature_name = str(
        getattr(row, "feature_name", None)
        or metadata.get("feature_name")
        or feature_name_for_violation_type(raw_violation_type)
        or meta["event_type"]
    )
    department = str(
        getattr(row, "department", None)
        or metadata.get("department")
        or camera_detail.get("department")
        or department_for_feature(feature_name)
        or department_for_violation_type(raw_violation_type)
        or ""
    ) or None

    camera_no = (raw_camera_no or None) if not is_channel else None
    camera_name = None
    channel_id = None
    channel_name = None
    if is_channel:
        channel_id_value = subject_id if subject_id is not None else metadata.get("channel_id")
        channel_id = str(channel_id_value) if channel_id_value is not None else None
        channel_name = str(
            subject_name
            or metadata.get("channel_name")
            or "物流通道"
        )
        subject_id = channel_id
        subject_name = channel_name
    else:
        camera_name = str(
            subject_name
            or camera_detail.get("name")
            or camera_no
            or "未知摄像头"
        )
        subject_id = subject_id if subject_id is not None else camera_no
        subject_name = subject_name if subject_name is not None else camera_name

    display_subject = str(subject_name or "未知主体")
    reason = str(
        persisted_reason
        or metadata.get("reason")
        or f"{meta['label']} - {display_subject}"
    )
    create_time = getattr(row, "create_time", None)
    created_at = create_time.isoformat(sep=" ") if create_time else None
    return {
        "id": str(row.id),
        "event_type": meta["event_type"],
        "event_label": meta["label"],
        "violation_type": violation_type,
        "feature_name": feature_name,
        "department": department,
        "camera_no": camera_no,
        "camera_name": camera_name,
        "subject_type": subject_type,
        "subject_id": str(subject_id) if subject_id is not None else None,
        "subject_name": str(subject_name) if subject_name is not None else None,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "reason": reason,
        "status": reason if is_channel else None,
        "confidence": 1,
        "created_at": created_at,
        "image_path": row.image_path,
        "image_url": f"/api/alarms/{row.id}/image",
        "video_path": getattr(row, "video_path", None),
        "video_status": getattr(row, "video_status", None),
        **_channel_alarm_fields(metadata),
        "metadata": metadata,
    }


# 功能：读取或查询 `list_alarms` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `limit`（int）：返回或处理的最大记录数；默认值为 `Query(200, ge=1, le=1000)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('', response_model=AlarmListResponse)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`get_session`、`_camera_details`、`session.query(AiAlarmEvent).order_by(AiAlarmEvent.create_time.desc(),
#          AiAlarmEvent.id.desc()).limit(limit).all`、`session.query(AiAlarmEvent).order_by(AiAlarmEvent.create_time.desc(),
#          AiAlarmEvent.id.desc()).limit`、`session.query(AiAlarmEvent).order_by`、`session.query`、`AiAlarmEvent.create_time.desc`、`AiAlarmEvent.id.desc`、`_event_dict`
#          等共 12 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("", response_model=AlarmListResponse)
def list_alarms(limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    session = get_session()
    try:
        cameras = _camera_details(session)
        rows = (
            session.query(AiAlarmEvent)
            .order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc())
            .limit(limit)
            .all()
        )
        return {"items": [_event_dict(row, cameras) for row in rows]}
    finally:
        session.close()


# 功能：实现 `alarm_image` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm_id`（int）：`alarm_id` 对应业务对象的唯一标识
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{alarm_id}/image')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`get_session`、`session.query(AiAlarmEvent).filter(AiAlarmEvent.id ==
#          alarm_id).first`、`session.query(AiAlarmEvent).filter`、`session.query`、`HTTPException`、`os.path.exists`、`FileResponse`、`session.close`、`router.get`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.get("/{alarm_id}/image")
def alarm_image(alarm_id: int):
    session = get_session()
    try:
        row = session.query(AiAlarmEvent).filter(AiAlarmEvent.id == alarm_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        if not row.image_path or not os.path.exists(row.image_path):
            raise HTTPException(status_code=404, detail="alarm image not found")
        return FileResponse(row.image_path, media_type="image/png")
    finally:
        session.close()


@public_router.get("/{alarm_id}/image")
def public_alarm_image(alarm_id: int):
    """提供企业微信卡片可直接访问的告警图片。"""
    return alarm_image(alarm_id)


# 功能：实现 `alarm_video` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `alarm_id`（int）：`alarm_id` 对应业务对象的唯一标识
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{alarm_id}/video')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`get_session`、`session.query(AiAlarmEvent).filter(AiAlarmEvent.id ==
#          alarm_id).first`、`session.query(AiAlarmEvent).filter`、`session.query`、`HTTPException`、`getattr`、`os.path.exists`、`ensure_browser_compatible_mp4`、`logger.warning`、`FileResponse`
#          等共 12 个调用。
# 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
@router.get("/{alarm_id}/video")
def alarm_video(alarm_id: int):
    session = get_session()
    try:
        row = session.query(AiAlarmEvent).filter(AiAlarmEvent.id == alarm_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        if getattr(row, "video_status", None) != "ready":
            raise HTTPException(status_code=404, detail="alarm video is not ready")
        video_path = getattr(row, "video_path", None)
        if not video_path or not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="alarm video not found")
        try:
            compatible_path = ensure_browser_compatible_mp4(video_path)
        except VideoEncodingError as exc:
            logger.warning(f"[AlarmVideo] 浏览器兼容转换失败 alarm_id={alarm_id}: {exc}")
            raise HTTPException(status_code=500, detail="alarm video is not browser compatible") from exc
        return FileResponse(compatible_path, media_type="video/mp4")
    finally:
        session.close()


# 功能：实现 `alarm_statistics` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `days`（int）：`days` 对应的业务输入值；默认值为 `Query(7, ge=1, le=90)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/statistics/summary')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`dt.datetime.now`、`now.replace`、`dt.timedelta`、`get_session`、`_camera_details`、`session.query(AiAlarmEvent).filter(AiAlarmEvent.create_time
#          >=
#          range_start).order_by(AiAlarmEvent.create_time.asc()).all`、`session.query(AiAlarmEvent).filter(AiAlarmEvent.create_time
#          >= range_start).order_by`、`session.query(AiAlarmEvent).filter`、`session.query` 等共 35 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
@router.get("/statistics/summary")
def alarm_statistics(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    """查询最近 N 天告警，按类型、主体、日期和小时聚合。"""
    now = dt.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = today_start - dt.timedelta(days=days - 1)

    session = get_session()
    try:
        cameras = _camera_details(session)
        rows = (
            session.query(AiAlarmEvent)
            .filter(AiAlarmEvent.create_time >= range_start)
            .order_by(AiAlarmEvent.create_time.asc())
            .all()
        )

        total = len(rows)
        today = sum(1 for row in rows if row.create_time and row.create_time >= today_start)
        type_counts = Counter(normalize_violation_type(row.violation_type) for row in rows)
        subject_counts: Counter[tuple[str, str]] = Counter()
        subject_names: dict[tuple[str, str], str] = {}
        for row in rows:
            event = _event_dict(row, cameras)
            subject_type = str(event["subject_type"] or "unknown")
            subject_id = str(event["subject_id"] or event["subject_name"] or "unknown")
            subject_key = (subject_type, subject_id)
            subject_counts[subject_key] += 1
            subject_names[subject_key] = str(event["subject_name"] or subject_id)
        hourly_counts = Counter(row.create_time.hour for row in rows if row.create_time)
        daily_by_type: dict[str, Counter[int]] = defaultdict(Counter)
        hourly_by_type: dict[int, Counter[int]] = defaultdict(Counter)

        for row in rows:
            if not row.create_time:
                continue
            day_key = row.create_time.strftime("%m-%d")
            violation_type = normalize_violation_type(row.violation_type)
            daily_by_type[day_key][violation_type] += 1
            hourly_by_type[row.create_time.hour][violation_type] += 1

        daily = []
        for offset in range(days):
            day = range_start + dt.timedelta(days=offset)
            key = day.strftime("%m-%d")
            bucket = daily_by_type.get(key, Counter())
            daily.append({
                "day": key,
                "total": sum(bucket.values()),
                **{_meta(vtype)["event_type"]: count for vtype, count in bucket.items()},
            })

        hourly = []
        for hour in range(24):
            bucket = hourly_by_type.get(hour, Counter())
            hourly.append({
                "time": f"{hour:02d}:00",
                "total": sum(bucket.values()),
                **{_meta(vtype)["event_type"]: count for vtype, count in bucket.items()},
            })

        by_type = [
            {
                "event_type": meta["event_type"],
                "name": meta["label"],
                "value": type_counts.get(vtype, 0),
            }
            for vtype, meta in _TYPE_META.items()
            if type_counts.get(vtype, 0) > 0
        ]

        by_subject = [
            {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "subject_name": subject_names.get((subject_type, subject_id), subject_id),
                "value": value,
            }
            for (subject_type, subject_id), value in subject_counts.most_common(8)
        ]

        peak_hour = hourly_counts.most_common(1)[0][0] if hourly_counts else None
        return {
            "summary": {
                "total": total,
                "today": today,
                "avg_per_day": round(total / days, 2),
                "active_subjects": len(subject_counts),
                "peak_hour": f"{peak_hour:02d}:00" if peak_hour is not None else "-",
            },
            "by_type": by_type,
            "by_subject": by_subject,
            "daily": daily,
            "hourly": hourly,
            "recent": [_event_dict(row, cameras) for row in rows[-8:]][::-1],
        }
    finally:
        session.close()
