"""
features/_shared/spec.py
FeatureSpec — 功能元数据声明。

每个 features/{package}/spec.py 定义唯一的 SPEC = FeatureSpec(...),
features/registry.py 显式注册内置功能；包名与 SPEC.name 业务标识分离。

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
    name: str                                   # 功能名
    display_name: str                           # 前端显示的名字
    consumer_cls: Type                          # 使用哪个consumer
    orm_class: Type[DeclarativeBase]            # 配置哪张ORM表
    config_schema: Type[BaseModel]              # 配置由哪个Schema校验
    required_models: tuple[str, ...] = field(default_factory=tuple)     # 需要哪个模型
    violation_type: int = 0                     # 告警类型是多少
    def __repr__(self) -> str:
        models = list(self.required_models) or "无"
        return f"<FeatureSpec name={self.name!r} display={self.display_name!r} models={models}>"
