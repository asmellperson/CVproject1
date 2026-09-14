"""features/detect_human/orm.py"""
from sqlalchemy.orm import declared_attr
from sqlalchemy import CheckConstraint, Column, Integer, Float, JSON
from AiVision.features._base import defaults
from AiVision.features._base.orm import FeatureConfigBase
from .schema import HumanValueSchema

_VALUE_DEFAULTS = HumanValueSchema().model_dump()

class HumanConfigFieldsMixin:
    """人员违规逗留检测配置字段，供各公司独立配置表复用。"""

    @declared_attr
    def __table_args__(cls):
        return (
            CheckConstraint("DETECTION_IOU_THR BETWEEN 0 AND 1", name=f"ck_{cls.__tablename__}_0"),
            CheckConstraint("TRACK_IOU_THR BETWEEN 0 AND 1", name=f"ck_{cls.__tablename__}_1"),
            CheckConstraint("MAX_LOST >= 0", name=f"ck_{cls.__tablename__}_2"),
        )

    CONF_THRESHOLD = Column(Float, default=_VALUE_DEFAULTS["CONF_THRESHOLD"])
    # DETECTION_IOU_THR 用于模型推理；TRACK_IOU_THR 用于跨帧目标匹配
    DETECTION_IOU_THR = Column(Float, nullable=False, default=defaults.DETECTION_IOU_THR, server_default=str(defaults.DETECTION_IOU_THR))
    TRACK_IOU_THR = Column(Float, nullable=False, default=defaults.TRACK_IOU_THR, server_default=str(defaults.TRACK_IOU_THR))
    MAX_LOST = Column(Integer, nullable=False, default=defaults.MAX_LOST, server_default=str(defaults.MAX_LOST))
    # 逗留时间达到该值后，将目标记为告警状态
    MAX_TIME = Column(Float, default=defaults.MAX_TIME)
    roi_pos = Column(JSON, nullable=False, default=list)
    # 过滤面积最小检测框
    MIN_BOX_AREA = Column(Integer, default=_VALUE_DEFAULTS["MIN_BOX_AREA"])
    # 过滤宽高比不符合要求的检测框
    ASPECT_RATIO_RANGE = Column(JSON, nullable=False, default=lambda: list(_VALUE_DEFAULTS["ASPECT_RATIO_RANGE"]))
    # 控制跟踪匹配时对中心距离的容忍程度
    CENTER_DIST_THR = Column(Float, default=defaults.CENTER_DIST_THR)
    # 当IOU不足时，约束两个框的的面积相似度
    AREA_RATIO_THR = Column(Float, default=defaults.AREA_RATIO_THR)
    # 综合匹配分数达到该值，才进入候选匹配
    MATCH_SCORE_THR = Column(Float, default=defaults.MATCH_SCORE_THR)
    # 控制新检测框与原检测框的平滑权重
    TRACK_SMOOTH_ALPHA = Column(Float, default=defaults.TRACK_SMOOTH_ALPHA)

class HumanConfigORM(HumanConfigFieldsMixin, FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_human"
