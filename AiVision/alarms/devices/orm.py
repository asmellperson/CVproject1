"""alarms/devices/orm.py — 喇叭设备配置表"""
from sqlalchemy import Column, Integer, String, Boolean, Text, TIMESTAMP, JSON, Float, text
from AiVision.core.db import Base    # 所有ORM表模型的父类

# AiHornConfig：喇叭设备配置表在Python里的ORM映射（Python 类 AiHornConfig <--> MySQL 表 ai_horn_config）
class AiHornConfig(Base):
    """保存独立喇叭设备及认证资料，公开响应由服务层剔除密码。"""
    __tablename__ = "ai_horn_config"
    # 建表参数
    __table_args__ = {
        "comment": "喇叭设备配置表",       # 给数据库表加说明
        "mysql_engine": "InnoDB",          # InnoDB 是 MySQL 常用的事务型存储引擎。
        "mysql_charset": "utf8mb4",        # 数据库字符编码
    }

    # 每一条喇叭记录的数据库唯一编号，autoincrement=True:自动增长
    id = Column(Integer, primary_key=True, autoincrement=True)
    # nullable=False：不能是None。也就是喇叭必须有名字，unique=True名字不能重复
    name = Column(String(100), nullable=False, unique=True, index=True)
    # 喇叭设备的网络地址
    url = Column(String(500), nullable=False)
    # 访问这个喇叭地址的用户名和密码
    username = Column(String(100), nullable=False, default="admin")
    password = Column(String(200), nullable=False)
    # 空值使用设备内置音频；SIP 参数仅在内部读取时包含注册密码。
    sip_config = Column(JSON(none_as_null=True), nullable=True)
    # 这个喇叭配置是否启用
    enable = Column(Boolean, default=True, index=True)
    # 普通备注
    description = Column(Text, nullable=True)
    # 数据库新增这一行时，自动记录创建时间
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    # 修改配置记录的时间
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    def __repr__(self):
        """仅显示设备 ID 和名称，避免调试输出泄露凭据。"""
        return f"<AiHornConfig id={self.id} name={self.name!r}>"


class AiHornAudio(Base):
    """服务器音频素材；告警绑定保存主键，磁盘文件使用随机名称。"""
    __tablename__ = "ai_horn_audio"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    storage_key = Column(String(64), nullable=False, unique=True)
    size = Column(Integer, nullable=False)
    duration = Column(Float, nullable=False)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
