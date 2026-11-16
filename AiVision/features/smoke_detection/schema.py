"""摄像头烟雾报警接入配置，不保存平台烟雾识别算法参数。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._shared.alarm_schema import AlarmConfigSchema


class SmokeValueSchema(BaseModel):
    """设备接口与通知间隔；设备检测参数通过独立接口实时读取和修改。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    device_scheme: Literal["http", "https"] = "http"
    device_port: int = Field(80, ge=1, le=65535)
    event_channel_id: int = Field(1, ge=1)
    thermal_channel_id: int = Field(1, ge=1)
    alarm_interval: float = Field(60.0, gt=0)


class SmokeConfigSchema(BaseModel):
    """标准逐摄像头开关及数据库、喇叭、企微告警通道。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: SmokeValueSchema = Field(default_factory=SmokeValueSchema)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)
