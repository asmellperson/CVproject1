# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/camera/orm.py
摄像头主配置表 ORM。

字段与旧表 ai_camera_config 一致 — 不改表结构。
"""
from __future__ import annotations
from sqlalchemy import Column, Integer, String, Boolean, JSON, TIMESTAMP, Text, text

from AiVision.core.db import Base


# 功能：定义 `AiCameraConfig` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：AiCameraConfig；返回新建的 `AiCameraConfig` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Column`、`String`、`text`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AiCameraConfig(Base):
    __tablename__ = "ai_camera_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    url = Column(String(500), nullable=False)
    shm_name = Column(String(100), nullable=False, unique=True, index=True,
                      comment="共享内存标识,全系统唯一")
    fps = Column(Integer, default=5)
    max_restart = Column(Integer, default=10, comment="摄像头断流最大自动重启次数")

    # 旧的 function_config JSON 字段保留 — 仅作历史兼容,新代码不读不写
    function_config = Column(JSON, nullable=True)
    enable = Column(Boolean, default=True)

    import_time = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    import_message = Column(Text)
    shape = Column(JSON, nullable=True, default=[1080, 1920, 3], comment="默认分辨率 [H,W,C]")
    department = Column(String(100), nullable=True, comment="归属部门")

    # 功能：实现 `__repr__` 对应的数据库模型逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def __repr__(self):
        return f"<AiCameraConfig id={self.id} name={self.name!r} enable={self.enable} dept={self.department!r}>"
