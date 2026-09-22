"""复用本地千问的 Chat Completions 接口与认证配置。"""

import os

from pydantic import BaseModel, Field
import requests


class QwenError(RuntimeError):
    """不携带请求正文和认证信息的服务错误。"""


class _ChatMessage(BaseModel):
    content: str | None
    refusal: str | None = None


class _ChatChoice(BaseModel):
    message: _ChatMessage
    finish_reason: str


class ChatCompletion(BaseModel):
    choices: list[_ChatChoice] = Field(min_length=1, max_length=1)


class QwenClient:
    @staticmethod
    def _headers() -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get("SECURITY_VLM_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def complete(self, *, base_url: str, model: str, messages: list[dict],
                 max_tokens: int, temperature: float, timeout_seconds: float) -> str:
        try:
            with requests.post(
                f"{base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": model, "messages": messages, "stream": False,
                    "max_tokens": max_tokens, "temperature": temperature,
                    "response_format": {"type": "json_object"},
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                timeout=(5, timeout_seconds), allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise QwenError(f"千问服务返回 HTTP {response.status_code}")
                return response.text
        except requests.Timeout as exc:
            raise QwenError("千问服务请求超时") from exc
        except requests.RequestException as exc:
            raise QwenError(f"千问服务请求失败：{type(exc).__name__}") from exc
