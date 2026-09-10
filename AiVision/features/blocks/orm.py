"""features/blocks/orm.py — 区域入侵检测 ORM 表"""
from sqlalchemy import Column, Float, Integer, JSON
from AiVision.features._base.orm import FeatureConfigBase

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
    alarm_side = Column(Integer, default=1, comment="警戒线入侵侧: 1=左侧,-1=右侧")
    foot_ratio = Column(Float, default=0.93, comment="人体框脚底点高度比例")
    threshold = Column(Float, default=0.1, comment="检测阈值")
    blur_kernel = Column(Integer, default=5, comment="模糊核大小")
    diff_threshold = Column(Integer, default=10, comment="差异阈值")
    diff_threshold_env = Column(Integer, default=10, comment="环境差异阈值")
    env_threshold = Column(Float, default=0.5, comment="环境变化阈值")

    def __repr__(self):
        return f"<BlocksConfig camera_id={self.camera_id} enable={self.enable}>"
