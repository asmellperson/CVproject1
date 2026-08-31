# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_face/ — 人脸逗留检测"""
from features._base.spec import FeatureSpec
from .consumer import FaceConsumer
from .orm import FaceConfigORM
from .schema import FaceConfigSchema

SPEC = FeatureSpec(
    name="detect_face",
    display_name="人脸检测",
    consumer_cls=FaceConsumer,
    orm_class=FaceConfigORM,
    config_schema=FaceConfigSchema,
    required_models=("yolo_face",),
    violation_type=4,
    departments=("research_institute",),
)
