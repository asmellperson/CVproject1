"""
core/alarm/wechat.py
企业微信告警发送 — 默认单条图文卡片消息。

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


# 功能内部名称 → 推送消息中的中文展示名
# 新增事件类型时在此表补充，无需改动发送逻辑
_EVENT_DISPLAY = {
    "blocks":        "区域入侵",
    "detect_face":   "人脸逗留",
    "detect_phone":  "手机违规",
    "detect_door":   "大门状态",
    "detect_human":  "人员逗留",
    "detect_logistics_single_person": "物流通道单人异常",
}


class WeChatNotifier:
    """
    企业微信应用消息发送器。

    发送流程（每次 send() 调用）:
        1. _get_token()    — 向企业微信接口换取 access_token（未缓存，每次重新获取）。
        2. send()          — 优先发送单条 news 图文卡片；缺少卡片 URL 时降级为旧文本+图片。

    凭据优先级（三选一，从高到低）:
        构造参数 > settings.alarm > 环境变量 WECHAT_CORP_ID / WECHAT_CORP_SECRET / WECHAT_AGENT_ID

    Note:
        未配置凭据时 _get_token() 返回 None，send() 记录 info 日志后静默跳过，
        不影响其他告警通道（喇叭、SQL）的正常执行。
    """

    def __init__(
        self,
        corp_id: Optional[str] = None,
        corp_secret: Optional[str] = None,
        agent_id: Optional[int] = None,
    ):
        # 凭据按优先级合并：构造参数 > settings > 环境变量 > 默认值
        self.corp_id = corp_id or settings.alarm.wechat_corp_id or os.environ.get("WECHAT_CORP_ID", "")
        self.corp_secret = corp_secret or settings.alarm.wechat_corp_secret or os.environ.get("WECHAT_CORP_SECRET", "")
        self.agent_id = int(agent_id or settings.alarm.wechat_agent_id or os.environ.get("WECHAT_AGENT_ID", 1000050))

        self._token: Optional[str] = None  # 预留字段，当前每次 send() 都重新获取

    # ------------------------------------------------------------------ #
    #  私有方法                                                             #
    # ------------------------------------------------------------------ #

    def _get_token(self) -> Optional[str]:
        """
        向企业微信接口换取 access_token。

        Returns:
            成功时返回 token 字符串；凭据未配置或接口报错时返回 None。

        Note:
            access_token 有效期为 7200 秒，当前未做本地缓存，每次调用都重新请求。
            若并发量大或调用频繁，可在此处加入过期时间缓存以减少接口压力。
        """
        if not self.corp_id or not self.corp_secret:
            return None  # 凭据缺失，无法请求，提前返回

        try:
            resp = requests.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                # errcode 非 0 表示企业微信侧返回业务错误（如凭据错误、IP 未加白）
                logger.warning(f"[WeChat] 获取 access_token 失败: {data}")
                return None
            self._token = data.get("access_token")
            return self._token
        except Exception as e:
            logger.warning(f"[WeChat] 获取 access_token 失败: {e}")
            return None

    def _upload_image(self, token: str, image_bytes: bytes) -> Optional[str]:
        """
        将 JPEG 图片上传为企业微信临时素材，获取 media_id。

        临时素材在企业微信服务端保留 3 天，期间可用 media_id 发送图片消息。
        上传失败时返回 None，send() 将跳过图片消息，仅发送文本告警。

        Args:
            token      : 有效的 access_token。
            image_bytes: JPEG 格式的图片字节流（由调用方负责编码格式正确）。

        Returns:
            成功时返回 media_id 字符串；失败时返回 None。
        """
        try:
            resp = requests.post(
                "https://qyapi.weixin.qq.com/cgi-bin/media/upload",
                params={"access_token": token, "type": "image"},
                # 以 multipart/form-data 格式上传，文件名固定为 alarm.jpg
                files={"media": ("alarm.jpg", BytesIO(image_bytes), "image/jpeg")},
                timeout=30,  # 图片上传网络耗时较长，超时设为 30 秒
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(f"[WeChat] 上传图片失败: {data}")
                return None
            return data.get("media_id")
        except Exception as e:
            logger.warning(f"[WeChat] 上传图片失败: {e}")
            return None

    def _send_news_card(
        self,
        *,
        token: str,
        recipients: str,
        title: str,
        description: str,
        detail_url: str,
        image_url: str,
    ) -> None:
        """发送单条企业微信图文消息，缩略图与详情页均使用平台 URL。"""
        try:
            resp = requests.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json={
                    "touser": recipients,
                    "msgtype": "news",
                    "agentid": self.agent_id,
                    "news": {
                        "articles": [
                            {
                                "title": title,
                                "description": description,
                                "url": detail_url,
                                "picurl": image_url,
                            }
                        ]
                    },
                    "safe": 0,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(f"[WeChat] 发送图文失败: {data}")
        except Exception as e:
            logger.warning(f"[WeChat] 发送图文失败: {e}")

    # ------------------------------------------------------------------ #
    #  核心入口                                                             #
    # ------------------------------------------------------------------ #

    def send(
        self,
        feature_name: str,
        camera_name: str,
        image_jpeg_bytes: bytes,
        recipients: str,
        image_url: str = "",
        detail_url: str = "",
    ):
        """向指定接收人发送告警通知。

        发送策略:
            - image_url/detail_url 存在时发送单条 news 图文卡片。
            - URL 缺失时保留旧文本+图片降级路径，避免配置缺失导致报警完全不可见。

        Args:
            feature_name    : 功能内部名称，通过 _EVENT_DISPLAY 映射为中文展示名。
            camera_name     : 摄像头展示名称，写入告警文本。
            image_jpeg_bytes: 违规帧的 JPEG 字节流，由 AlarmDispatcher 编码后传入。
            recipients      : 接收人账号，多人用 | 分隔，如 "user1|user2"。
            image_url       : 企业微信可访问的报警缩略图 URL。
            detail_url      : 平台报警详情页 URL。
        """
        if not recipients:
            return  # 无接收人，跳过

        token = self._get_token()
        if token is None:
            logger.info("[WeChat] 未配置企业微信凭据,跳过推送")
            return

        # 将内部功能名映射为用户友好的中文标签；未收录的名称原样展示
        event_label = _EVENT_DISPLAY.get(feature_name, feature_name)

        if image_url and detail_url:
            self._send_news_card(
                token=token,
                recipients=recipients,
                title=f"{event_label}告警",
                description=camera_name,
                detail_url=detail_url,
                image_url=image_url,
            )
            return

        # 上传图片（失败时 media_id 为 None，后续图片消息跳过）
        media_id = self._upload_image(token, image_jpeg_bytes)

        # ---- 消息 1: Markdown 文本告警 ----
        try:
            resp = requests.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json={
                    "touser":  recipients,
                    "msgtype": "markdown",
                    "agentid": self.agent_id,
                    "markdown": {
                        "content": (
                            f"检测到异常行为!\n"
                            f"**事件**: {event_label}\n"
                            f"**摄像头**: {camera_name}\n"
                        )
                    },
                    "safe": 0,  # 0: 普通消息；1: 保密消息（不可转发）
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(f"[WeChat] 发送文本失败: {data}")
        except Exception as e:
            logger.warning(f"[WeChat] 发送文本失败: {e}")

        # ---- 消息 2: 图片消息（依赖上传成功）----
        if media_id is not None:
            try:
                resp = requests.post(
                    "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                    params={"access_token": token},
                    json={
                        "touser":  recipients,
                        "msgtype": "image",
                        "agentid": self.agent_id,
                        "image":   {"media_id": media_id},
                        "safe": 0,
                    },
                    timeout=10,
                )
                data = resp.json()
                if data.get("errcode", 0) != 0:
                    logger.warning(f"[WeChat] 发送图片失败: {data}")
            except Exception as e:
                logger.warning(f"[WeChat] 发送图片失败: {e}")

    def send_text(self, content: str, recipients: str):
        """
        发送纯 Markdown 文本消息,用于系统运行状态类通知。

        Args:
            content   : Markdown 消息正文。
            recipients: 接收人账号,多人用 | 分隔；@all 表示全体。
        """
        if not recipients:
            return

        token = self._get_token()
        if token is None:
            logger.info("[WeChat] 未配置企业微信凭据,跳过推送")
            return

        try:
            resp = requests.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json={
                    "touser": recipients,
                    "msgtype": "markdown",
                    "agentid": self.agent_id,
                    "markdown": {"content": content},
                    "safe": 0,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(f"[WeChat] 发送文本失败: {data}")
        except Exception as e:
            logger.warning(f"[WeChat] 发送文本失败: {e}")
