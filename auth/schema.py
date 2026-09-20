"""认证与账号管理请求模型。"""

from pydantic import BaseModel, ConfigDict


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(AuthRequest):
    employee_id: str
    password: str


class ChangePasswordRequest(AuthRequest):
    current_password: str
    new_password: str


class AdminUserCreateRequest(AuthRequest):
    employee_id: str
    name: str
    role: str
    departments: list[str] | None = None
    password: str


class AdminUserUpdateRequest(AuthRequest):
    name: str
    role: str
    departments: list[str] | None = None
    enabled: bool


class AdminUserPasswordResetRequest(AuthRequest):
    new_password: str
