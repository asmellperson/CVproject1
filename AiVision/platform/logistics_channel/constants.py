# 文件说明：实现`constants` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""物流通道共享常量与功能白名单。"""
from __future__ import annotations

from datetime import time


LOGISTICS_FEATURES = frozenset({
    "detect_logistics_single_person",
    "detect_logistics_single_person_electronics_electrician",
    "detect_logistics_single_person_electrical_components",
    "detect_logistics_single_person_precious_metal_recycling",
})

LOGISTICS_FEATURE_DEPARTMENTS = {
    "detect_logistics_single_person": "general_electric",
    "detect_logistics_single_person_electronics_electrician": "electronics_electrician",
    "detect_logistics_single_person_electrical_components": "electrical_components",
    "detect_logistics_single_person_precious_metal_recycling": "precious_metal_recycling",
}

MAX_CAMERAS_PER_CHANNEL = 9
DEFAULT_DETECTION_START = time(8, 0)
DEFAULT_DETECTION_END = time(20, 0)
DEFAULT_PERSON_CONFIDENCE_THRESHOLD = 0.3
DEFAULT_STATUS_STALE_SECONDS = 5.0


# 功能：校验并规范化物流单人检测功能名称；输入与输出详见下方说明
# 参数：
#   - `feature_name`（str）：`feature_name` 对应的业务输入值
# 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::list_channels`
#         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::get_channel`
#         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::create_channel`
#         调用本符号；`AiVision/platform/logistics_channel/service.py` 的 `LogisticsChannelService::update_channel` 调用本符号；另有 19 处静态调用
#   - 内部调用：`isinstance`、`feature_name.strip`、`ValueError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def require_logistics_feature(feature_name: str) -> str:
    """校验并规范化物流单人检测功能名称。"""
    normalized = feature_name.strip() if isinstance(feature_name, str) else ""
    if normalized not in LOGISTICS_FEATURES:
        raise ValueError(f"不支持的物流检测功能: {feature_name!r}")
    return normalized
