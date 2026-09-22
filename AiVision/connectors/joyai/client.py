"""JoyAI 官方 Adapter 协议；每次请求只携带一张 JPEG。"""

import base64
from dataclasses import dataclass
import threading
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError
import requests

from AiVision.core.settings import settings


class JoyAIError(RuntimeError):
    """可向业务层显示的脱敏服务错误。"""


class _Message(BaseModel):
    content: str


class _Choice(BaseModel):
    message: _Message


class _Completion(BaseModel):
    choices: list[_Choice] = Field(min_length=1, max_length=1)
    streamingharness: "_Harness"


class _Timing(BaseModel):
    adapter_total_ms: float = Field(ge=0)
    vllm_inference_ms: float = Field(0, ge=0)


class _Harness(BaseModel):
    timing: _Timing


class _Model(BaseModel):
    id: str = Field(min_length=1)


class _Models(BaseModel):
    data: list[_Model] = Field(min_length=1, max_length=1)


@dataclass(frozen=True)
class JoyAIResult:
    text: str | None
    latency_seconds: float


def visible_text(content: str) -> str | None:
    """静默不成为结果或事件；协议标记不进入前端。"""
    content = content.strip()
    if content.startswith("</silence>"):
        return None
    return content.replace("</response>", "").replace("</silence>", "").strip() or None


class JoyAIClient:
    def __init__(self):
        self.config = settings.joyai
        self._model: str | None = None
        self._model_lock = threading.Lock()

    def _request(self, method: str, path: str, session_id: str | None = None, payload: dict | None = None) -> dict:
        base = self.config.adapter_url.rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise JoyAIError("请在 AiVision/.env 配置 JOYAI_ADAPTER_URL")
        # 内网服务直连；不向系统 HTTP 代理发送摄像头图像或视频提问。
        with requests.Session() as transport:
            transport.trust_env = False
            try:
                response = transport.request(
                    method,
                    f"{base}{path}", json=payload,
                    headers={"Content-Type": "application/json", **({"x-streaming-session": session_id} if session_id else {})},
                    timeout=(5, self.config.request_timeout_seconds), allow_redirects=False,
                )
                if response.status_code != 200:
                    raise JoyAIError(f"指令驱动智慧安防服务请求失败（HTTP {response.status_code}）")
                body = response.json()
                if not isinstance(body, dict):
                    raise JoyAIError("指令驱动智慧安防服务未返回 JSON 对象")
                return body
            except requests.Timeout as exc:
                raise JoyAIError("指令驱动智慧安防服务请求超时") from exc
            except requests.JSONDecodeError as exc:
                raise JoyAIError("指令驱动智慧安防服务返回无效 JSON") from exc
            except requests.RequestException as exc:
                raise JoyAIError("无法连接指令驱动智慧安防服务") from exc

    def reset(self, session_id: str):
        body = self._request("POST", "/v1/streaming/reset", session_id, {})
        if body.get("ok") is not True:
            raise JoyAIError("指令驱动智慧安防会话清理失败")

    def _model_name(self) -> str:
        with self._model_lock:
            if self._model is None:
                try:
                    self._model = _Models.model_validate(self._request("GET", "/v1/models"), strict=True).data[0].id
                except ValidationError as exc:
                    raise JoyAIError("Adapter 必须公布一个有效的主模型") from exc
            return self._model

    def observe(self, *, session_id: str, jpeg: bytes, prompt: str, start_seconds: float, end_seconds: float,
                max_tokens: int, temperature: float, top_p: float) -> JoyAIResult:
        body = self._request("POST", "/v1/chat/completions", session_id, {
            "model": self._model_name(),
            "frame_time_ranges": [f"{start_seconds:.3f} seconds ~ {end_seconds:.3f} seconds"],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
                }},
            ]}],
        })
        try:
            result = _Completion.model_validate(body, strict=True)
            return JoyAIResult(
                text=visible_text(result.choices[0].message.content),
                latency_seconds=result.streamingharness.timing.vllm_inference_ms / 1000,
            )
        except ValidationError as exc:
            raise JoyAIError("指令驱动智慧安防服务返回格式不符合 Chat Completions 协议") from exc
