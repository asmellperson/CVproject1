"""摄像头烟雾事件订阅与通用告警配置。"""
from sqlalchemy import CheckConstraint, Column, Float, Integer, String

from AiVision.features._shared.orm import FeatureConfigBase
from .schema import SmokeValueSchema


_DEFAULTS = SmokeValueSchema().model_dump()


class SmokeConfigORM(FeatureConfigBase):
    """设备负责检测；数据库只保存连接选项和平台通知配置。"""

    __tablename__ = "ai_camera_config_smoke_detection"
    __table_args__ = (
        CheckConstraint("device_port BETWEEN 1 AND 65535", name="ck_smoke_device_port"),
        CheckConstraint("event_channel_id > 0", name="ck_smoke_event_channel"),
        CheckConstraint("thermal_channel_id > 0", name="ck_smoke_thermal_channel"),
        CheckConstraint("device_scheme IN ('http', 'https')", name="ck_smoke_device_scheme"),
        CheckConstraint("alarm_interval > 0", name="ck_smoke_alarm_interval"),
    )
    device_scheme = Column(String(5), nullable=False, default=_DEFAULTS["device_scheme"], server_default="http")
    device_port = Column(Integer, nullable=False, default=_DEFAULTS["device_port"], server_default="80")
    event_channel_id = Column(Integer, nullable=False, default=_DEFAULTS["event_channel_id"], server_default="1")
    thermal_channel_id = Column(Integer, nullable=False, default=_DEFAULTS["thermal_channel_id"], server_default="1")
    alarm_interval = Column(Float, nullable=False, default=_DEFAULTS["alarm_interval"], server_default="60")

    # 设备主动上报事件，不使用公共帧处理间隔；该继承列不进入对外配置。
    _NON_VALUE_COLUMNS = FeatureConfigBase._NON_VALUE_COLUMNS | {"cap_interval"}
