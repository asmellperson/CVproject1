# utils.py
"""通用工具函数模块。"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    """确保目录存在，不存在时递归创建，返回 Path 对象。

    等价于 mkdir -p，已存在时不报错。
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_str() -> str:
    """返回当前时间的字符串，格式 "YYYYMMDD_HHMMSS"，用于生成文件名。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_float(value: Any, default: float = 0.0) -> float:
    """将任意值转换为 float，转换失败时返回 default 而非抛出异常。

    适用于解析来自外部配置或网络数据的数值字段，防止类型错误中断流程。
    """
    try:
        return float(value)
    except Exception:
        return default
