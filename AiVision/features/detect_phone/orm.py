# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_phone/orm.py"""
from sqlalchemy import Boolean, Column, Float, JSON
from AiVision.features._base.orm import FeatureConfigBase


# 功能：定义 `PhoneConfigORM` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：PhoneConfigORM；返回新建的 `PhoneConfigORM` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PhoneConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_phone"

    roi_pos = Column(JSON, nullable=True)
    CONF_THRESHOLD = Column(Float, default=0.7)
    IOU_THR = Column(Float, default=0.5)
    MIN_CONFIRM_SECONDS = Column(Float, default=1.2)
    MIN_CONSECUTIVE_HITS = Column(Float, default=3)
    MAX_MISSED_SECONDS = Column(Float, default=0.6)
    TRACK_TTL_SECONDS = Column(Float, default=2.0)
    TRACK_IOU_THRESHOLD = Column(Float, default=0.2)
    PERSON_CONF_THRESHOLD = Column(Float, default=0.3)
    PERSON_IOU_THR = Column(Float, default=0.3)
    REQUIRE_PERSON_ASSOCIATION = Column(Boolean, default=True)
    PERSON_EXPAND_RATIO = Column(Float, default=0.18)
    HAND_REGION_MAX_Y_RATIO = Column(Float, default=0.85)
    MIN_PERSON_PHONE_OVERLAP = Column(Float, default=0.08)
