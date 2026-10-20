"""本地福达AI连接与生成参数，供不同业务复用同一套校验。"""
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QwenConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    base_url: str = "http://127.0.0.1:18100/v1"
    model: str = "fuda-qwen38-27b"
    max_tokens: int = Field(2048, ge=128, le=16384)
    temperature: float = Field(0.1, ge=0, le=2)
    api_timeout_sec: float = Field(45.0, ge=1, le=180)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (value != value.strip() or url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("模型地址必须为不含认证信息的 HTTP(S) 地址")
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("模型名称不能为空或含首尾空白")
        return value
