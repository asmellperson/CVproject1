"""海康网络音柱的 ISAPI 摘要认证与预录音频控制。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth


DEVICE_INFO_PATH = "ISAPI/System/deviceInfo"
CUSTOM_AUDIO_PLAY_PATH = "ISAPI/AccessControl/EventCardLinkageCfg/CustomAudio/{audio_id}/play?format=json"


class HikvisionSpeakerError(RuntimeError):
    """仅包含可公开的设备错误，不附带凭据、响应原文或请求异常文本。"""


class HikvisionSpeakerClient:
    """封装海康网络音柱协议；调用方负责串行执行设备请求。"""

    def __init__(self, url: str, username: str, password: str, timeout: float):
        """保存连接参数，构造时不访问设备。"""
        self._url = url.rstrip("/") + "/"
        self._auth = HTTPDigestAuth(username, password)
        self._timeout = timeout

    def _request(self, method: str, path: str, operation: str, **kwargs) -> requests.Response:
        """局域网设备直连，保留 TLS 校验，且不把凭据发送给重定向目标。"""
        try:
            with requests.Session() as session:
                # 设备位于局域网，不能受服务器外网代理或 netrc 登录信息影响。
                session.trust_env = False
                session.auth = self._auth
                response = session.request(
                    method, self._url + path, timeout=self._timeout,
                    allow_redirects=False, **kwargs,
                )
        except requests.exceptions.SSLError:
            raise HikvisionSpeakerError(f"{operation}失败：HTTPS 证书校验失败，请检查设备证书") from None
        except requests.Timeout:
            raise HikvisionSpeakerError(f"{operation}失败：设备请求超时，请检查 HTTP/HTTPS 端口和网络") from None
        except requests.ConnectionError:
            raise HikvisionSpeakerError(f"{operation}失败：无法连接设备 HTTP/HTTPS 服务，请检查地址、端口和网络") from None
        except requests.RequestException as exc:
            raise HikvisionSpeakerError(f"{operation}失败：HTTP 请求异常（{type(exc).__name__}）") from None

        status = response.status_code
        if status == 401:
            raise HikvisionSpeakerError(f"{operation}失败：设备认证未通过，请检查用户名、密码或账号锁定状态（HTTP 401）")
        if status == 403:
            raise HikvisionSpeakerError(f"{operation}失败：设备拒绝访问，请检查账号权限和接口支持情况（HTTP 403）")
        if status in {404, 405}:
            raise HikvisionSpeakerError(f"{operation}失败：设备不支持所需 ISAPI 接口，请检查设备型号和地址（HTTP {status}）")
        if 300 <= status < 400:
            raise HikvisionSpeakerError(f"{operation}失败：设备要求跳转，请填写最终的 HTTP/HTTPS 设备根地址（HTTP {status}）")
        if not 200 <= status < 300:
            raise HikvisionSpeakerError(f"{operation}失败：设备返回 HTTP {status}")
        return response

    def check_connection(self) -> None:
        """通过只读设备信息接口验证认证；ISAPI 无需额外登录或会话保活。"""
        response = self._request("GET", DEVICE_INFO_PATH, "设备认证")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            raise HikvisionSpeakerError("设备认证失败：响应不是有效的 ISAPI 设备信息 XML，请检查设备根地址") from None
        if root.tag.rsplit("}", 1)[-1] != "DeviceInfo":
            raise HikvisionSpeakerError("设备认证失败：未返回 ISAPI 设备信息，请检查设备型号和根地址")

    def play(self, event_id: str | int) -> None:
        """语音任务 ID 对应设备素材库的音频文件 ID，不修改设备播放配置。"""
        audio_id = str(event_id)
        if not re.fullmatch(r"[1-9][0-9]{0,9}", audio_id) or int(audio_id) > 2_147_483_647:
            raise HikvisionSpeakerError("播放失败：音频文件 ID 必须是有效的正整数")
        response = self._request(
            "PUT", CUSTOM_AUDIO_PLAY_PATH.format(audio_id=audio_id), "语音播放", json={},
        )
        try:
            data = response.json()
        except ValueError:
            raise HikvisionSpeakerError("语音播放失败：设备返回了无效的 ISAPI JSON 响应") from None
        # HTTP 200 仅表示请求已送达，ISAPI 的业务状态仍可能表示播放被拒绝。
        if not isinstance(data, dict) or type(data.get("statusCode")) is not int:
            raise HikvisionSpeakerError("语音播放失败：设备响应缺少 ISAPI 业务状态")
        if data["statusCode"] not in {0, 1}:
            raise HikvisionSpeakerError(
                f"语音播放失败：设备拒绝播放（ISAPI 状态 {data['statusCode']}），请检查音频文件 ID、设备素材和播放权限"
            )
