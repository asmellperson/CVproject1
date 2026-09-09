"""皓达公司人员违规逗留检测的独立配置表。"""

from AiVision.features._base.orm import FeatureConfigBase
from AiVision.features.detect_human.orm import HumanConfigFieldsMixin

class HaodaHumanConfigORM(HumanConfigFieldsMixin, FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_human_haoda"
