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
    name: str                                   # 功能名
    display_name: str                           # 前端显示的名字
    consumer_cls: Type                          # 使用哪个consumer
    orm_class: Type[DeclarativeBase]            # 配置哪张ORM表
    config_schema: Type[BaseModel]              # 配置由哪个Schema校验
    required_models: tuple[str, ...] = field(default_factory=tuple)     # 需要哪个模型
    violation_type: int = 0                     # 告警类型是多少
    departments: tuple[str, ...] = field(default_factory=tuple)         #允许哪些事业部使用

    def resolve_camera_department(self, department: str | None) -> str | None:
        """
        新建并启用、启用已有摄像头时共用的部门规则；不修改摄像头。
        逻辑有三种情况：
            1、Feature只有一个事业部，自动绑定当前事业部
            2、Feature支持多个事业部，department 是必填项；请先明确选择摄像头所属部门后再启用
            3、用户填错了事业部，直接报错
        """
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

    def __repr__(self) -> str:
        models = list(self.required_models) or "无"
        depts = list(self.departments) or "无"
        return f"<FeatureSpec name={self.name!r} display={self.display_name!r} models={models} depts={depts}>"
