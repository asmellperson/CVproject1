"""
features/__init__.py
自动发现所有 feature 子目录并注册到 _REGISTRY。

加新功能 = 新建 features/{name}/ 目录 + 写一个 SPEC = FeatureSpec(...)
不需要修改本文件,启动时自动扫描。
"""
from __future__ import annotations
import importlib
import pkgutil
from features._base.spec import FeatureSpec

_REGISTRY: dict[str, FeatureSpec] = {}


def _discover():
    """扫描 features/ 下所有非下划线开头的子目录"""
    package = __import__("features", fromlist=["*"])
    for _, name, ispkg in pkgutil.iter_modules(package.__path__):
        if name.startswith("_") or not ispkg:
            continue
        try:
            module = importlib.import_module(f"features.{name}")
        except Exception as e:
            from core.logger import logger
            logger.warning(f"[features] 加载 features.{name} 失败: {e}")
            continue
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, FeatureSpec):
            _REGISTRY[spec.name] = spec
        else:
            from core.logger import logger
            logger.warning(f"[features] features.{name} 没有导出 SPEC,跳过")


_discover()


def all_specs() -> dict[str, FeatureSpec]:
    """返回所有已注册的 feature(只读副本)"""
    return dict(_REGISTRY)


def get_spec(name: str) -> FeatureSpec | None:
    return _REGISTRY.get(name)


def list_orm_classes() -> list[type]:
    """返回所有 feature 的 ORM 类 — 启动时 Base.metadata.create_all 需要"""
    return [s.orm_class for s in _REGISTRY.values()]
