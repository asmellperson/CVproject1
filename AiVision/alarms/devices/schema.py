"""喇叭配置契约；凭据仅用于写入和设备认证。"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class HornFields(BaseModel):
    """设备配置公共校验，错误响应隐藏原始输入以保护凭据。"""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("name", "username", check_fields=False)
    @classmethod
    def nonblank(cls, value):
        """规范化必填名称等文本，拒绝空白值。"""
        if value is None or not value.strip():
            raise ValueError("不能为空")
        return value.strip()

    @field_validator("url", check_fields=False)
    @classmethod
    def device_url(cls, value):
        """规范化设备根地址，拒绝内嵌凭据、查询片段和异常分隔符。"""
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
        """区分未提交启用字段与显式空值，拒绝空启用状态。"""
        if value is None:
            raise ValueError("启用状态不能为空")
        return value

    def write_values(self) -> dict:
        """导出明确提交的字段，密码仅在进入内部写入流程时解包。"""
        values = self.model_dump(exclude_unset=True)
        if isinstance(values.get("password"), SecretStr):
            values["password"] = values["password"].get_secret_value()
        return values


class HornCreate(HornFields):
    """创建设备所需信息，密码使用 SecretStr 避免默认展示。"""
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)
    username: str = Field(default="admin", min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=200)
    enable: bool = True
    description: str | None = Field(default=None, max_length=10000)


class HornUpdate(HornFields):
    """设备局部更新请求，密码保留策略由服务层决定。"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr | None = Field(default=None, max_length=200)
    enable: bool | None = None
    description: str | None = Field(default=None, max_length=10000)


class HornConnectionTest(HornFields):
    """对已存设备或临时连接参数进行认证探测的请求。"""
    horn_id: int | None = Field(default=None, gt=0)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr | None = Field(default=None, max_length=200)


class HornRuntimeStatus(BaseModel):
    """公开设备生命周期、心跳和最近可用状态。"""
    state: Literal["disabled", "not_started", "pending", "connecting", "online", "offline", "failed", "stopping", "stopped"]
    online: bool = False
    heartbeat_alive: bool = False
    last_error: str | None = None
    last_seen_at: float | None = None


class HornResponse(BaseModel):
    """设备公开响应仅提供 password_set，不返回密码本身。"""
    id: int
    name: str
    url: str
    username: str
    password_set: bool
    enable: bool
    description: str | None
    runtime: HornRuntimeStatus


class HornConnectionResult(BaseModel):
    """一次连接测试的成功标志及运行状态快照。"""
    success: bool
    runtime: HornRuntimeStatus
