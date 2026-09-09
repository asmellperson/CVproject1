# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""物流通道领域模型。"""

from .state import (
    CameraSnapshot,
    CameraSnapshotStore,
    ChannelDecision,
    ChannelPresenceState,
    PersonDetection,
    classify_channel,
    deduplicate_person_detections,
    intersection_over_union,
    translate_person_detection,
)
from .compositor import CameraTile, compose_channel_frame, layout_for_count, letterbox, render_placeholder

__all__ = [
    "CameraSnapshot",
    "CameraSnapshotStore",
    "ChannelDecision",
    "ChannelPresenceState",
    "PersonDetection",
    "classify_channel",
    "deduplicate_person_detections",
    "intersection_over_union",
    "translate_person_detection",
    "CameraTile",
    "compose_channel_frame",
    "layout_for_count",
    "letterbox",
    "render_placeholder",
    "LogisticsChannelService",
    "logistics_channel_service",
    "LogisticsChannelRuntime",
]


# 功能：延迟导出数据库服务，避免 ORM 初始化期间形成包级循环导入；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`AttributeError`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def __getattr__(name: str):
    """延迟导出数据库服务，避免 ORM 初始化期间形成包级循环导入。"""
    if name in {
        "LogisticsChannelService",
        "logistics_channel_service",
    }:
        from .service import (
            LogisticsChannelService,
            logistics_channel_service,
        )

        return {
            "LogisticsChannelService": LogisticsChannelService,
            "logistics_channel_service": logistics_channel_service,
        }[name]
    if name == "LogisticsChannelRuntime":
        from .runtime import LogisticsChannelRuntime

        return LogisticsChannelRuntime
    raise AttributeError(name)
