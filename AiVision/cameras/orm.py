"""摄像头资源、所属事业部及事业部内展示顺序。"""
from __future__ import annotations
from sqlalchemy import Column, Integer, String, Boolean, JSON, TIMESTAMP, Text, text

from AiVision.core.db import Base

class AiCameraConfig(Base):
    """对应ai_camera_config数据库，一行数据就是一台摄像头基本配置"""
    __tablename__ = "ai_camera_config"
    # 数据库主键
    id = Column(Integer, primary_key=True, autoincrement=True)
    # 摄像头展示名称，nullable:不能为空，unique：不能有两台摄像头重名，index：数据库给它建索引，方便按名称查询
    name = Column(String(100), nullable=False, unique=True, index=True)
    # 摄像头视频源地址
    url = Column(String(500), nullable=False)
    # shm:shared memory:共享内存，其实使用camera_id也可以当共享内存名，但是shm_name更灵活
    shm_name = Column(String(100), nullable=False, unique=True, index=True,
                      comment="共享内存标识,全系统唯一")
    fps = Column(Integer, default=5)
    # 摄像头断流以后，Runtime最多允许自动重启多少次
    max_restart = Column(Integer, default=10, comment="摄像头断流最大自动重启次数")
    function_config = Column(JSON, nullable=True)
    # 摄像头总开关
    enable = Column(Boolean, default=True)
    # 这一条摄像头记录什么时候创建，server_default默认时间由mysql生成
    import_time = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    # 摄像头最近什么时候改过
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    import_message = Column(Text)
    # 摄像头画面尺寸
    shape = Column(JSON, nullable=True, default=[1080, 1920, 3], comment="默认分辨率 [H,W,C]")
    department = Column(String(100), nullable=True, comment="归属部门")
    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"),
                        index=True, comment="事业部内摄像头展示排序")

    def __repr__(self):
        # Python打印当前对象的时候会输出什么
        return f"<AiCameraConfig id={self.id} name={self.name!r} enable={self.enable} dept={self.department!r}>"


def get_camera_by_key(session, key: str | int) -> AiCameraConfig | None:
    """字符串依次匹配 shm_name、展示名、数字或 camera_<id> 别名；整数直接查主键。"""
    if isinstance(key, int) and not isinstance(key, bool):
        return session.get(AiCameraConfig, key)
    key = (key or "").strip()
    if not key:
        return None
    for column in (AiCameraConfig.shm_name, AiCameraConfig.name):
        camera = session.query(AiCameraConfig).filter(column == key).first()
        if camera is not None:
            return camera
    camera_id = key.removeprefix("camera_") if key.startswith("camera_") else key
    if camera_id.isascii() and camera_id.isdecimal():
        return session.get(AiCameraConfig, int(camera_id))
    return None
