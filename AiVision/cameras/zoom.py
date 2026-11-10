"""海康 ISAPI 镜头控制；查询、短时动作与停止统一由后端完成。"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from threading import Event, Lock
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth

from AiVision.cameras.zoom_schema import CameraZoomCapabilities, CameraZoomResult
from AiVision.core.logger import logger
from AiVision.core.settings import settings


CHANNELS_PATH = "/ISAPI/PTZCtrl/channels"
ISAPI_NAMESPACE = "http://www.hikvision.com/ver20/XMLSchema"


class CameraZoomError(RuntimeError):
    """错误信息仅包含可公开的原因，不能附带设备地址或认证响应。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _text(root: ET.Element, name: str) -> str:
    return next(((node.text or "").strip() for node in root.iter() if _name(node) == name), "")


@dataclass(frozen=True)
class _Target:
    base_url: str
    channel_id: int
    username: str = field(repr=False)
    password: str = field(repr=False)

    @property
    def key(self) -> tuple[str, int]:
        """同一设备的重复配置和不同功能共享控制锁，不按数据库 ID 分锁。"""
        return self.base_url, self.channel_id


def _target(camera: dict, options) -> _Target:
    try:
        parsed = urlsplit(str(camera.get("url") or ""))
        if parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname or not parsed.username:
            raise ValueError
        host = parsed.hostname
        if any(char in host for char in "/\\?#@\r\n"):
            raise ValueError
        host = f"[{host}]" if ":" in host else host
        match = re.fullmatch(r"/(?:ISAPI/)?Streaming/Channels/([1-9][0-9]*)(?:/httpPreview)?/?", parsed.path, re.IGNORECASE)
        stream = int(match.group(1)) if match else 0
        if stream < 100:
            raise CameraZoomError("当前视频源无法确认对应的设备控制通道", 409)
        # 海康 101/102 都属于通道 1，无法映射的源不能默认控制通道 1。
        channel = stream // 100
        return _Target(f"{options.scheme}://{host}:{options.port}", channel,
                       unquote(parsed.username), unquote(parsed.password or ""))
    except (ValueError, TypeError):
        raise CameraZoomError("当前视频源未提供可用的摄像头管理地址和认证信息", 409) from None


class CameraZoomClient:
    """直连已配置设备，禁止重定向、代理及原始异常信息外泄。"""

    def __init__(self, target: _Target, options):
        self.target = target
        self.options = options

    def _request(self, method: str, path: str, **kwargs) -> ET.Element:
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.auth = HTTPDigestAuth(self.target.username, self.target.password)
                response = session.request(method, self.target.base_url + path,
                    timeout=self.options.request_timeout_seconds, allow_redirects=False, **kwargs)
        except requests.Timeout:
            raise CameraZoomError("摄像头管理接口请求超时，请检查设备网络") from None
        except requests.exceptions.SSLError:
            raise CameraZoomError("摄像头 HTTPS 证书校验失败") from None
        except requests.RequestException:
            raise CameraZoomError("无法连接摄像头管理接口") from None
        if response.status_code in {401, 403}:
            raise CameraZoomError("摄像头拒绝访问，请检查设备账号权限及接口支持情况")
        if not 200 <= response.status_code < 300:
            raise CameraZoomError(f"摄像头未提供可用的变焦接口（HTTP {response.status_code}）")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            raise CameraZoomError("摄像头未返回有效的变焦协议响应") from None
        if _name(root) == "ResponseStatus" and _text(root, "statusCode") != "1":
            raise CameraZoomError("摄像头未接受变焦请求，请检查设备接口与控制权限")
        return root

    def capabilities(self) -> CameraZoomCapabilities:
        channels = self._request("GET", CHANNELS_PATH)
        channel = next((node for node in channels.iter() if _name(node) == "PTZChannel"
                        and _text(node, "id") == str(self.target.channel_id)), None)
        if channel is None:
            return CameraZoomCapabilities(status="unknown", message="未确认当前视频通道的变焦能力")
        support = _text(channel, "zoomSupport").lower()
        if support == "false":
            return CameraZoomCapabilities(status="unsupported", message="设备报告当前通道不支持变焦")
        if support != "true":
            return CameraZoomCapabilities(status="unknown", message="设备未提供明确的变焦能力")
        caps = self._request("GET", f"{CHANNELS_PATH}/{self.target.channel_id}/capabilities")
        if _text(caps, "notSupportPTZContinuous").lower() == "true":
            return CameraZoomCapabilities(status="unknown", message="设备报告支持变焦，但未提供连续变焦控制")
        space = next((node for node in caps.iter() if _name(node) == "ContinuousZoomSpace"), None)
        try:
            minimum = float(_text(space, "Min")) if space is not None else math.nan
            maximum = float(_text(space, "Max")) if space is not None else math.nan
            if not (math.isfinite(minimum) and math.isfinite(maximum) and minimum <= 0 <= maximum and minimum < maximum):
                raise ValueError
        except ValueError:
            return CameraZoomCapabilities(status="unknown", message="设备未提供可验证的连续变焦控制范围")
        return CameraZoomCapabilities(status="supported", message="支持镜头变焦", channel_id=self.target.channel_id,
            zoom_in=maximum > 0, zoom_out=minimum < 0, minimum=minimum, maximum=maximum)

    def continuous(self, speed: float) -> None:
        # 只发送 zoom，避免对不支持云台转动的枪机附带转动指令。
        payload = f'<PTZData version="2.0" xmlns="{ISAPI_NAMESPACE}"><zoom>{speed:g}</zoom></PTZData>'
        root = self._request("PUT", f"{CHANNELS_PATH}/{self.target.channel_id}/continuous",
                             data=payload.encode(), headers={"Content-Type": "application/xml"})
        if _name(root) != "ResponseStatus" or _text(root, "statusCode") != "1":
            raise CameraZoomError("摄像头未确认变焦指令执行结果")


@dataclass
class _Motion:
    lock: Lock = field(default_factory=Lock)
    cancel: Event = field(default_factory=Event)


class CameraZoomService:
    """每个设备通道串行控制；浏览器断连不会取消 finally 中的停止请求。"""

    def __init__(self, options=None, client_factory=CameraZoomClient):
        self.options = options if options is not None else settings.camera_zoom
        self.client_factory = client_factory
        self._lock = Lock()
        self._motions: dict[tuple[str, int], _Motion] = {}

    def capabilities(self, camera: dict) -> CameraZoomCapabilities:
        try:
            return self.client_factory(_target(camera, self.options), self.options).capabilities()
        except CameraZoomError as exc:
            return CameraZoomCapabilities(status="unknown", message=str(exc))

    def control(self, camera: dict, action: str) -> CameraZoomResult:
        target = _target(camera, self.options)
        client = self.client_factory(target, self.options)
        with self._lock:
            motion = self._motions.setdefault(target.key, _Motion())
        if action == "stop":
            # 先唤醒短步等待，再等待在途启动请求和兜底停止结束，避免停止早于启动到达设备。
            motion.cancel.set()
            if not motion.lock.acquire(timeout=4 * self.options.request_timeout_seconds + self.options.step_seconds):
                raise CameraZoomError("设备控制尚未结束，停止结果未确认，请稍后重试", 409)
            try:
                client.continuous(0)
            finally:
                motion.lock.release()
            return CameraZoomResult(action="stop")
        if action not in {"in", "out"}:
            raise CameraZoomError("无效的变焦动作", 422)
        if not motion.lock.acquire(blocking=False):
            raise CameraZoomError("该摄像头正在调整镜头，请稍后重试", 409)
        try:
            motion.cancel.clear()
            caps = client.capabilities()
            if caps.status != "supported" or not (caps.zoom_in if action == "in" else caps.zoom_out):
                raise CameraZoomError(caps.message, 409)
            if motion.cancel.is_set():
                return CameraZoomResult(action=action)
            speed = (caps.maximum if action == "in" else caps.minimum) * self.options.speed_fraction
            try:
                client.continuous(speed)
                motion.cancel.wait(self.options.step_seconds)
            finally:
                # 即使启动请求超时，也可能已被设备执行，必须继续发送停止并核对业务回执。
                try:
                    client.continuous(0)
                except CameraZoomError:
                    logger.warning(f"[CameraZoom] 摄像头 {camera.get('shm_name', '')} 停止变焦未获确认")
                    raise CameraZoomError("停止变焦未获设备确认，请点击停止并检查设备连接") from None
            return CameraZoomResult(action=action)
        finally:
            motion.lock.release()


camera_zoom_service = CameraZoomService()
