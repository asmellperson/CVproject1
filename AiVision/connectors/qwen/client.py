"""共享图文请求的并发预算，不在 API 或业务模块中加载模型权重。"""
import os
import threading
import time

import requests

from AiVision.core.settings import settings


class QwenError(RuntimeError):
    """不包含凭据、请求正文或证据内容的模型服务异常。"""


_slots = threading.BoundedSemaphore(settings.runtime.qwen_max_concurrent_requests)


def model_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("SECURITY_VLM_API_KEY", "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    return headers


class QwenClient:
    def complete(self, *, base_url: str, model: str, messages: list[dict], max_tokens: int,
                 temperature: float, timeout: float) -> tuple[str, float]:
        started = time.monotonic()
        if not _slots.acquire(timeout=timeout):
            raise QwenError("千问服务请求繁忙，等待超时")
        try:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise QwenError("等待千问服务超时")
            with requests.Session() as transport:
                transport.trust_env = False
                try:
                    with transport.post(
                        base_url.rstrip("/") + "/chat/completions", headers=model_headers(),
                        json={"model": model, "messages": messages, "stream": False,
                              "max_tokens": max_tokens, "temperature": temperature,
                              "response_format": {"type": "json_object"},
                              "chat_template_kwargs": {"enable_thinking": False}},
                        timeout=(min(5.0, remaining), remaining), allow_redirects=False,
                    ) as response:
                        if response.status_code != 200:
                            raise QwenError(f"千问服务返回 HTTP {response.status_code}")
                        return response.text, time.monotonic() - started
                except requests.RequestException as exc:
                    raise QwenError(f"千问服务请求失败：{type(exc).__name__}") from exc
        finally:
            _slots.release()
