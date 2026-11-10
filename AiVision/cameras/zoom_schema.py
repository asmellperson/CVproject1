"""摄像头镜头能力与短时控制的公开数据结构，不包含设备凭据。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class CameraZoomResult(BaseModel):
    action: Literal["in", "out", "stop"]
    stopped: bool = True
