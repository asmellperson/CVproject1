"""海康 Artemis 请求签名；签名的 body 必须与实际发送的字节完全一致。"""
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
