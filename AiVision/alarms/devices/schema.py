"""喇叭配置契约；凭据仅用于写入和设备认证。"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class HornFields(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("name", "username", check_fields=False)
    @classmethod
    def nonblank(cls, value):
        if value is None or not value.strip():
            raise ValueError("不能为空")
        return value.strip()

    @field_validator("url", check_fields=False)
    @classmethod
    def device_url(cls, value):
        if value is None:
            raise ValueError("设备地址不能为空")
        value = value.strip()
        try:
            parts = urlsplit(value)
            valid = (parts.scheme in {"http", "https"} and parts.hostname
                     and parts.port != 0 and not parts.username and not parts.password
                     and not parts.query and not parts.fragment
                     and not any(c.isspace() for c in value) and "\\" not in value)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("设备地址须为不含账号、密码、查询参数的 HTTP/HTTPS 地址")
        return value.rstrip("/")

    @field_validator("enable", check_fields=False)
    @classmethod
    def enabled_value(cls, value):
        if value is None:
            raise ValueError("启用状态不能为空")
        return value

    def write_values(self) -> dict:
        values = self.model_dump(exclude_unset=True)
        if isinstance(values.get("password"), SecretStr):
            values["password"] = values["password"].get_secret_value()
        return values


class HornCreate(HornFields):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)
    username: str = Field(default="admin", min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=200)
    enable: bool = True
    description: str | None = Field(default=None, max_length=10000)


class HornUpdate(HornFields):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr | None = Field(default=None, max_length=200)
    enable: bool | None = None
    description: str | None = Field(default=None, max_length=10000)


class HornConnectionTest(HornFields):
    horn_id: int | None = Field(default=None, gt=0)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr | None = Field(default=None, max_length=200)


class HornRuntimeStatus(BaseModel):
    state: Literal["disabled", "not_started", "pending", "connecting", "online", "offline", "failed", "stopping", "stopped"]
    online: bool = False
    heartbeat_alive: bool = False
    last_error: str | None = None
    last_seen_at: float | None = None


class HornResponse(BaseModel):
    id: int
    name: str
    url: str
    username: str
    password_set: bool
    enable: bool
    description: str | None
    runtime: HornRuntimeStatus


class HornConnectionResult(BaseModel):
    success: bool
    runtime: HornRuntimeStatus
