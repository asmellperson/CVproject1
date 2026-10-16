"""喇叭配置契约；凭据仅用于写入和设备认证。"""
from __future__ import annotations

from typing import Literal
from ipaddress import IPv4Address
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from AiVision.departments.department_registry import require_department


class HornReference(BaseModel):
    """只返回定位绑定所需的信息，不包含摄像头地址或设备凭据。"""
    key: str
    kind: Literal["camera", "logistics_channel", "guard_site"]
    feature: str
    feature_label: str
    department: str | None
    department_label: str
    resource_id: int
    resource_name: str
    detection_enabled: bool
    horn_enabled: bool
    audio_id: int | None
    alarm_label: str | None = None


class HornUsage(BaseModel):
    """删除前查看全部引用，包括停用配置，并以版本防止误删新出现的绑定。"""
    horn_id: int
    device_enabled: bool
    references: list[HornReference]
    revision: str


class HornDeleteRequest(BaseModel):
    """管理员确认引用清单后，显式解除已停用设备的绑定。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    detach_bindings: bool = False
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class HornSipWrite(BaseModel):
    """单台喇叭的 SIP 身份；写入密码不会进入公开响应。"""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str = Field(min_length=1, max_length=64)
    auth_id: str = Field(min_length=1, max_length=64)
    password: SecretStr | None = Field(default=None, max_length=128)
    port: int = Field(default=5060, ge=1, le=65535, strict=True)

    @field_validator("username", "auth_id")
    @classmethod
    def sip_identifier(cls, value: str) -> str:
        """SIP 标识只允许 URI 安全字符，防止报文头注入。"""
        if not re.fullmatch(r"[A-Za-z0-9_.+\-]{1,64}", value):
            raise ValueError("SIP 账户和认证 ID 只能包含字母、数字、下划线、点、加号或减号")
        return value


class HornSipResponse(BaseModel):
    """设备 SIP 公开参数，密码仅暴露是否已设置。"""
    username: str
    auth_id: str
    port: int
    password_set: bool


class SipServerConfig(BaseModel):
    """本平台 SIP 服务，保存后立即使用固定 UDP 监听端口。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    address: str = ""
    port: int = Field(default=5062, ge=1024, le=65535)

    @field_validator("address")
    @classmethod
    def server_address(cls, value: str) -> str:
        """公告地址应是喇叭能访问的服务器 IPv4 地址。"""
        if not value:
            return ""
        address = IPv4Address(value)
        if address.is_unspecified or address.is_multicast or address.is_loopback:
            raise ValueError("请填写喇叭可以访问的服务器局域网 IPv4 地址")
        return str(address)


class SipServerResponse(SipServerConfig):
    """保存配置与本机监听状态分别展示，不能把保存成功当作服务在线。"""
    running: bool = False
    last_error: str | None = None


class HornAudioResponse(BaseModel):
    """上传并转码成功后才公开的音频素材。"""
    id: int
    name: str
    size: int
    duration: float


class HornPlaybackTest(BaseModel):
    """对指定喇叭试播一个已经保存的音频 ID。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    audio_id: int = Field(gt=0, le=2_147_483_647)


class HornFields(BaseModel):
    """设备配置公共校验，错误响应隐藏原始输入以保护凭据。"""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("department", check_fields=False)
    @classmethod
    def device_department(cls, value):
        """新建和归属调整只能选择正式事业部，不能写入全局设备。"""
        return require_department(value)

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
        sip = getattr(self, "sip", None)
        if sip is not None:
            # SIP 对象整体替换时仍须包含默认本地端口，空密码由服务层保留。
            values["sip"] = sip.model_dump(exclude={"password"})
            if sip.password is not None:
                values["sip"]["password"] = sip.password.get_secret_value()
        return values


class HornCreate(HornFields):
    """创建设备所需信息，密码使用 SecretStr 避免默认展示。"""
    name: str = Field(min_length=1, max_length=100)
    department: str
    url: str = Field(min_length=1, max_length=500)
    username: str = Field(default="admin", min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=200)
    enable: bool = True
    description: str | None = Field(default=None, max_length=10000)
    sip: HornSipWrite | None = None


class HornUpdate(HornFields):
    """设备局部更新请求，密码保留策略由服务层决定。"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    department: str | None = None
    url: str | None = Field(default=None, min_length=1, max_length=500)
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: SecretStr | None = Field(default=None, max_length=200)
    enable: bool | None = None
    description: str | None = Field(default=None, max_length=10000)
    sip: HornSipWrite | None = None


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
    sip_ready: bool = False
    playing: bool = False


class HornResponse(BaseModel):
    """设备公开响应仅提供 password_set，不返回密码本身。"""
    id: int
    name: str
    department: str | None
    url: str
    username: str
    password_set: bool
    enable: bool
    description: str | None
    sip: HornSipResponse | None = None
    runtime: HornRuntimeStatus


class HornConnectionResult(BaseModel):
    """一次连接测试的成功标志及运行状态快照。"""
    success: bool
    runtime: HornRuntimeStatus


class HornPlaybackResult(HornConnectionResult):
    """实际发送结束后返回结果，现场是否出声仍由用户确认。"""
    message: str
