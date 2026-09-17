"""待正式切换时注册的 Feature 契约；当前不进入全局 registry。"""
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
