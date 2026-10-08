"""注册 AGV 请求触发型检测功能，将配置表、消费者与校验模型交给统一注册表。

检测请求的等待和结果回传由接口层处理，消费者负责共享帧采样及人体推理。
"""
from AiVision.features._shared.spec import FeatureSpec

from .consumer import AgvPersonCheckConsumer
from .orm import AgvPersonCheckConfigORM
from .schema import AgvPersonCheckConfigSchema

SPEC = FeatureSpec(
    name="agv_person_check",
    display_name="AGV无人运货检测",
    consumer_cls=AgvPersonCheckConsumer,
    orm_class=AgvPersonCheckConfigORM,
    config_schema=AgvPersonCheckConfigSchema,
    required_models=("yolo_human",),
    alarm_types=(13,),
)
