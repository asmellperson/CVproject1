"""Artemis HTTP 传输、错误处理及图片重定向下载。配置由调用方显式注入。"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests

from AiVision.core.logger import logger

from .signer import ArtemisSigner

DEFAULT_TIMEOUT = (8.0, 25.0)
DEFAULT_MAX_RESPONSE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_PICTURE_REDIRECTS = 3
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class HikvisionError(RuntimeError):
    """已脱敏的连接器错误，保留 HTTP 状态和海康业务错误码供调用方处理。"""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class HikvisionConfig:
    """单个平台配置；多平台分别实例化。verify_tls 也可传入 CA 证书路径。"""

    base_url: str
    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)
    artemis_path: str = "/artemis"
    verify_tls: bool | str = True
    timeout: tuple[float, float] = DEFAULT_TIMEOUT
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_picture_redirects: int = DEFAULT_MAX_PICTURE_REDIRECTS
    # 默认只下载当前平台主机的图片，允许其返回不同端口；独立图片服务器需显式配置主机名。
    picture_hosts: tuple[str, ...] = ()

    def __post_init__(self):
        parts = urlsplit(self.base_url)
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
                or parts.path not in ("", "/") or parts.query or parts.fragment):
            raise ValueError("base_url must contain only an HTTP(S) scheme, host and optional port")
        parts.port  # 验证端口格式。
        if not self.app_key.strip() or not self.app_secret.strip():
            raise ValueError("Artemis credentials are required")
        if not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", self.artemis_path):
            raise ValueError("artemis_path must be an absolute path without query")
        if len(self.timeout) != 2 or any(not math.isfinite(value) or value <= 0 for value in self.timeout):
            raise ValueError("timeout must contain positive finite connect and read durations")
        if self.max_response_bytes <= 0 or self.max_picture_redirects < 0:
            raise ValueError("response limit must be positive and redirect limit must be nonnegative")


@dataclass(frozen=True)
class HikvisionResponse:
    status_code: int
    content_type: str
    body: bytes = field(repr=False)
    location: str | None = field(default=None, repr=False)
    gateway_error: str = field(default="", repr=False)
    request_url: str = field(default="", repr=False)


@dataclass(frozen=True)
class HikvisionPicture:
    """原始图片字节，不落盘、不做人脸检测；解码由调用方决定。"""

    content: bytes = field(repr=False)
    content_type: str

    @property
    def size_bytes(self) -> int:
        return len(self.content)


class HikvisionClient:
    """同步客户端；一个实例用于一个平台，使用 with 或 close 释放连接。"""

    def __init__(self, config: HikvisionConfig):
        self.config = config
        self._signer = ArtemisSigner(config.app_key, config.app_secret)
        self._api_session = requests.Session()
        self._picture_session = requests.Session()
        # 不继承代理、netrc 凭据；下载 session 不携带 Artemis 请求头或 API cookie。
        self._api_session.trust_env = False
        self._picture_session.trust_env = False
        self._closed = False

    def __enter__(self) -> HikvisionClient:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        self._api_session.close()
        self._picture_session.close()
        self._closed = True

    def _redact(self, text: str, values: tuple[str, ...] = ()) -> str:
        for value in (self.config.app_key, self.config.app_secret, *values):
            if value:
                text = text.replace(value, "<redacted>")
        text = re.sub(r"https?://\S+|/pic\?\S+", "<picture-url>", text)
        return text[:400]

    def _request(
        self, session: requests.Session, method: str, url: str, *,
        headers: dict[str, str], body: bytes | None = None,
    ) -> HikvisionResponse:
        if self._closed:
            raise HikvisionError("Hikvision client is closed")
        try:
            with session.request(method, url, headers=headers, data=body, timeout=self.config.timeout,
                                 verify=self.config.verify_tls, stream=True, allow_redirects=False) as response:
                content = bytearray()
                for chunk in response.iter_content(65536):
                    if len(content) + len(chunk) > self.config.max_response_bytes:
                        raise HikvisionError("Hikvision response exceeds configured size limit",
                                             status_code=response.status_code)
                    content.extend(chunk)
                return HikvisionResponse(
                    status_code=response.status_code,
                    content_type=response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower(),
                    body=bytes(content), location=response.headers.get("Location"),
                    gateway_error=response.headers.get("X-Ca-Error-Message", ""),
                    request_url=url,
                )
        except requests.RequestException as exc:
            # requests 异常可能包含完整图片签名 URL；不要附带原异常或打印原文。
            message = f"Hikvision {method} transport failed ({type(exc).__name__})"
            logger.warning(message)
            raise HikvisionError(message) from None

    def post(self, path: str, payload: dict) -> HikvisionResponse:
        """请求相对于 artemis_path 的 API 路径，保留 302 供图片流程显式处理。"""
        if not re.fullmatch(r"/api/[A-Za-z0-9_/-]+", path) or "//" in path:
            raise ValueError("Expected an Artemis /api/ path without query")
        full_path = self.config.artemis_path + path
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        headers = self._signer.sign("POST", full_path, body)
        response = self._request(self._api_session, "POST", self.config.base_url.rstrip("/") + full_path,
                                 headers=headers, body=body)
        logger.debug(f"[Hikvision] POST {path}: HTTP {response.status_code}")
        return response

    def _check_response(self, response: HikvisionResponse, *, values: tuple[str, ...] = ()) -> dict | None:
        try:
            payload = json.loads(response.body)
        except (ValueError, UnicodeDecodeError):
            payload = None
        code = None
        message = response.gateway_error
        if isinstance(payload, dict):
            value = payload.get("code", payload.get("ErrorCode"))
            code = None if value is None else str(value)
            message = str(payload.get("msg", payload.get("message", payload.get("Message", message))))
        if not 200 <= response.status_code < 300 or (code is not None and code != "0"):
            code = self._redact(code, values) if code is not None else None
            message = self._redact(message, values)
            description = f"Hikvision HTTP {response.status_code}, code={code}: {message or 'request failed'}"
            logger.warning(description)
            raise HikvisionError(description, status_code=response.status_code, code=code)
        return payload if isinstance(payload, dict) else None

    def post_json(self, path: str, payload: dict) -> dict:
        response = self.post(path, payload)
        values = tuple(value for value in payload.values() if isinstance(value, str))
        result = self._check_response(response, values=values)
        if result is None or str(result.get("code")) != "0" or "data" not in result:
            raise HikvisionError("Invalid Artemis JSON response envelope", status_code=response.status_code)
        return result

    def download_picture(
        self, response: HikvisionResponse, *, sensitive_values: tuple[str, ...] = (),
    ) -> HikvisionPicture:
        """消费图片接口响应，只跟随服务端返回且主机在配置范围内的 URL。"""
        url = response.request_url or self.config.base_url.rstrip("/") + "/"
        values = sensitive_values
        for hop in range(self.config.max_picture_redirects + 1):
            if response.status_code not in REDIRECT_STATUSES:
                self._check_response(response, values=values)
                if not response.content_type.startswith("image/") or not response.body:
                    raise HikvisionError("Hikvision picture response is not a nonempty image",
                                         status_code=response.status_code)
                return HikvisionPicture(response.body, response.content_type)
            if not response.location:
                raise HikvisionError("Hikvision picture redirect has no Location", status_code=response.status_code)
            if hop == self.config.max_picture_redirects:
                raise HikvisionError("Hikvision picture redirect limit exceeded", status_code=response.status_code)
            url = urljoin(url, response.location)
            try:
                parts = urlsplit(url)
                parts.port
                allowed = {urlsplit(self.config.base_url).hostname, *self.config.picture_hosts}
                valid = (parts.scheme in ("http", "https") and parts.hostname in allowed
                         and not parts.username and not parts.password and not parts.fragment)
            except ValueError:
                valid = False
            if not valid:
                raise HikvisionError("Hikvision picture redirect target is not an allowed picture host")
            values = (*sensitive_values, url, parts.query, *(value for _, value in parse_qsl(parts.query)))
            response = self._request(self._picture_session, "GET", url, headers={"Accept": "image/*"})
        raise HikvisionError("Hikvision picture download did not complete")
