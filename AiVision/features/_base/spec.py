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


@dataclass(frozen=True)
class FeatureSpec:
    """单个功能的全部元数据"""

    name: str
    """机器名,作为 URL 参数和数据库 function_name 字段。如 'blocks' / 'detect_face'"""

    display_name: str
    """UI 友好名称。如 '区域入侵检测'"""

    consumer_cls: Type
    """对应 features._base.consumer.BaseFunctionConsumer 子类。运行时由 Orchestrator 实例化。"""

    orm_class: Type[DeclarativeBase]
    """配置 ORM 表类。继承自 features._base.orm.FeatureConfigBase。"""

    config_schema: Type[BaseModel]
    """前端配置的 Pydantic 校验模型。继承自 features._base.schema.FeatureConfigSchema。"""

    required_models: tuple[str, ...] = field(default_factory=tuple)
    """需要的推理模型名列表。空 tuple 表示无需推理(如 blocks/door 纯帧差)。
    
    注意: 用模型 name(如 'yolo_phone')而不是 model_id,这样不依赖数据库 id 顺序。
    """

    violation_type: int = 0
    """违规类型枚举,用于写入 ai_violation_image.violation_type"""

    def __repr__(self) -> str:
        models = list(self.required_models) or "无"
        return f"<FeatureSpec name={self.name!r} display={self.display_name!r} models={models}>"
