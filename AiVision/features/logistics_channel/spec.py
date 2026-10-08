"""声明物流通道单人检测功能及其单摄消费者。

逐路消费者产生人数快照，统一通道运行时负责多摄汇总、持续时间与告警。
"""
from AiVision.features._shared.spec import FeatureSpec

from .consumer import LogisticsSinglePersonConsumer
from .orm import LogisticsSinglePersonConfigORM
from .schema import LogisticsSinglePersonConfigSchema

SPEC = FeatureSpec(
    name="detect_logistics_single_person",
    display_name="物流通道单人检测",
    consumer_cls=LogisticsSinglePersonConsumer,
    orm_class=LogisticsSinglePersonConfigORM,
    config_schema=LogisticsSinglePersonConfigSchema,
    required_models=("yolo_human",),
    alarm_types=(6,),
)
