"""features/door_state/ — 门禁状态检测"""
from AiVision.features._shared.spec import FeatureSpec
# 从当前的 door_state 目录导入三个类
from .consumer import DoorConsumer
from .orm import DoorConfigORM
from .schema import DoorConfigSchema

# 创建这个功能的描述对象
SPEC = FeatureSpec(
    name="detect_door",                    # 持续内部使用的功能标识
    display_name="大门开关检测",           # 界面展示的名称
    consumer_cls=DoorConsumer,             # 由哪个类执行检测
    orm_class=DoorConfigORM,               # 由哪个类映射数据库配置表
    config_schema=DoorConfigSchema,        # 由哪个类校验配置参数
    required_models=(),                    # 不依赖模型推理
    alarm_types=(2,),                      # 功能可触发的正式告警类型
)
