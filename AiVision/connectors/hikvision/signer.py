"""Artemis 请求签名，保证参与签名的路径、请求头与 body 字节和真实发送内容一致。

这里只生成认证请求头，不联网、不保存人员信息。调用方在序列化后签名，
不能在签名完成后重新编码 JSON 或修改已签字段。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass, field
from email.utils import formatdate


@dataclass(frozen=True)
class ArtemisSigner:
    """持有单个平台凭据的签名器，凭据字段从 repr 中隐藏，避免对象日志直接暴露密钥。"""
    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)

    def sign(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        timestamp_ms: int | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        """为无 query 的 Artemis API 路径生成 HMAC-SHA256 / Base64 请求头。"""
        if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            raise ValueError("Artemis signing requires an absolute API path without query or fragment")
        timestamp_ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
        headers = {
            "Accept": "*/*",
            "Content-MD5": base64.b64encode(hashlib.md5(body).digest()).decode("ascii"),
            "Content-Type": "application/json",
            "Date": formatdate(timestamp_ms / 1000, usegmt=True),
            "x-ca-key": self.app_key,
            "x-ca-nonce": str(uuid.uuid4()) if nonce is None else nonce,
            "x-ca-timestamp": str(timestamp_ms),
        }
        signed_names = sorted(name for name in headers if name.startswith("x-ca-"))
        canonical = method.upper() + "\n"
        canonical += "".join(headers[name] + "\n" for name in ("Accept", "Content-MD5", "Content-Type", "Date"))
        canonical += "".join(f"{name}:{headers[name]}\n" for name in signed_names)
        canonical += path
        headers["x-ca-signature-headers"] = ",".join(signed_names)
        headers["x-ca-signature"] = base64.b64encode(
            hmac.new(self.app_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii")
        return headers
