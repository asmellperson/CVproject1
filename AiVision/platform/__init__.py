# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
AiVision runtime platform package.

本项目历史上使用了顶层包名 ``platform``，与 Python 标准库同名。为避免第三方库
``import platform`` 被误伤，这里代理标准库 platform.py 的公开属性，同时作为本项目
``platform.camera`` / ``platform.inference`` 等子包的承载包。
"""
from __future__ import annotations

import importlib.util
import os

# 不要在这里 import sysconfig；sysconfig 自身会 import platform，容易形成递归。
_stdlib_dir = os.path.dirname(os.__file__)
_stdlib_platform_path = os.path.join(_stdlib_dir, "platform.py")
_spec = importlib.util.spec_from_file_location("_aivision_stdlib_platform", _stdlib_platform_path)
if _spec is not None and _spec.loader is not None:
    _stdlib_platform = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_stdlib_platform)
    for _name in dir(_stdlib_platform):
        if _name.startswith("__") and _name not in {"__version__"}:
            continue
        globals().setdefault(_name, getattr(_stdlib_platform, _name))

__all__ = [name for name in globals() if not name.startswith("_")]
