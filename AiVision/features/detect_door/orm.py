# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_door/orm.py"""
from sqlalchemy import Column, Integer, Float, JSON
from features._base.orm import FeatureConfigBase


# 功能：定义 `DoorConfigORM` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：DoorConfigORM；返回新建的 `DoorConfigORM` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DoorConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_detect_door"

    roi_pos = Column(JSON, nullable=True)
    threshold = Column(Float, default=0.5)
    blur_kernel = Column(Integer, default=5)
    diff_threshold = Column(Integer, default=5)
    diff_threshold_env = Column(Integer, default=10)
    env_threshold = Column(Float, default=10.0)
    first_alarm = Column(Integer, default=60, comment="首次告警需持续秒数")
    stable_confirm_seconds = Column(Float, default=1.0)
    stable_confirm_hits = Column(Integer, default=3)
    background_update_alpha = Column(Float, default=0.05)
    global_motion_threshold = Column(Float, default=0.22)
    min_local_change_ratio = Column(Float, default=0.01)
