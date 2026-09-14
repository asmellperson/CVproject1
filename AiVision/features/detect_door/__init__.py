"""features/detect_door/ — 门禁状态检测"""
from AiVision.features._base.spec import FeatureSpec
# 从当前的 detect_door 目录导入三个类
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
    violation_type=2,                      # 报警记录使用的违规类型编号
    departments=("general_electric",),     # 支持的业务部门：通用电气
)
