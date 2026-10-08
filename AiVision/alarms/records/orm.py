"""
alarms/records/orm.py

一条告警事件最终在数据库里保存成什么样
调用链：
    Consumer判断违规 -> AlarmDispatcher -> 违规图片和视频 -> AsyncViolationWriter -> AiAlarmEvent -> MySQL表ai_violation_image
 AiAlarmEvent：
    ① 基础身份
        id
        violation_type
        feature_name
        create_time

    ② 证据文件
        image_path
        video_path
        video_status

    ③ 归属/主体
        department
        camera_no
        subject_type
        subject_id
        subject_name

    ④ 告警详情
        reason
        event_metadata
    
"""
from sqlalchemy import JSON, Column, String, SmallInteger, DateTime, Enum, Text, text, event
from sqlalchemy.dialects.mysql import BIGINT
from AiVision.core.db import Base
from ..validation import validate_alarm_identity

# Python类 AiAlarmEvent <--> 数据库表 ai_violation_image
class AiAlarmEvent(Base):
    """完整告警事件"""

    __tablename__ = "ai_violation_image"
    __table_args__ = {
        "comment": "AI告警事件表",
        "mysql_engine": "InnoDB",     # InnoDB是MySQL存储引擎，支持事务
        "mysql_charset": "utf8mb4",   # utf8mb4：字符集，可以保存中文、英文、特殊字符、emoji
    }
    # BIGINT：更大的整数空间。unsigned=True：这个整数没有负数
    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    image_path = Column(String(500), nullable=False, comment="违规图片存储路径")
    video_path = Column(String(500), nullable=True, comment="报警证据视频路径")
    # pengding:视频还在生成，ready:视频已经生成好了，failed：视频生成失败
    video_status = Column(String(20), nullable=True, comment="视频状态: pending/ready/failed")
    # SmallInteger告警类型有限
    violation_type = Column(SmallInteger, nullable=False, comment="告警类型枚举")
    feature_name = Column(String(128), nullable=True, comment="触发告警的检测功能")
    department = Column(String(100), nullable=True, comment="告警归属部门")
    camera_no = Column(String(100), nullable=True, comment="摄像头主体的 shm_name")
    # 告警是什么对象触发的：摄像头或者物流通道
    subject_type = Column(String(50), nullable=True, comment="告警主体类型")
    # shm_name或者是物流通道的id（给程序识别）
    subject_id = Column(String(128), nullable=True, comment="告警主体ID")
    # 摄像头的前端显示名称或者是某个物流通道的名称（给人看）
    subject_name = Column(String(255), nullable=True, comment="告警主体名称快照")
    reason = Column(String(50), nullable=True, comment="异常原因")
    event_metadata = Column(JSON, nullable=True, comment="告警结构化元数据")
    # 告警记录创建时间
    create_time = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    def __init__(self, *, violation_type: int, feature_name: str, department: str, **kwargs):
        """创建事件时要求明确且一致的正式告警身份字段。"""
        validate_alarm_identity(violation_type, feature_name, department)
        super().__init__(violation_type=violation_type, feature_name=feature_name, department=department, **kwargs)

    def __repr__(self):
        """以记录 ID 与告警类型提供简短调试标识。"""
        return f"<AiAlarmEvent id={self.id} type={self.violation_type}>"


@event.listens_for(AiAlarmEvent, "before_insert")
def _validate_new_alarm(_mapper, _connection, target: AiAlarmEvent) -> None:
    # 防止对象创建后、真正 INSERT 前被改成缺失或不一致的正式字段；不改变数据库列定义。
    """INSERT 前再次核对身份，防止构造后被改为缺失或不一致的字段。"""
    validate_alarm_identity(target.violation_type, target.feature_name, target.department)


class AiAlarmDisposition(Base):
    """报警处置独立保留；证据过期清理不删除处理历史。"""

    __tablename__ = "ai_alarm_disposition"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    alarm_id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=False)
    status = Column(Enum("pending", "acknowledged", "resolved", "false_positive"), nullable=False)
    note = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    updated_by = Column(JSON, nullable=False)
    history = Column(JSON, nullable=False)
