"""注册全部正式事业部共享的指令驱动智慧安防能力。

公共消费者管理摄像头配置，独立 HTTP 运行时按摄像头隔离视频上下文。
"""

from AiVision.features._shared.spec import FeatureSpec
from .consumer import VisualLanguageConsumer
from .orm import VisualLanguageConfigORM
from .schema import FEATURE_NAME, VisualLanguageConfig

SPEC = FeatureSpec(
    name=FEATURE_NAME,
    display_name="指令驱动智慧安防",
    consumer_cls=VisualLanguageConsumer,
    orm_class=VisualLanguageConfigORM,
    config_schema=VisualLanguageConfig,
    alarm_types=(14,),
)
