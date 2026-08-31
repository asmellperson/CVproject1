# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/blocks/orm.py — 区域入侵检测 ORM 表"""
from sqlalchemy import Column, Float, Integer, JSON
from features._base.orm import FeatureConfigBase


# 功能：定义 `BlocksConfigORM` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：BlocksConfigORM；返回新建的 `BlocksConfigORM` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class BlocksConfigORM(FeatureConfigBase):
    __tablename__ = "ai_camera_config_blocks"
    __table_args__ = {
        "comment": "摄像头blocks功能配置表",
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
    }

    # 特有字段(共享字段在 FeatureConfigBase 里)
    roi_pos = Column(JSON, nullable=True, comment="ROI区域坐标点集")
    line_points = Column(JSON, nullable=True, comment="警戒线两点坐标")
    alarm_side = Column(Integer, default=1, comment="警戒线入侵侧: 1=左侧,-1=右侧")
    foot_ratio = Column(Float, default=0.93, comment="人体框脚底点高度比例")
    threshold = Column(Float, default=0.1, comment="检测阈值")
    blur_kernel = Column(Integer, default=5, comment="模糊核大小")
    diff_threshold = Column(Integer, default=10, comment="差异阈值")
    diff_threshold_env = Column(Integer, default=10, comment="环境差异阈值")
    env_threshold = Column(Float, default=0.5, comment="环境变化阈值")

    # 功能：实现 `__repr__` 对应的数据库模型逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def __repr__(self):
        return f"<BlocksConfig camera_id={self.camera_id} enable={self.enable}>"
