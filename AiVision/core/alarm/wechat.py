"""
core/alarm/wechat.py
企业微信告警发送 — 文本消息 + 图片消息。

旧代码硬编码了 corpid 和 corpsecret,本次改为从环境变量读取。
对应环境变量(可选,未配置时仅日志告警):
    WECHAT_CORP_ID
    WECHAT_CORP_SECRET
    WECHAT_AGENT_ID
"""
from __future__ import annotations
import base64
import os
from io import BytesIO
from typing import Optional

import requests

from core.logger import logger
from core.settings import settings


# 事件名 → UI 友好显示名
_EVENT_DISPLAY = {
    "blocks": "区域入侵",
    "detect_face": "人脸逗留",
    "detect_phone": "手机违规",
    "detect_door": "大门状态",
    "detect_human": "人员逗留",
}


class WeChatNotifier:
    """企业微信通知发送器 — 单例,缓存 access_token"""

    def __init__(
        self,
        corp_id: Optional[str] = None,
        corp_secret: Optional[str] = None,
        agent_id: int = 1000050,
    ):
        self.corp_id = corp_id or settings.alarm.wechat_corp_id or os.environ.get("WECHAT_CORP_ID", "")
        self.corp_secret = corp_secret or settings.alarm.wechat_corp_secret or os.environ.get("WECHAT_CORP_SECRET", "")
        self.agent_id = int(settings.alarm.wechat_agent_id or os.environ.get("WECHAT_AGENT_ID", agent_id))
        self._token: Optional[str] = None

    def _get_token(self) -> Optional[str]:
        if not self.corp_id or not self.corp_secret:
            return None
        try:
            resp = requests.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(f"[WeChat] 获取 access_token 失败: {data}")
                return None
            self._token = data.get("access_token")
            return self._token
        except Exception as e:
            logger.warning(f"[WeChat] 获取 access_token 失败: {e}")
            return None

    def _upload_image(self, token: str, image_bytes: bytes) -> Optional[str]:
        try:
            resp = requests.post(
                "https://qyapi.weixin.qq.com/cgi-bin/media/upload",
                params={"access_token": token, "type": "image"},
                files={"media": ("alarm.jpg", BytesIO(image_bytes), "image/jpeg")},
                timeout=30,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(f"[WeChat] 上传图片失败: {data}")
                return None
            return data.get("media_id")
        except Exception as e:
            logger.warning(f"[WeChat] 上传图片失败: {e}")
            return None

    def send(
        self,
        feature_name: str,
        camera_name: str,
        image_jpeg_bytes: bytes,
        recipients: str,
    ):
        """发送告警通知 — recipients 形如 'user1|user2'"""
        if not recipients:
            return
        token = self._get_token()
        if token is None:
            logger.info("[WeChat] 未配置企业微信凭据,跳过推送")
            return

        media_id = self._upload_image(token, image_jpeg_bytes)
        event_label = _EVENT_DISPLAY.get(feature_name, feature_name)

        # 文本告警
        try:
            resp = requests.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json={
                    "touser": recipients,
                    "msgtype": "markdown",
                    "agentid": self.agent_id,
                    "markdown": {
                        "content": (
                            f"检测到异常行为!\n"
                            f"**事件**: {event_label}\n"
                            f"**摄像头**: {camera_name}\n"
                        )
                    },
                    "safe": 0,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(f"[WeChat] 发送文本失败: {data}")
        except Exception as e:
            logger.warning(f"[WeChat] 发送文本失败: {e}")

        # 图片告警
        if media_id is not None:
            try:
                resp = requests.post(
                    f"https://qyapi.weixin.qq.com/cgi-bin/message/send",
                    params={"access_token": token},
                    json={
                        "touser": recipients,
                        "msgtype": "image",
                        "agentid": self.agent_id,
                        "image": {"media_id": media_id},
                        "safe": 0,
                    },
                    timeout=10,
                )
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    logger.warning(f"[WeChat] 发送图片失败: {data}")
            except Exception as e:
                logger.warning(f"[WeChat] 发送图片失败: {e}")
