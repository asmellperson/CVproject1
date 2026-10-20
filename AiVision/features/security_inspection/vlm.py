"""内部福达AI客户端；只接受约定的 Chat Completions JSON 响应。"""

import base64
import re
from typing import Literal

import cv2
from pydantic import BaseModel, Field, ValidationError
import requests

from AiVision.core.logger import logger
from AiVision.connectors.qwen.client import QwenClient, QwenError, model_headers
from .prompts import VLM_SYSTEM_PROMPT, VLM_USER_PROMPT
from .schema import InspectionVerdict, VlmHealth, VlmSettings

HEALTH_CHECK_TIMEOUT_SEC = 3


class VlmError(RuntimeError):
    """区分通信、JSON 封装、字段和业务判定错误，供运行状态展示。"""
    def __init__(self, category: Literal["HTTP_ERROR", "JSON_ERROR", "FIELD_ERROR", "RESULT_ERROR"], detail: str):
        """保留稳定错误分类，同时构造可读异常摘要。"""
        self.category = category
        super().__init__(f"[{category}] {detail}")


class _ChatMessage(BaseModel):
    """约束模型消息中的文本与拒绝字段。"""
    content: str | None
    refusal: str | None = None


class _ChatChoice(BaseModel):
    """描述唯一候选的消息与生成结束原因。"""
    message: _ChatMessage
    finish_reason: str


class _ChatCompletion(BaseModel):
    # 传输层只读取单次判定需要的字段，id、usage 等标准元数据不进入业务层。
    """要求模型响应恰好包含一个候选，避免判定来源不明确。"""
    choices: list[_ChatChoice] = Field(min_length=1, max_length=1)


def parse_completion(body: str) -> InspectionVerdict:
    """唯一解析入口：标准响应封装 → 文本边界整理 → 严格业务模型。"""
    stage = "Chat Completions 响应"
    try:
        choice = _ChatCompletion.model_validate_json(body, strict=True).choices[0]
        if choice.finish_reason != "stop":
            raise VlmError("RESULT_ERROR", f"模型未完成判定：finish_reason={choice.finish_reason}")
        if choice.message.refusal:
            raise VlmError("RESULT_ERROR", "模型拒绝判定")
        content = choice.message.content
        if content is None:
            raise VlmError("RESULT_ERROR", "模型未返回判定内容")
        # 福达AI关闭思考时仍可能输出空 think 标签；只接纳这个完整的空前缀。
        content = re.sub(r"\A<think>\s*</think>\s*", "", content.strip(), count=1)
        fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", content, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            content = fenced[1].strip()
        if not content:
            raise VlmError("RESULT_ERROR", "模型返回空判定内容")
        stage = "判定 JSON"
        return InspectionVerdict.model_validate_json(content)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        kinds = {error["type"] for error in errors}
        if "json_invalid" in kinds:
            category = "JSON_ERROR"
        elif kinds <= {"greater_than_equal", "less_than_equal", "finite_number", "value_error"}:
            category = "RESULT_ERROR"
        else:
            category = "FIELD_ERROR"
        detail = "; ".join(
            f"{'.'.join(map(str, error['loc'])) or '$'}: {error['msg']} ({error['type']})" for error in errors
        )
        raise VlmError(category, f"{stage}：{detail}") from exc


def encode_frames(frames, settings: VlmSettings) -> list[bytes]:
    """按最长边限制缩小关键帧并编码 JPEG，编码失败显式抛错。"""
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
    """调用内部 Chat Completions 服务，返回经过严格校验的安检判定。"""
    def check_health(self, settings: VlmSettings) -> VlmHealth:
        """只检查接口和已配置模型，不生成内容，也不代替真实图片判定。"""
        try:
            with requests.get(
                f"{settings.base_url}/models",
                headers=model_headers(),
                timeout=(HEALTH_CHECK_TIMEOUT_SEC, HEALTH_CHECK_TIMEOUT_SEC),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"福达AI健康检查返回 HTTP {response.status_code}")
                if not any(model["id"] == settings.model for model in response.json()["data"]):
                    raise RuntimeError("福达AI接口未提供已配置的模型")
        except Exception as exc:
            logger.warning(f"[security_inspection] 福达AI健康检查失败：{type(exc).__name__}: {exc}")
            if isinstance(exc, requests.Timeout):
                error = "福达AI接口连接或响应超时"
            elif isinstance(exc, requests.ConnectionError):
                error = "无法连接福达AI接口，请检查模型服务和地址"
            elif isinstance(exc, RuntimeError):
                error = str(exc)
            else:
                error = "福达AI健康检查响应格式无效"
            return VlmHealth(reachable=False, last_error=error)
        return VlmHealth(reachable=True)

    def judge(self, frames: list[bytes], settings: VlmSettings) -> tuple[InspectionVerdict, float]:
        """发送至少两张关键帧与固定安检提示词，返回结构化判定及耗时。

        请求关闭重定向和流式输出，HTTP 或响应契约异常通过 VlmError 报告，
        不能把通信失败解释为安检合格。
        """
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
        try:
            body, latency = QwenClient().complete(
                base_url=settings.base_url, model=settings.model,
                messages=[{"role": "system", "content": VLM_SYSTEM_PROMPT},
                          {"role": "user", "content": content}],
                max_tokens=settings.max_tokens, temperature=settings.temperature, timeout=settings.api_timeout_sec,
                json_mode=True,
            )
        except QwenError as exc:
            raise VlmError("HTTP_ERROR", str(exc)) from exc
        return parse_completion(body), latency
