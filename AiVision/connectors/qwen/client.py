"""共享图文请求的并发预算，不在 API 或业务模块中加载模型权重。"""
import os
import threading
import time

import requests

from AiVision.core.settings import settings


class QwenError(RuntimeError):
    """不包含凭据、请求正文或证据内容的模型服务异常。"""


class QwenNetworkError(QwenError):
    """模型请求的连接或传输失败，不包含底层异常中的地址。"""


class QwenTimeoutError(QwenError):
    """等待并发名额或模型响应超时。"""


class QwenServiceError(QwenError):
    """模型服务返回错误或未正常完成生成。"""


class QwenResponseError(QwenError):
    """模型响应封装或正文无法解析。"""


class QwenTruncatedError(QwenError):
    """模型因输出长度限制提前终止生成。"""


_slots = threading.BoundedSemaphore(settings.runtime.qwen_max_concurrent_requests)


def model_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("SECURITY_VLM_API_KEY", "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    return headers


class QwenClient:
    def complete(self, *, base_url: str, model: str, messages: list[dict], max_tokens: int,
                 temperature: float, timeout: float, json_mode: bool = False) -> tuple[str, float]:
        started = time.monotonic()
        payload = {"model": model, "messages": messages, "stream": False,
                   "max_tokens": max_tokens, "temperature": temperature,
                   "chat_template_kwargs": {"enable_thinking": False}}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if not _slots.acquire(timeout=timeout):
            raise QwenTimeoutError("福达AI服务请求繁忙，等待超时")
        try:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise QwenTimeoutError("等待福达AI服务超时")
            with requests.Session() as transport:
                transport.trust_env = False
                try:
                    with transport.post(
                        base_url.rstrip("/") + "/chat/completions", headers=model_headers(),
                        json=payload,
                        timeout=(min(5.0, remaining), remaining), allow_redirects=False,
                    ) as response:
                        if response.status_code != 200:
                            raise QwenServiceError(f"福达AI服务返回 HTTP {response.status_code}")
                        return response.text, time.monotonic() - started
                except requests.Timeout:
                    raise QwenTimeoutError("等待福达AI服务响应超时") from None
                except requests.RequestException as exc:
                    raise QwenNetworkError(f"福达AI服务请求失败：{type(exc).__name__}") from None
        finally:
            _slots.release()
