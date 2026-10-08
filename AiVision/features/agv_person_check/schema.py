"""AGV 检测参数及通信配置；对外协议不进入人体判定逻辑。"""
from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from AiVision.features._shared.roi import NormalizedRoi
from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared.defaults import ALARM_INTERVAL

TEMPLATE_VARIABLES = frozenset({"${result}", "${camera_key}", "${request_id}"})


class HttpConfigSchema(BaseModel):
    """同步响应或回调模式的协议配置，独立于内部人体判断。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    mode: Literal["sync", "callback"] = "sync"
    callback_url: str = ""
    method: Literal["GET", "POST"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: JsonValue = Field(default_factory=lambda: {"result": "${result}"})
    present_value: bool | int | float | str | None = None
    absent_value: bool | int | float | str | None = None
    timeout_seconds: float = Field(3.0, gt=0, le=10)

    @model_validator(mode="after")
    def validate_result_values(self):
        """防止有人与无人被配置为相同 JSON 值，造成接收方无法区分。"""
        if self.present_value is not None and self.absent_value is not None:
            if json.dumps(self.present_value) == json.dumps(self.absent_value):
                raise ValueError("有人返回值和无人返回值必须不同")
        return self

    def require_ready(self):
        """先添加摄像头并配置参数；实际接收检测请求前必须完成通信配置。"""
        if self.present_value is None or self.absent_value is None:
            raise ValueError("请先在 HTTP 通信中配置有人返回值和无人返回值")
        if self.mode == "callback" and not self.callback_url:
            raise ValueError("请先在 HTTP 通信中配置回调 URL")

    @field_validator("callback_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """限制为有效 HTTP 地址，拒绝内嵌凭据、片段和非法端口。"""
        if value:
            parts = urlsplit(value)
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                    or parts.username is not None or parts.password is not None or parts.fragment):
                raise ValueError("回调地址必须是无内嵌账号密码、无片段的 HTTP/HTTPS URL")
            _ = parts.port
        return value

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        """校验 Header 名称及可编码值，拒绝换行注入和开头空白。"""
        for name, content in value.items():
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                raise ValueError("HTTP Header 名称不合法")
            if "\r" in content or "\n" in content or content[:1].isspace():
                raise ValueError("HTTP Header 值不能包含换行或以空白开头")
            try:
                content.encode("latin-1")
            except UnicodeEncodeError as exc:
                raise ValueError("HTTP Header 值必须可用 Latin-1 编码") from exc
        return value

    @field_validator("body_template")
    @classmethod
    def validate_template(cls, value: JsonValue) -> JsonValue:
        """占位符作为完整 JSON 值替换，避免把布尔值、数字变成字符串。"""
        json.dumps(value, allow_nan=False)
        found = set()

        def visit(item):
            """递归检查占位符位置与名称，禁止把动态变量写入 JSON 键。"""
            if isinstance(item, dict):
                if any("${" in key for key in item):
                    raise ValueError("模板占位符只能用于 JSON 值")
                for child in item.values():
                    visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)
            elif isinstance(item, str) and "${" in item:
                if item not in TEMPLATE_VARIABLES:
                    raise ValueError("模板仅支持完整值 ${result}、${camera_key}、${request_id}")
                found.add(item)

        visit(value)
        if "${result}" not in found:
            raise ValueError("JSON Body 模板必须包含 ${result}")
        return value


class AgvPersonCheckValueSchema(BaseModel):
    """约束多帧无人确认窗口、帧新鲜度和推理超时。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    roi_pos: NormalizedRoi = Field(default_factory=list)
    alarm_interval: float = Field(ALARM_INTERVAL, gt=0)
    confidence_threshold: float = Field(0.5, ge=0, le=1)
    iou_threshold: float = Field(0.5, ge=0, le=1)
    sample_count: int = Field(3, ge=2, le=30, description="全部无人所需的不同帧数；任一帧有人即结束")
    cap_interval: float = Field(0.2, ge=0.05, le=5, description="采样间隔，单位秒")
    request_timeout_seconds: float = Field(5.0, gt=0, le=60)
    inference_timeout_seconds: float = Field(0.8, gt=0, le=2)
    frame_max_age_seconds: float = Field(1.0, gt=0, le=5)
    http: HttpConfigSchema = Field(default_factory=HttpConfigSchema)

    @model_validator(mode="after")
    def validate_window(self):
        """保证请求窗口长于最少采样间隔与一次推理等待之和。"""
        if self.request_timeout_seconds <= (self.sample_count - 1) * self.cap_interval + self.inference_timeout_seconds:
            raise ValueError("请求超时必须大于采样间隔总时长与单帧推理超时之和")
        return self


class AgvPersonCheckConfigSchema(BaseModel):
    """组合 AGV 检测开关、采样与通信配置及告警通道。"""
    model_config = ConfigDict(extra="forbid", strict=True)

    enable: bool = False
    value: AgvPersonCheckValueSchema = Field(default_factory=AgvPersonCheckValueSchema)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)


class PersonCheckResult(BaseModel):
    """内部检测结果只表达是否有人，不包含 AGV 协议值。"""
    model_config = ConfigDict(extra="forbid", strict=True)

    person_present: bool
