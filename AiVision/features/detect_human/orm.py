# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_human/orm.py"""
from sqlalchemy import Column, Integer, Float, JSON
from AiVision.features._base.orm import FeatureConfigBase


# 功能：人员违规逗留检测配置字段，供各公司独立配置表复用；输入与输出详见下方说明
# 参数：无。
# 返回：HumanConfigFieldsMixin；返回新建的 `HumanConfigFieldsMixin` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class HumanConfigFieldsMixin:
    """人员违规逗留检测配置字段，供各公司独立配置表复用。"""

    CONF_THRESHOLD = Column(Float, default=0.3)
    IOU_THR = Column(Float, default=0.3)
    MAX_LOST = Column(Integer, default=5)
    MAX_TIME = Column(Float, default=10.0)
    roi_pos = Column(JSON, nullable=True)
    region = Column(JSON, nullable=True)
    MIN_BOX_AREA = Column(Integer, default=0)
    ASPECT_RATIO_RANGE = Column(JSON, nullable=True)
    CENTER_DIST_THR = Column(Float, default=0.65)
    AREA_RATIO_THR = Column(Float, default=0.55)
    MATCH_SCORE_THR = Column(Float, default=0.35)
    TRACK_SMOOTH_ALPHA = Column(Float, default=0.7)


# 功能：定义 `HumanConfigORM` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：HumanConfigORM；返回新建的 `HumanConfigORM` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class HumanConfigORM(HumanConfigFieldsMixin, FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_human"
