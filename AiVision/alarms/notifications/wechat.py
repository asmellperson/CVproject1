"""
alarms/notifications/wechat.py
企业微信告警发送 — 默认单条图文卡片消息。
负责获取 token、组织图文卡片并调用企业微信 HTTP API。
AlarmDispatcher._wechat_loop()传入本次已保存报警的链接；保存失败时才使用文字通知，人员缩略图使用受限签名链接。
对应环境变量(可选,未配置时仅日志告警):
    WECHAT_CORP_ID
    WECHAT_CORP_SECRET
    WECHAT_AGENT_ID

流程：
    __init__():保存企业微信凭据
    _get_token():crop_id + secret 获取access_token
    _send_news_card():单条图文卡片
    send(): AI业务报警 news 图文卡片，URL 缺失则记录失败
    send_alarm_text():卡片记录保存失败时的业务告警文本
    send_text():业务告警及系统异常文本通知
协议与调用入口：企业微信消息协议

    WeChatNotifier：保存企业 ID、应用密钥、应用 ID；构造本身不发送网络请求。
        凭据按构造参数、settings.alarm、环境变量等既有回退规则取值。
    _get_token()：校验凭据，请求 access_token，检查 HTTP 状态、业务错误码和响应。
        当前已经缓存 token 和过期时间，使用 monotonic 时钟及锁避免并发重复刷新，
        并按接口响应的 expires_in 提前刷新；不是每次发送都重新获取 token。
    send()：用于检测业务告警，需要正式报警类型、接收人、缩略图 URL 和详情 URL。
        标题统一使用 VIOLATION_TYPE_META 中的报警名称。
        当前只走单条 news 图文卡片；缺少 URL 时记录原因并返回 False，
        不再执行旧说明中提到的“上传图片 / 文本加图片降级”流程。
    _send_news_card()：组织标题、说明、图片 URL、跳转 URL，调用企业微信 message/send。
        检查 HTTP 和企业微信业务错误码，返回本次发送是否成功。
    send_text()：发送 Markdown 文本，用于摄像头、模型、Consumer 或 API 的系统异常通知。
        与业务告警图文卡片是不同入口，系统异常不必构造 AlarmRequest。

"""
from __future__ import annotations
import os
import threading
import time
from typing import Optional         # 类型标注

import requests                     # 调企业微信HTTP API

from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.alarms.types import VIOLATION_TYPE_META

_TOKEN_REFRESH_MARGIN_SECONDS = 60

class WeChatNotifier:
    """
    企业微信应用消息发送器。

    发送流程（每次 send() 调用）:
        1. _get_token()    — 获取并按有效期缓存 access_token。
        2. send()          — 发送单条 news 图文卡片；缺少卡片 URL 时记录失败。

    凭据优先级（三选一，从高到低）:
        构造参数 > settings.alarm > 环境变量 WECHAT_CORP_ID / WECHAT_CORP_SECRET / WECHAT_AGENT_ID

    Note:
        未配置凭据时 _get_token() 返回 None，send() 记录 info 日志后静默跳过，
        不影响其他告警通道（喇叭、SQL）的正常执行。
    """

    def __init__(
        self,
        corp_id: Optional[str] = None,                 # 企业ID
        corp_secret: Optional[str] = None,             # 权限
        agent_id: Optional[int] = None,                # 企业微信应用
    ):
        # 凭据按优先级合并：构造参数 > settings > 环境变量 > 默认值
        """按既有优先级读取凭据并初始化受锁 Token 缓存，构造时不访问网络。"""
        self.corp_id = corp_id or settings.alarm.wechat_corp_id or os.environ.get("WECHAT_CORP_ID", "")
        self.corp_secret = corp_secret or settings.alarm.wechat_corp_secret or os.environ.get("WECHAT_CORP_SECRET", "")
        self.agent_id = int(agent_id or settings.alarm.wechat_agent_id or os.environ.get("WECHAT_AGENT_ID", 1000050))

        self._token: Optional[str] = None  # 按企业微信返回的有效期缓存
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  私有方法                                                             #
    # ------------------------------------------------------------------ #
    def _get_token(self) -> Optional[str]:
        """
        使用corp_id + corp_secret向企业微信接口换取 access_token。

        Returns:
            成功时返回 token 字符串；凭据未配置或接口报错时返回 None。

        Note:
            按响应 expires_in 缓存，提前刷新，并通过锁避免并发重复获取。
        """
        if not self.corp_id or not self.corp_secret:
            logger.warning("[WeChat] 企业微信凭据未配置，缺少 corp_id 或 corp_secret")
            return None  # 凭据缺失，无法请求，提前返回

        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token

        with self._token_lock:
            now = time.monotonic()
            if self._token and now < self._token_expires_at:
                return self._token
            try:
                # 请求token
                resp = requests.get(
                    "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                    params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
                    timeout=10,
                )
            except requests.RequestException as exc:
                logger.warning(f"[WeChat] 获取 access_token 网络失败: {exc}")
                return None
            except Exception as exc:
                logger.warning(f"[WeChat] 获取 access_token 请求异常: {exc}")
                return None

            status_code = getattr(resp, "status_code", 200)
            if not 200 <= status_code < 300:
                logger.warning(f"[WeChat] 获取 access_token HTTP 失败: status={status_code}")
                return None
            try:
                data = resp.json()
            except (TypeError, ValueError) as exc:
                logger.warning(f"[WeChat] 获取 access_token 响应解析失败: {exc}")
                return None
            # 企业微信返回的errcode不为0就认为业务失败
            if not isinstance(data, dict) or data.get("errcode", 0) != 0:
                errcode = data.get("errcode") if isinstance(data, dict) else None
                errmsg = data.get("errmsg") if isinstance(data, dict) else None
                logger.warning(
                    f"[WeChat] 获取 access_token 业务失败: errcode={errcode} errmsg={errmsg}"
                )
                return None
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                logger.warning("[WeChat] 获取 access_token 业务失败: 响应缺少 access_token")
                return None
            try:
                expires_in = max(1, int(data.get("expires_in", 7200)))
            except (TypeError, ValueError):
                expires_in = 7200
            refresh_margin = min(
                _TOKEN_REFRESH_MARGIN_SECONDS,
                max(1, expires_in // 10),
            )
            # 保存access_token到self._token
            self._token = token
            self._token_expires_at = time.monotonic() + max(1, expires_in - refresh_margin)
            return self._token

    def _send_news_card(
        self,
        *,
        token: str,
        recipients: str,
        title: str,
        description: str,
        detail_url: str,
        image_url: str,
    ) -> bool:
        """发送单条企业微信图文消息，缩略图与详情页均使用平台 URL。"""
        try:
            resp = requests.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json={
                    "touser": recipients,           # 发给谁
                    "msgtype": "news",              # 发送图片卡片消息
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
                    "safe": 0,                    # 按照普通消息处理
                },
                timeout=10,
            )
            status_code = getattr(resp, "status_code", 200)
            if not 200 <= status_code < 300:
                logger.warning(f"[WeChat] 发送图文 HTTP 失败: status={status_code}")
                return False
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(
                    f"[WeChat] 发送图文业务失败: errcode={data.get('errcode')} "
                    f"errmsg={data.get('errmsg')}"
                )
                return False
            return True
        except requests.RequestException as exc:
            logger.warning(f"[WeChat] 发送图文网络失败: {exc}")
        except Exception as exc:
            logger.warning(f"[WeChat] 发送图文失败: {exc}")
        return False

    # ------------------------------------------------------------------ #
    #  核心入口                                                             #
    # ------------------------------------------------------------------ #

    def send(
        self,
        violation_type: int,
        camera_name: str,
        recipients: str,
        image_url: str = "",
        detail_url: str = "",
    ) -> bool:
        """向指定接收人发送告警通知。

        发送策略:
            - image_url/detail_url 存在时发送单条 news 图文卡片。
            - URL 缺失时记录失败，不发送没有可用链接的卡片。

        Args:
            violation_type  : 正式报警类型，标题使用 VIOLATION_TYPE_META 中的名称。
            camera_name     : 摄像头展示名称，写入告警文本。
            recipients      : 接收人账号，多人用 | 分隔，如 "user1|user2"。
            image_url       : 企业微信可访问的报警缩略图 URL。
            detail_url      : 平台报警详情页 URL。
        """
        if type(violation_type) is not int or violation_type not in VIOLATION_TYPE_META:
            raise ValueError("企业微信业务告警 violation_type 必须是正式报警类型注册表中的整数")
        event_label = VIOLATION_TYPE_META[violation_type]["label"]
        if not recipients:
            return False  # 无接收人，跳过
        if not image_url or not detail_url:
            missing = []
            if not image_url:
                missing.append("image_url")
            if not detail_url:
                missing.append("detail_url")
            logger.warning(
                f"[WeChat] AI 告警图文卡片缺少 {', '.join(missing)}，跳过推送: "
                f"violation_type={violation_type} target={camera_name}"
            )
            return False
        # 先向企业微信认证，拿到后面接口所需的access_token
        token = self._get_token()
        if token is None:
            return False

        # 告警截图和告警详情URL都有
        return self._send_news_card(
            token=token,
            recipients=recipients,
            title=f"{event_label}告警",
            description=camera_name,
            detail_url=detail_url,
            image_url=image_url,
        )

    def send_alarm_text(self, violation_type: int, camera_name: str, recipients: str, *, detail_url: str = ""):
        """无截图或记录保存失败时继续通知；已保存的设备事件附带详情入口。"""
        if type(violation_type) is not int or violation_type not in VIOLATION_TYPE_META:
            raise ValueError("企业微信业务告警 violation_type 必须是正式报警类型注册表中的整数")
        label = VIOLATION_TYPE_META[violation_type]["label"]
        content = f"{label}告警\n报警对象：{camera_name}\n推送时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
        if detail_url:
            content += f"\n[查看报警详情]({detail_url})"
        self.send_text(
            content=content,
            recipients=recipients,
        )

    def send_text(self, content: str, recipients: str):
        """
        发送业务告警或系统运行异常的 Markdown 文本消息。

        Args:
            content   : Markdown 消息正文。
            recipients: 接收人账号,多人用 | 分隔；@all 表示全体。
        """
        if not recipients:
            return

        token = self._get_token()
        if token is None:
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
            status_code = getattr(resp, "status_code", 200)
            if not 200 <= status_code < 300:
                logger.warning(f"[WeChat] 发送系统文本 HTTP 失败: status={status_code}")
                return
            data = resp.json()
            if data.get("errcode", 0) != 0:
                logger.warning(
                    f"[WeChat] 发送系统文本业务失败: errcode={data.get('errcode')} "
                    f"errmsg={data.get('errmsg')}"
                )
        except Exception as e:
            logger.warning(f"[WeChat] 发送文本失败: {e}")
