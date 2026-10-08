"""保安行为检测的正式 Feature 契约，关联单摄消费者和专用配置模型。

单摄层只产生感知证据；跨摄像头规则及正式告警由保安室运行层负责。
"""
from AiVision.features._shared.spec import FeatureSpec
from .constants import GUARD_ALARM_TYPES
from .consumer import GuardBehaviorConsumer
from .orm import GuardBehaviorCameraConfig
from .schema import GuardBehaviorCameraConfigSchema


SPEC = FeatureSpec(
    name="guard_behavior",
    display_name="保安行为规范检测",
    consumer_cls=GuardBehaviorConsumer,
    orm_class=GuardBehaviorCameraConfig,
    config_schema=GuardBehaviorCameraConfigSchema,
    required_models=("yolo_guard_person_phone", "guard_uniform"),
    optional_models=("yolo_guard_pose", "yolo_vehicle"),
    alarm_types=GUARD_ALARM_TYPES,
)
