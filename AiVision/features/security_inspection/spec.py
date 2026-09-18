from AiVision.features._shared.spec import FeatureSpec
from .consumer import InspectionConsumer
from .orm import InspectionCameraConfig
from .schema import InspectionConfig

SPEC = FeatureSpec(
    name="security_inspection",
    display_name="安检流程规范检测",
    consumer_cls=InspectionConsumer,
    orm_class=InspectionCameraConfig,
    config_schema=InspectionConfig,
    required_models=("yolo_human",),
    alarm_types=(12,),
)
