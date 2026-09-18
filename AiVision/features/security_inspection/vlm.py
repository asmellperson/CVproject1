"""内部千问客户端；只接受约定的 Chat Completions JSON 响应。"""

import base64
import os
import time

import cv2
import requests

from AiVision.core.logger import logger
from .prompts import VLM_SYSTEM_PROMPT, VLM_USER_PROMPT
from .schema import InspectionVerdict, VlmHealth, VlmSettings

HEALTH_CHECK_TIMEOUT_SEC = 3


def encode_frames(frames, settings: VlmSettings) -> list[bytes]:
    encoded = []
    for frame in frames:
        height, width = frame.shape[:2]
        scale = min(1.0, settings.image_max_side / max(height, width))
        if scale < 1:
            frame = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))))
        ok, image = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, settings.image_jpeg_quality])
        if not ok:
            raise ValueError("关键帧 JPEG 编码失败")
        encoded.append(image.tobytes())
    return encoded


class VlmClient:
    @staticmethod
    def _headers() -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get("SECURITY_VLM_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def check_health(self, settings: VlmSettings) -> VlmHealth:
        """只检查接口和已配置模型，不生成内容，也不代替真实图片判定。"""
        try:
            with requests.get(
                f"{settings.base_url}/models",
                headers=self._headers(),
                timeout=(HEALTH_CHECK_TIMEOUT_SEC, HEALTH_CHECK_TIMEOUT_SEC),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"千问健康检查返回 HTTP {response.status_code}")
                if not any(model["id"] == settings.model for model in response.json()["data"]):
                    raise RuntimeError("千问接口未提供已配置的模型")
        except Exception as exc:
            logger.warning(f"[security_inspection] 千问健康检查失败：{type(exc).__name__}: {exc}")
            if isinstance(exc, requests.Timeout):
                error = "千问接口连接或响应超时"
            elif isinstance(exc, requests.ConnectionError):
                error = "无法连接千问接口，请检查模型服务和地址"
            elif isinstance(exc, RuntimeError):
                error = str(exc)
            else:
                error = "千问健康检查响应格式无效"
            return VlmHealth(reachable=False, last_error=error)
        return VlmHealth(reachable=True)

    def judge(self, frames: list[bytes], settings: VlmSettings) -> tuple[InspectionVerdict, float]:
        if len(frames) < 2:
            raise ValueError("至少需要两张关键帧")
        content = [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(frame).decode("ascii")},
            }
            for frame in frames
        ]
        content.append({"type": "text", "text": VLM_USER_PROMPT.format(n_frames=len(frames))})
        started = time.monotonic()
        with requests.post(
            f"{settings.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": settings.model,
                "messages": [
                    {"role": "system", "content": VLM_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                "stream": False,
                "max_tokens": settings.max_tokens,
                "temperature": settings.temperature,
                "response_format": {"type": "json_object"},
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=(5, settings.api_timeout_sec),
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise RuntimeError(f"内部模型返回 HTTP {response.status_code}")
            text = response.json()["choices"][0]["message"]["content"]
        return InspectionVerdict.model_validate_json(text), time.monotonic() - started
