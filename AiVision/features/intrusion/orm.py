"""features/intrusion/orm.py — 区域入侵检测 ORM 表"""
from sqlalchemy import Column, Float, Integer, JSON
from AiVision.features._shared import defaults
from AiVision.features._shared.orm import FeatureConfigBase
from .schema import BlocksValueSchema

_VALUE_DEFAULTS = BlocksValueSchema().model_dump()

class BlocksConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_blocks"
    __table_args__ = {
        "comment": "摄像头blocks功能配置表",
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
    }

    # 特有字段(共享字段在 FeatureConfigBase 里)
    roi_pos = Column(JSON, nullable=False, default=list, comment="单个ROI归一化坐标点集（0~1）")
    line_points = Column(JSON, nullable=False, default=list, comment="警戒线两点归一化坐标（0~1）")
    alarm_side = Column(Integer, default=_VALUE_DEFAULTS["alarm_side"], comment="警戒线入侵侧: 1=左侧,-1=右侧")
    foot_ratio = Column(Float, default=_VALUE_DEFAULTS["foot_ratio"], comment="人体框脚底点高度比例")
    threshold = Column(Float, nullable=False, default=defaults.BLOCKS_CONFIDENCE, server_default=str(defaults.BLOCKS_CONFIDENCE), comment="人体检测置信度，0~1")

    def __repr__(self):
        return f"<BlocksConfig camera_id={self.camera_id} enable={self.enable}>"
