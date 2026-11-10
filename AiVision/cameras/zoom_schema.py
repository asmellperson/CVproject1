"""摄像头镜头能力与短时控制的公开数据结构，不包含设备凭据。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CameraZoomCapabilities(BaseModel):
    status: Literal["supported", "unsupported", "unknown"]
    message: str
    channel_id: int | None = None
    zoom_in: bool = False
    zoom_out: bool = False
    minimum: float | None = None
    maximum: float | None = None


class CameraZoomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["in", "out", "stop"]
    speed_fraction: float | None = Field(None, gt=0, le=1)

    @model_validator(mode="after")
    def stop_has_no_speed(self):
        """停止只发送零速度，不能同时携带移动速度。"""
        if self.action == "stop" and self.speed_fraction is not None:
            raise ValueError("停止动作不能指定变焦速度")
        return self


class CameraZoomResult(BaseModel):
    action: Literal["in", "out", "stop"]
    stopped: bool = True
