# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：扫描 features/ 下所有非下划线开头的子目录；输入与输出详见下方说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`__import__`、`pkgutil.iter_modules`、`name.startswith`、`importlib.import_module`、`logger.warning`、`getattr`、`isinstance`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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


# 功能：返回所有已注册的 feature(只读副本)；输入与输出详见下方说明
# 参数：无。
# 返回：dict[str, FeatureSpec]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/core/cache.py` 的 `ConfigCache::_load_function_configs` 调用本符号；`AiVision/api/v2/logistics_channels.py` 的
#         `get_member_camera_config` 调用本符号；`AiVision/api/v2/logistics_channels.py` 的 `update_member_camera_config`
#         调用本符号；`AiVision/api/v2/logistics_channels.py` 的 `_channel_alarm_query` 调用本符号；另有 34 处静态调用
#   - 内部调用：`dict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def all_specs() -> dict[str, FeatureSpec]:
    """返回所有已注册的 feature(只读副本)"""
    return dict(_REGISTRY)


# 功能：读取或查询 `get_spec` 对应的`__init__` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `name`（str）：业务对象名称
# 返回：FeatureSpec | None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/core/cache.py` 的 `ConfigCache::refresh_function` 调用本符号；`AiVision/features/_base/api.py` 的 `_require_spec`
#         调用本符号；`AiVision/api/compat.py` 的 `_require_legacy_spec` 调用本符号
#   - 内部调用：`_REGISTRY.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def get_spec(name: str) -> FeatureSpec | None:
    return _REGISTRY.get(name)


# 功能：返回所有 feature 的 ORM 类 — 启动时 Base.metadata.create_all 需要；输入与输出详见下方说明
# 参数：无。
# 返回：list[type]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_REGISTRY.values`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def list_orm_classes() -> list[type]:
    """返回所有 feature 的 ORM 类 — 启动时 Base.metadata.create_all 需要"""
    return [s.orm_class for s in _REGISTRY.values()]
