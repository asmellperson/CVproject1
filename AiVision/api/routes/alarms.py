"""报警查询与证据文件接口。"""
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from auth.auth import get_current_user, token_from_request
from AiVision.alarms.notifications.notification_image import thumbnail_response, verify_thumbnail_token
from AiVision.alarms.records.orm import AiAlarmEvent
from AiVision.alarms.records.schema import AlarmEventResponse, AlarmListResponse
from AiVision.alarms.records.queries import (
    alarm_items, alarm_query, alarm_statistics, require_alarm_access,
)
from AiVision.core.db import get_session
from AiVision.core.logger import logger
from AiVision.core.video_encoding import VideoEncodingError, ensure_browser_compatible_mp4

router = APIRouter(prefix="/api/alarms", tags=["alarms"])
public_router = APIRouter(prefix="/api/public/alarms", tags=["alarms"])


@router.get("", response_model=AlarmListResponse)
def list_alarms(
    limit: int = Query(200, ge=1, le=1000),
    department: str | None = None,
    feature: str | None = None,
    event_types: str | None = None,
    user: dict = Depends(get_current_user),
):
    with get_session() as session:
        query = alarm_query(session, user, department, feature, event_types)
        rows = query.order_by(AiAlarmEvent.create_time.desc(), AiAlarmEvent.id.desc()).limit(limit).all()
        return {"items": alarm_items(session, rows)}


@router.get("/statistics/summary")
def statistics(
    days: int = Query(7, ge=1, le=90),
    department: str | None = None,
    feature: str | None = None,
    event_types: str | None = None,
    user: dict = Depends(get_current_user),
):
    with get_session() as session:
        return alarm_statistics(session, alarm_query(session, user, department, feature, event_types), days)


@router.get("/{alarm_id}", response_model=AlarmEventResponse)
def alarm_detail(alarm_id: int, user: dict = Depends(get_current_user)):
    with get_session() as session:
        row = session.get(AiAlarmEvent, alarm_id)
        if row is None:
            raise HTTPException(404, "alarm not found")
        require_alarm_access(row, user)
        return alarm_items(session, [row])[0]


@router.get("/{alarm_id}/image")
def alarm_image(alarm_id: int, user: dict = Depends(get_current_user)):
    """根据告警id找到对应的告警截图，然后把图片文件返回给浏览器"""
    session = get_session()
    try:
        row = session.query(AiAlarmEvent).filter(AiAlarmEvent.id == alarm_id).first() #通过alarm_id去数据库找截图，拿第一条
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        require_alarm_access(row, user)
        if not row.image_path or not os.path.exists(row.image_path):
            raise HTTPException(status_code=404, detail="alarm image not found")
        # 直接读取服务器磁盘上的图片文件，通过HTTP发给浏览器
        return FileResponse(row.image_path, media_type="image/png")
    finally:
        session.close()


@public_router.get("/{alarm_id}/image")
def public_alarm_image(alarm_id: int, request: Request, thumbnail_token: str | None = None):
    """人员证据要求登录；通知签名仅授权该报警的短期缩略图。"""
    session = get_session()
    try:
        row = session.get(AiAlarmEvent, alarm_id)
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        if row.violation_type == 5 or row.feature_name == "detect_human":
            if thumbnail_token is not None:
                # 已携带登录身份时仍执行事业部检查，不让链接绕过用户权限。
                if token_from_request(request):
                    require_alarm_access(row, get_current_user(request))
                if row.feature_name != "detect_human" or row.violation_type != 5 or not verify_thumbnail_token(
                    thumbnail_token, row.id, row.department,
                ):
                    raise HTTPException(status_code=403, detail="invalid or expired notification thumbnail")
                if not row.image_path or not os.path.exists(row.image_path):
                    raise HTTPException(status_code=404, detail="alarm image not found")
                return thumbnail_response(row.image_path)
            return alarm_image(alarm_id, get_current_user(request))
        if not row.image_path or not os.path.exists(row.image_path):
            raise HTTPException(status_code=404, detail="alarm image not found")
        return FileResponse(row.image_path, media_type="image/png")
    finally:
        session.close()

@router.get("/{alarm_id}/video")
def alarm_video(alarm_id: int, user: dict = Depends(get_current_user)):
    """根据告警ID找到告警视频，确认视频已经生成、文件存在、浏览器可以播放、然后把MP4返回给前端"""
    session = get_session()
    try:
        row = session.query(AiAlarmEvent).filter(AiAlarmEvent.id == alarm_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="alarm not found")
        require_alarm_access(row, user)
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
