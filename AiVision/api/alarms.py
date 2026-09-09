"""报警记录与统计聚合接口。"""
from __future__ import annotations

import datetime as dt
import os
from collections import Counter, defaultdict                        # 自动计数字典，主要用于告警类型统计、摄像头告警排行、小时告警统计
from typing import Any

from fastapi import APIRouter, HTTPException, Query                # Query:URL查询参数
from fastapi.responses import FileResponse                         # FileResponse：直接把磁盘上的文件作为HTTP响应返回
from pydantic import BaseModel, ConfigDict, Field                  # ConfigDict：API数据库严格模式，Field:字段默认值

from AiVision.core.db import get_session                           # 获取数据库操作会话
from AiVision.core.logger import logger                            # AiVision统一日志记录器
from AiVision.core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4      # ensure_brower_compatible_mp4:确保这个报警视频是浏览器可以直接播放的MP4（浏览器通常更喜欢MP4容器+H.264视频编码）
from AiVision.platform.violation.orm import AiAlarmEvent           # 完整告警事件数据库映射
from AiVision.platform.violation.types import (
    DEFAULT_ALARM_TYPE_META,
    VIOLATION_TYPE_META,
)


router = APIRouter(prefix="/api/alarms", tags=["alarms"])
public_router = APIRouter(prefix="/api/public/alarms", tags=["alarms"])      # 不需要正常登录认证的公开接口，主要用途是企业微信报警消息里的图片链接可以直接打开

# 告警类型只描述发生了什么；部门、公司和通道归属由独立字段表达。
_TYPE_META = VIOLATION_TYPE_META
_DEFAULT_META = DEFAULT_ALARM_TYPE_META
# 允许的最大摄像头ID，摄像头ID不能超过Integer能表示的最大值 
_MAX_CAMERA_ID = 2**31 - 1  

class AlarmEventResponse(BaseModel):
    """统一告警列表项，同时兼容旧摄像头告警和通道告警。"""

    model_config = ConfigDict(extra="forbid")       # 不允许返回模型没有定义的额外字段（严格约束API返回格式）

    id: str
    event_type: str
    event_label: str
    violation_type: int | None = None
    feature_name: str | None = None
    department: str | None = None
    camera_no: str | None = None                    # 仅摄像头主体使用的内部标识
    camera_name: str | None = None                  # 仅摄像头主体使用的展示名称
    subject_type: str                               # 这条告警属于哪个业务，可能是摄像头，可能是物流通道
    subject_id: str | None = None
    subject_name: str | None = None
    channel_id: str | None = None                  # 如果是物流通道告警，物流通道的id
    channel_name: str | None = None                # 物流通道的名字
    reason: str                                    # 具体为什么报警
    status: str | None = None                      # 主要给某些通道类告警提供的状态信息
    confidence: float = 1                          # 告警置信度（感觉好像没什么用）
    created_at: str | None = None                  # 时间
    image_path: str | None = None                  # 图片路径
    image_url: str                                 # 前端能访问图片的HTTP地址
    video_path: str | None = None                 
    video_status: str | None = None                # 告警视频的状态（pending、ready、failed）
    # 物流通道多摄像头告警字段
    camera_ids: list[int] = Field(default_factory=list)   # 参与当前通道的摄像头ID
    camera_names: dict[str, str] = Field(default_factory=dict) # 摄像头名称
    camera_counts: dict[str, int | None] = Field(default_factory=dict)  # 每台摄像头检测到的人数
    camera_states: dict[str, dict[str, Any]] = Field(default_factory=dict)  # 每台摄像头的运行信息
    offending_camera_ids: list[int] = Field(default_factory=list)           # 真正触发违规摄像头的ID

    evidence_error: str | None = None                                       # 告警视频保存中有没有出错
    metadata: dict[str, Any] = Field(default_factory=dict)                  # 格外特殊字段

# 定义告警列表最终返回的数据结构（多条告警组成的列表）
class AlarmListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")             # 不允许出现没有定义的额外字段

    # items必须是一个列表，而且列表里的每一项都必须符合AlarmEventResponse的结构，如果当前没有任何告警，默认返回空列表
    items: list[AlarmEventResponse] = Field(default_factory=list)

def _meta(violation_type: int | None) -> dict[str, str]:
    """根据数据库正式编号查告警名称。"""
    return _TYPE_META.get(violation_type, _DEFAULT_META)

def _dict_value(value: object) -> dict[str, Any]:
    """确保某个metadata字段一定是字典，而且key一定转成字符串"""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}

def _int_list(value: object) -> list[int]:
    """把metadata里的摄像头ID列表清洗成合法、去重的整数列表"""
    # 1、必须是list
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()                   # 去重
    # 遍历列表
    for item in value:
        if isinstance(item, bool):           # 排除bool
            continue
        if isinstance(item, int):            # 本来是int直接用
            camera_id = item
        elif isinstance(item, str):
            normalized = item.strip()        # 去空格
            # 只接受纯数字
            if not normalized or any(char not in "0123456789" for char in normalized):
                continue
            try:
                camera_id = int(normalized)          #转成整数
            except (ValueError, OverflowError):
                continue
        else:
            continue
        # 合法且不能重复
        if not 1 <= camera_id <= _MAX_CAMERA_ID or camera_id in seen:
            continue
        seen.add(camera_id)
        result.append(camera_id)
    return result

def _channel_alarm_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    """从通道告警的metadata中，把多摄像头相关字段整理出来"""
    # 取摄像头的参数，并保证是字典
    raw_states = _dict_value(metadata.get("camera_states"))
    # 只保留value本身也是字典的数据
    camera_states = {
        key: dict(value)
        for key, value in raw_states.items()
        if isinstance(value, dict)
    }

    raw_counts = _dict_value(metadata.get("camera_counts"))
    camera_counts: dict[str, int | None] = {}
    # 只接受None或者>=0的整数
    for key, value in raw_counts.items():
        if value is None:
            camera_counts[key] = None
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            camera_counts[key] = value

    # 处理摄像头名称，并统一转成字符串
    explicit_names = _dict_value(metadata.get("camera_names"))
    camera_names = {
        key: str(value)
        for key, value in explicit_names.items()
        if value is not None
    }
    for key, state in camera_states.items():
        if state.get("camera_name") is not None:
            # 如果camera_states有的摄像头名称而camera_names没有就补进去，有就不补
            camera_names.setdefault(key, str(state["camera_name"]))
    evidence_error = metadata.get("evidence_error")
    # 整理成统一格式返回
    return {
        "camera_ids": _int_list(metadata.get("camera_ids")),
        "camera_names": camera_names,
        "camera_counts": camera_counts,
        "camera_states": camera_states,
        "offending_camera_ids": _int_list(metadata.get("offending_camera_ids")),
        "evidence_error": str(evidence_error) if evidence_error is not None else None,
    }

def _event_dict(row: AiAlarmEvent) -> dict[str, Any]:
    """把数据库告警事件转换成以 subject 为主语义的接口记录。"""
    violation_type = row.violation_type
    meta = _meta(violation_type)
    raw_metadata = getattr(row, "event_metadata", None)
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    subject_type = str(getattr(row, "subject_type", None) or "camera")
    subject_id = getattr(row, "subject_id", None)
    subject_name = getattr(row, "subject_name", None)
    persisted_reason = getattr(row, "reason", None)
    raw_camera_no = str(getattr(row, "camera_no", None) or "")
    is_channel = subject_type == "logistics_channel"

    feature_name = row.feature_name
    department = row.department

    camera_no = (raw_camera_no or None) if not is_channel else None
    camera_name = None
    channel_id = None
    channel_name = None
    if is_channel:
        channel_id_value = subject_id
        channel_id = str(channel_id_value) if channel_id_value is not None else None
        channel_name = str(
            subject_name
            or "物流通道"
        )
        subject_id = channel_id
        subject_name = channel_name
    else:
        camera_name = str(
            subject_name
            or "未知摄像头"
        )
        subject_name = subject_name if subject_name is not None else camera_name

    display_subject = str(subject_name or "未知主体")
    reason = str(
        persisted_reason
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

@router.get("", response_model=AlarmListResponse)
def list_alarms(limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    """从数据库查最近的告警记录，转成前端统一格式，然后返回"""
    session = get_session()
    try:
        rows = (
            # 查询告警记录表
            session.query(AiAlarmEvent)
            # 按时间排序，最新告警排在前面，时间一样就id比较大的排在前面
            .order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc())
            # 限制条数
            .limit(limit)
            .all()          # 真正执行数据库查询
        )
        # 统一告警格式返回
        return {"items": [_event_dict(row) for row in rows]}
    finally:
        session.close()

@router.get("/{alarm_id}/image")
def alarm_image(alarm_id: int):
    """根据告警id找到对应的告警截图，然后把图片文件返回给浏览器"""
    session = get_session()
    try:
        row = session.query(AiAlarmEvent).filter(AiAlarmEvent.id == alarm_id).first() #通过alarm_id去数据库找截图，拿第一条
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        if not row.image_path or not os.path.exists(row.image_path):
            raise HTTPException(status_code=404, detail="alarm image not found")
        # 直接读取服务器磁盘上的图片文件，通过HTTP发给浏览器
        return FileResponse(row.image_path, media_type="image/png")
    finally:
        session.close()


@public_router.get("/{alarm_id}/image")
def public_alarm_image(alarm_id: int):
    """提供企业微信卡片可直接访问的告警图片。"""
    return alarm_image(alarm_id)

@router.get("/{alarm_id}/video")
def alarm_video(alarm_id: int):
    """根据告警ID找到告警视频，确认视频已经生成、文件存在、浏览器可以播放、然后把MP4返回给前端"""
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
            # 确保是浏览器可以播放的mp4
            compatible_path = ensure_browser_compatible_mp4(video_path)
        except VideoEncodingError as exc:
            logger.warning(f"[AlarmVideo] 浏览器兼容转换失败 alarm_id={alarm_id}: {exc}")
            raise HTTPException(status_code=500, detail="alarm video is not browser compatible") from exc
        # 返回浏览器可以访问的视频地址
        return FileResponse(compatible_path, media_type="video/mp4")
    finally:
        session.close()

@router.get("/statistics/summary")
def alarm_statistics(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    """查询最近 N 天告警，按类型、主体、日期和小时聚合。"""
    now = dt.datetime.now()
    # 算今天的00：00
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    range_start = today_start - dt.timedelta(days=days - 1)   # 算统计起始日期

    session = get_session()
    try:
        rows = (
            session.query(AiAlarmEvent)
            .filter(AiAlarmEvent.create_time >= range_start)
            .order_by(AiAlarmEvent.create_time.asc())
            .all()                                        # 查询range_start内的告警，按时间从旧到新排序
        )

        # 总告警数
        total = len(rows)
        # 今日告警数
        today = sum(1 for row in rows if row.create_time and row.create_time >= today_start)
        # 按照告警类型进行计数
        type_counts = Counter(row.violation_type for row in rows)
        # 按告警主体进行计数
        subject_counts: Counter[tuple[str, str]] = Counter()
        subject_names: dict[tuple[str, str], str] = {}
        for row in rows:
            # 把数据库原始数据转换为统一格式
            event = _event_dict(row)
            subject_type = str(event["subject_type"] or "unknown")
            subject_id = str(event["subject_id"] or event["subject_name"] or "unknown")
            subject_key = (subject_type, subject_id)
            subject_counts[subject_key] += 1
            subject_names[subject_key] = str(event["subject_name"] or subject_id)
        # 按小时统计总告警
        hourly_counts = Counter(row.create_time.hour for row in rows if row.create_time)
        # 每一天，每一类告警是多少条
        daily_by_type: dict[str, Counter[int]] = defaultdict(Counter)
        # 每个小时每一种告警是多少条
        hourly_by_type: dict[int, Counter[int]] = defaultdict(Counter)

        for row in rows:
            if not row.create_time:
                continue
            day_key = row.create_time.strftime("%m-%d")
            violation_type = row.violation_type
            daily_by_type[day_key][violation_type] += 1                # 按天真正统计
            hourly_by_type[row.create_time.hour][violation_type] += 1  # 按小时真正统计

        daily = []
        for offset in range(days):
            day = range_start + dt.timedelta(days=offset)            # 起始日期向后
            key = day.strftime("%m-%d")
            bucket = daily_by_type.get(key, Counter())               # 当前天的各种告警数据
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

        # 按告警类型做分类统计
        by_type = [
            {
                "event_type": meta["event_type"],
                "name": meta["label"],
                "value": type_counts.get(vtype, 0),
            }
            for vtype, meta in _TYPE_META.items()
            if type_counts.get(vtype, 0) > 0            # 没发生过的类型就不要返回
        ]

        # 根据统一告警主体分类
        by_subject = [
            {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "subject_name": subject_names.get((subject_type, subject_id), subject_id),
                "value": value,
            }
            for (subject_type, subject_id), value in subject_counts.most_common(8)
        ]
        # 找高峰告警小时，告警最多的前一个的第一个元组的第一个数字（时间）
        peak_hour = hourly_counts.most_common(1)[0][0] if hourly_counts else None
        return {
            "summary": {
                "total": total,
                "today": today,
                "avg_per_day": round(total / days, 2),      # 平均每天多少条
                "active_subjects": len(subject_counts),     # 最近N出现过的告警主体数量
                "peak_hour": f"{peak_hour:02d}:00" if peak_hour is not None else "-",
            },
            "by_type": by_type,
            "by_subject": by_subject,
            "daily": daily,
            "hourly": hourly,
            "recent": [_event_dict(row) for row in rows[-8:]][::-1], # 前面的rows是旧到新排序，整理是拿最后8个倒叙，相对于最新告警排在第一
        }
    finally:
        session.close()
