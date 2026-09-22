"""全部正式事业部共享的视觉语言检测能力。"""

from AiVision.features._shared.spec import FeatureSpec
from .consumer import VisualLanguageConsumer
from .orm import VisualLanguageConfigORM
from .schema import FEATURE_NAME, VisualLanguageConfig

SPEC = FeatureSpec(
    name=FEATURE_NAME,
    display_name="视觉语言检测",
    consumer_cls=VisualLanguageConsumer,
    orm_class=VisualLanguageConfigORM,
    config_schema=VisualLanguageConfig,
)
