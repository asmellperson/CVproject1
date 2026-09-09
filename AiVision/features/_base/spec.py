# 文件说明：实现`spec` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/_base/spec.py
FeatureSpec — 功能元数据声明。

每个 features/{name}/__init__.py 都会导出一个 SPEC = FeatureSpec(...),
features/__init__.py 会自动发现并注册到全局 _REGISTRY。

后续的所有跨功能逻辑(API 路由、ORM 注册、Consumer 启动、配置缓存)
都通过 SPEC 反射,不需要硬编码功能名。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Type
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase


# 功能：单个功能的全部元数据；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `display_name`（str）：`display_name` 对应的业务输入值
#   - `consumer_cls`（Type）：`consumer_cls` 对应的业务输入值
#   - `orm_class`（Type[DeclarativeBase]）：`orm_class` 对应的业务输入值
#   - `config_schema`（Type[BaseModel]）：`config_schema` 对应的业务输入值
#   - `required_models`（tuple[str, ...]）：`required_models` 对应的业务输入值
#   - `violation_type`（int）：`violation_type` 对应的业务输入值
#   - `departments`（tuple[str, ...]）：`departments` 对应的业务输入值
# 返回：FeatureSpec；返回新建的 `FeatureSpec` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`field`、`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class FeatureSpec:
    """单个功能的全部元数据"""

    name: str
    """机器名,作为 URL 参数和数据库 function_name 字段。如 'blocks' / 'detect_face'"""

    display_name: str
    """UI 友好名称。如 '区域入侵检测'"""

    consumer_cls: Type
    """对应 AiVision.features._base.consumer.BaseFunctionConsumer 子类。运行时由 Orchestrator 实例化。"""

    orm_class: Type[DeclarativeBase]
    """配置 ORM 表类。继承自 AiVision.features._base.orm.FeatureConfigBase。"""

    config_schema: Type[BaseModel]
    """前端配置的 Pydantic 校验模型。继承自 AiVision.features._base.schema.FeatureConfigSchema。"""

    required_models: tuple[str, ...] = field(default_factory=tuple)
    """需要的推理模型名列表。空 tuple 表示无需推理(如 blocks/door 纯帧差)。
    
    注意: 用模型 name(如 'yolo_phone')而不是 model_id,这样不依赖数据库 id 顺序。
    """

    violation_type: int = 0
    """告警性质枚举,用于写入历史表 ai_violation_image.violation_type。"""

    departments: tuple[str, ...] = field(default_factory=tuple)
    """功能归属的唯一来源；编码必须在部门注册表中。空 tuple 表示无归属部门。"""

    def resolve_camera_department(self, department: str | None) -> str | None:
        """新建并启用、启用已有摄像头时共用的部门规则；不修改摄像头。"""
        # 一个功能可以有多个事业部
        allowed_departments = tuple(self.departments)
        requested_department = department
        # 如果检测功能只属于一个部门，不填摄像头的部门也没关系，直接使用检测功能的部门
        # 如果检测功能支持多个部门，那必须让用户明确选择摄像头对应的部门
        if allowed_departments:
            if not requested_department:
                if len(allowed_departments) != 1:
                    raise ValueError("department 是必填项；请先明确选择摄像头所属部门后再启用")
                requested_department = allowed_departments[0]
            # 检测摄像头的部门是否属于功能所对应的部门
            if requested_department not in allowed_departments:
                raise ValueError(
                    f"department 必须属于当前功能: {', '.join(allowed_departments)}"
                )
        return requested_department

    # 功能：实现 `__repr__` 对应的`spec` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def __repr__(self) -> str:
        models = list(self.required_models) or "无"
        depts = list(self.departments) or "无"
        return f"<FeatureSpec name={self.name!r} display={self.display_name!r} models={models} depts={depts}>"
