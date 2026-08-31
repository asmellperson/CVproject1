# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_face/orm.py"""
from sqlalchemy import Column, Float, JSON
from features._base.orm import FeatureConfigBase


# 功能：定义 `FaceConfigORM` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：FaceConfigORM；返回新建的 `FaceConfigORM` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FaceConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_face"

    roi_pos = Column(JSON, nullable=True)
    FACE_SCORE_THR = Column(Float, default=0.6)
    YAW_THRESHOLD = Column(JSON, nullable=True)
    # 复用基类的 cap_interval / alarm_interval
    # 跟踪相关字段(从 detect_human 借的设计)
    MAX_TIME = Column(Float, default=10.0, comment="逗留时间阈值(秒)")
    IOU_THR = Column(Float, default=0.3)
    MAX_LOST = Column(Float, default=5)
