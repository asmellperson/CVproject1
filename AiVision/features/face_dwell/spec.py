"""声明 detect_face 人脸逗留功能及正式告警类型 4。

仅依赖 insightface_detection；人员身份识别由独立的人脸识别功能负责。
"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import FaceConsumer
from .orm import FaceConfigORM
from .schema import FaceConfigSchema

SPEC = FeatureSpec(
    name="detect_face",
    display_name="人脸逗留检测",
    consumer_cls=FaceConsumer,
    orm_class=FaceConfigORM,
    config_schema=FaceConfigSchema,
    required_models=("insightface_detection",),
    alarm_types=(4,),
)
