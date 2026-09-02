# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_logistics_single_person/orm.py"""
from sqlalchemy import Column, Float, Integer, JSON

from AiVision.features._base.orm import FeatureConfigBase


# 功能：定义 `LogisticsSinglePersonConfigORM` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：LogisticsSinglePersonConfigORM；返回新建的 `LogisticsSinglePersonConfigORM` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsSinglePersonConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_logistics_single_person"

    CONF_THRESHOLD = Column(Float, default=0.3)
    IOU_THR = Column(Float, default=0.3)
    roi_pos = Column(JSON, nullable=True)
    region = Column(JSON, nullable=True)
    MIN_BOX_AREA = Column(Integer, default=0)
    ASPECT_RATIO_RANGE = Column(JSON, nullable=True)
    empty_grace_seconds = Column(Float, default=2.0)
    multi_grace_seconds = Column(Float, default=1.0)
