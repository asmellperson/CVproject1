"""声明人脸身份识别功能，业务标识为 recognize_face。

将消费者、持久化配置与请求校验结构统一注册，识别记录由专用记录模块管理。
"""
from AiVision.features._shared.spec import FeatureSpec
from .consumer import FaceRecognitionConsumer
from .orm import FaceRecognitionConfig
from .schema import FaceRecognitionConfigSchema

SPEC = FeatureSpec(
    name="recognize_face",
    display_name="人脸身份识别",
    consumer_cls=FaceRecognitionConsumer,
    orm_class=FaceRecognitionConfig,
    config_schema=FaceRecognitionConfigSchema,
    alarm_types=(7,),
    required_models=("insightface",),
)
