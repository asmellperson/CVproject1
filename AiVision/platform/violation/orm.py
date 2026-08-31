# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""platform/violation/orm.py"""
from sqlalchemy import JSON, Column, String, SmallInteger, DateTime, text
from sqlalchemy.dialects.mysql import BIGINT
from core.db import Base


# 功能：定义 `AiViolationImage` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：AiViolationImage；返回新建的 `AiViolationImage` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_violation_media_cleanup.py` 的 `_add_record` 实例化本符号；`AiVision/platform/violation/service.py` 的
#         `AsyncViolationWriter::save_now` 实例化本符号；`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::_flush_batch`
#         实例化本符号
#   - 内部调用：`Column`、`BIGINT`、`String`、`text`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AiViolationImage(Base):
    __tablename__ = "ai_violation_image"
    __table_args__ = {
        "comment": "AI违规图片存储表",
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
    }

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    image_path = Column(String(500), nullable=False, comment="违规图片存储路径")
    video_path = Column(String(500), nullable=True, comment="报警证据视频路径")
    video_status = Column(String(20), nullable=True, comment="视频状态: pending/ready/failed")
    violation_type = Column(SmallInteger, nullable=False, comment="违规类型枚举")
    camera_no = Column(String(100), nullable=True, comment="摄像头标识 shm_name")
    subject_type = Column(String(50), nullable=True, comment="告警主体类型")
    subject_id = Column(String(128), nullable=True, comment="告警主体ID")
    subject_name = Column(String(255), nullable=True, comment="告警主体名称快照")
    reason = Column(String(50), nullable=True, comment="异常原因")
    event_metadata = Column(JSON, nullable=True, comment="告警结构化元数据")
    create_time = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # 功能：实现 `__repr__` 对应的数据库模型逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def __repr__(self):
        return f"<AiViolationImage id={self.id} type={self.violation_type}>"
