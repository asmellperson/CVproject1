"""外部系统的授权范围和凭证管理契约。"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from AiVision.departments.department_registry import DEPARTMENT_SPECS

INSPECTION_FEATURE = "security_inspection"
INSPECTION_READ = "security_inspection:read"
INSPECTION_WRITE = "security_inspection:config:write"
ExternalScope = Literal["security_inspection:read", "security_inspection:config:write"]


class ExternalClientCreate(BaseModel):
    """创建凭证时必须明确事业部和有效期，默认只允许读取。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    departments: list[str] = Field(min_length=1, max_length=len(DEPARTMENT_SPECS))
    scopes: list[ExternalScope] = Field(
        default_factory=lambda: [INSPECTION_READ], min_length=1, max_length=2
    )
    expires_at: AwareDatetime

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        """避免空名称和控制字符进入操作日志。"""
        if value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("名称不能含首尾空白或控制字符")
        return value

    @field_validator("departments")
    @classmethod
    def validate_departments(cls, value):
        """只接受明确列出的正式事业部，禁止通配授权。"""
        if len(value) != len(set(value)) or set(value) - DEPARTMENT_SPECS.keys():
            raise ValueError("事业部必须来自正式目录且不能重复")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value):
        """配置写入以读取为前提，便于先读完整配置再保存。"""
        if len(value) != len(set(value)) or INSPECTION_READ not in value:
            raise ValueError("权限不能重复，且必须包含安检读取权限")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value):
        """统一使用带时区的未来时间，拒绝创建已经过期的凭证。"""
        if value <= datetime.now(timezone.utc):
            raise ValueError("有效期必须晚于当前时间")
        return value.astimezone(timezone.utc)


class ExternalClientUpdate(ExternalClientCreate):
    """全量修改凭证的授权信息，密钥只通过轮换接口更换。"""

    enabled: bool = Field(strict=True)


class ExternalClientEnabled(BaseModel):
    """允许独立停用已经过期的凭证。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class ExternalClientInfo(BaseModel):
    """凭证元数据始终不包含密钥或其摘要。"""

    id: str
    name: str
    departments: list[str]
    scopes: list[ExternalScope]
    enabled: bool
    expires_at: datetime
    created_by: str
    created_at: datetime
    updated_at: datetime


class ExternalClientIssued(BaseModel):
    """明文密钥只随创建或轮换结果返回一次。"""

    client: ExternalClientInfo
    api_key: str = Field(repr=False)
