# 文件说明：实现`ultralytics_compat` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""Ultralytics inference argument compatibility helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ultralytics.cfg import DEFAULT_CFG_DICT


# 功能：Return precision kwargs accepted by the installed Ultralytics version；输入与输出详见下方说明
# 参数：
#   - `use_half`（bool）：`use_half` 对应的业务输入值
#   - `default_cfg`（Mapping[str, Any]）：`default_cfg` 对应的业务输入值；默认值为 `DEFAULT_CFG_DICT`
# 返回：dict[str, int | bool | None]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def yolo_precision_kwargs(
    use_half: bool,
    *,
    default_cfg: Mapping[str, Any] = DEFAULT_CFG_DICT,
) -> dict[str, int | bool | None]:
    """Return precision kwargs accepted by the installed Ultralytics version."""
    if "quantize" in default_cfg:
        return {"quantize": 16 if use_half else None}
    return {"half": use_half}
