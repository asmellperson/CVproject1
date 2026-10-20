"""摄像头凭据仅驻留进程内存，进入模型和聊天数据库的内容只含引用。"""
from dataclasses import dataclass, field
import ipaddress
import re
import threading
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4


DEFAULT_RTSP_PORT = 554
DEFAULT_RTSP_PATH = "/Streaming/Channels/101"
SOURCE_TTL_SECONDS = 1800
MAX_PRIVATE_SESSIONS = 128
RTSP_PATTERN = re.compile(r"rtsps?://[^\s<>\"'`，。；！？（）【】]+", re.IGNORECASE)
CREDENTIAL_PATTERN = re.compile(
    r"(?P<label>账户|账号|用户名|username|密码|password|pwd)"
    r"(?:\s*(?:是|为|[:=：])\s*|\s+|(?=[A-Za-z0-9]))"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,，;；。]+)", re.IGNORECASE,
)


@dataclass
class CameraSource:
    url: str | None = field(default=None, repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    def resolve(self, host: str | None, port: int, path: str) -> str:
        if self.url:
            return self.url
        if not host or self.username is None or self.password is None:
            raise ValueError("请在同一条消息中提供摄像头账号、密码，并指定 IP")
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("摄像头地址必须是有效的 IP") from exc
        authority = f"[{address}]" if address.version == 6 else str(address)
        if not path.startswith("/") or any(char in path for char in "\r\n?#@"):
            raise ValueError("RTSP 路径无效")
        return (f"rtsp://{quote(self.username, safe='')}:{quote(self.password, safe='')}"
                f"@{authority}:{port}{path}")


def protect_message(text: str) -> tuple[str, dict[str, CameraSource]]:
    sources = {}

    def replace_url(match):
        raw = match.group(0).rstrip(",;。")
        parsed = urlsplit(raw)
        if not parsed.hostname:
            raise ValueError("RTSP 地址缺少摄像头 IP")
        key = "source_" + uuid4().hex[:12]
        sources[key] = CameraSource(url=raw)
        return f"【摄像头源 {key}，地址 {parsed.hostname}】"

    protected = RTSP_PATTERN.sub(replace_url, text)
    credentials = {}

    def replace_credential(match):
        label = match.group("label").lower()
        key = "password" if label in {"密码", "password", "pwd"} else "username"
        if key in credentials:
            raise ValueError("多组账号密码请分别提供完整 RTSP 地址，避免错配摄像头")
        credentials[key] = match.group("value").strip("\"'")
        return match.group("label") + "【已保护】"

    protected = CREDENTIAL_PATTERN.sub(replace_credential, protected)
    if credentials:
        key = "source_" + uuid4().hex[:12]
        sources[key] = CameraSource(**credentials)
        protected += f"\n【摄像头凭据引用 {key}；默认端口 {DEFAULT_RTSP_PORT}，路径 {DEFAULT_RTSP_PATH}】"
    return protected, sources


class CameraSourceVault:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[float, dict[str, CameraSource]]] = {}

    def update(self, session_id: str, sources: dict[str, CameraSource]) -> None:
        with self._lock:
            now = time.monotonic()
            self._sessions = {key: value for key, value in self._sessions.items()
                              if now - value[0] < SOURCE_TTL_SECONDS}
            if session_id not in self._sessions and len(self._sessions) >= MAX_PRIVATE_SESSIONS:
                oldest = min(self._sessions, key=lambda key: self._sessions[key][0])
                del self._sessions[oldest]
            previous = self._sessions.get(session_id, (now, {}))[1]
            self._sessions[session_id] = (now, {**previous, **sources})

    def get(self, session_id: str, source_id: str) -> CameraSource:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None or time.monotonic() - entry[0] >= SOURCE_TTL_SECONDS or source_id not in entry[1]:
                raise ValueError("摄像头凭据引用已过期，请重新提供连接信息")
            return entry[1][source_id]

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
