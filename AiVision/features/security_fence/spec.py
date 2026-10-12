"""围栏复用统一人体检测、人脸识别及报警基础设施。"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import FenceConsumer
from .orm import FenceConfigORM
from .schema import FEATURE, FORBIDDEN_ALARM, UNAUTHORIZED_ALARM, FenceConfig

SPEC = FeatureSpec(
    name=FEATURE, display_name="警戒围栏", consumer_cls=FenceConsumer,
    orm_class=FenceConfigORM, config_schema=FenceConfig,
    required_models=("yolo_human",), optional_models=("insightface",),
    alarm_types=(FORBIDDEN_ALARM, UNAUTHORIZED_ALARM),
)
