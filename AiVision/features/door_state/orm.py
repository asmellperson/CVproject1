"""
features/door_state/orm.py
"""
from sqlalchemy import CheckConstraint, Column, Integer, Float, JSON
from AiVision.features._shared import defaults
from AiVision.features._shared.orm import FeatureConfigBase
from .schema import DoorValueSchema

_VALUE_DEFAULTS = DoorValueSchema().model_dump()

class DoorConfigORM(FeatureConfigBase):
    # 数据库表名
    __tablename__ = "ai_camera_config_detect_door"
    __table_args__ = (
        CheckConstraint("threshold BETWEEN 0 AND 1", name="ck_detect_door_0"),
        CheckConstraint("global_motion_threshold BETWEEN 0 AND 1", name="ck_detect_door_1"),
        CheckConstraint("env_threshold IS NULL OR env_threshold BETWEEN 0 AND 1", name="ck_detect_door_2"),
        CheckConstraint("first_alarm >= 0", name="ck_detect_door_3"),
    )
    # roi使用JSON保存多边形坐标
    roi_pos = Column(JSON, nullable=False, default=list)
    # 图像变化相关参数
    threshold = Column(Float, nullable=False, default=_VALUE_DEFAULTS["threshold"], server_default="0.5")
    diff_threshold = Column(Integer, default=_VALUE_DEFAULTS["diff_threshold"])
    diff_threshold_env = Column(Integer, default=_VALUE_DEFAULTS["diff_threshold_env"])
    env_threshold = Column(Float, nullable=True, default=defaults.DOOR_ENV_THRESHOLD, comment="NULL关闭环境过滤；0~1为比例上限")
    # 首次报警时，需要持续满足条件的秒数
    first_alarm = Column(Integer, nullable=False, default=defaults.DOOR_FIRST_ALARM, server_default=str(defaults.DOOR_FIRST_ALARM), comment="首次告警需持续秒数")
    # 确认变化有效，需要满足的时间和次数
    stable_confirm_seconds = Column(Float, default=_VALUE_DEFAULTS["stable_confirm_seconds"])
    stable_confirm_hits = Column(Integer, default=_VALUE_DEFAULTS["stable_confirm_hits"])
    # 背景更新和变化过滤参数
    background_update_alpha = Column(Float, default=_VALUE_DEFAULTS["background_update_alpha"])
    global_motion_threshold = Column(Float, nullable=False, default=_VALUE_DEFAULTS["global_motion_threshold"], server_default="0.22")
    min_local_change_ratio = Column(Float, default=_VALUE_DEFAULTS["min_local_change_ratio"])
