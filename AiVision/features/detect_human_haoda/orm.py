"""皓达公司人体逗留检测的独立配置表。"""

from features._base.orm import FeatureConfigBase
from features.detect_human.orm import HumanConfigFieldsMixin


class HaodaHumanConfigORM(HumanConfigFieldsMixin, FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_human_haoda"
