# 文件说明：实现`utils` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# utils.py
"""通用工具函数模块。"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any


# 功能：确保目录存在，不存在时递归创建，返回 Path 对象；输入与输出详见下方说明
# 参数：
#   - `path`（str | os.PathLike[str]）：目标路径
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/alarm_clip_recorder.py` 的 `AlarmClipRecorder::__init__`
#         调用本符号；`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::__init__`
#         调用本符号；`AiVision/integrations/guard_room/src/vehicle_episode_recorder.py` 的 `VehicleEpisodeRecorder::__init__`
#         调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的 `GuardRoomRuntime::_build_writer` 调用本符号
#   - 内部调用：`Path`、`p.mkdir`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def ensure_dir(path: str | os.PathLike[str]) -> Path:
    """确保目录存在，不存在时递归创建，返回 Path 对象。

    等价于 mkdir -p，已存在时不报错。
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# 功能：返回当前时间的字符串，格式 "YYYYMMDD_HHMMSS"，用于生成文件名；输入与输出详见下方说明
# 参数：无。
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::emit` 调用本符号
#   - 内部调用：`datetime.now().strftime`、`datetime.now`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def now_str() -> str:
    """返回当前时间的字符串，格式 "YYYYMMDD_HHMMSS"，用于生成文件名。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# 功能：将任意值转换为 float，转换失败时返回 default 而非抛出异常；输入与输出详见下方说明
# 参数：
#   - `value`（Any）：待转换、校验或写入的值
#   - `default`（float）：`default` 对应的业务输入值；默认值为 `0.0`
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def safe_float(value: Any, default: float = 0.0) -> float:
    """将任意值转换为 float，转换失败时返回 default 而非抛出异常。

    适用于解析来自外部配置或网络数据的数值字段，防止类型错误中断流程。
    """
    try:
        return float(value)
    except Exception:
        return default
