# 文件说明：定义数据库模型的持久化模型、数据库连接或存取能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/inference/orm.py
推理模型配置表 — 与旧表 ai_model 一致。
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP, text
from core.db import Base


# 功能：定义 `AiModel` 类，封装数据库模型相关的状态、约束与操作
# 参数：无。
# 返回：AiModel；返回新建的 `AiModel` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/service.py` 的 `ModelService::create_model` 实例化本符号
#   - 内部调用：`Column`、`String`、`text`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class AiModel(Base):
    __tablename__ = "ai_model"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    type = Column(String(50), nullable=False, comment="yolo / mediapipe / other")
    path = Column(String(500), nullable=False, comment="模型文件路径")
    import_path = Column(
        String(255), nullable=True,
        comment="Worker 类导入路径,如 platform.inference.workers.yolo_detector.YoloDetectorWorker",
    )
    description = Column(
        Text, nullable=True,
        comment="说明 / 配置 JSON(可包含 class_filter, type_label, conf, iou)",
    )
    enable = Column(Boolean, default=True, index=True)
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
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
        return f"<AiModel id={self.id} name={self.name!r}>"
