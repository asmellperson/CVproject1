# 文件说明：定义`contracts` 模块的数据结构与类型契约。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""推理任务结果的稳定字段与状态常量。"""
from __future__ import annotations

from typing import Any, Final


INFERENCE_STATUS_OK: Final = "ok"
INFERENCE_STATUS_ERROR: Final = "error"
INFERENCE_STATUS_DROPPED: Final = "dropped"
INFERENCE_STATUS_TIMEOUT: Final = "timeout"
INFERENCE_STATUS_UNAVAILABLE: Final = "unavailable"
INFERENCE_FAILURE_STATUSES: Final = frozenset({
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_DROPPED,
    INFERENCE_STATUS_TIMEOUT,
    INFERENCE_STATUS_UNAVAILABLE,
})

INFERENCE_ERROR_MODEL: Final = "model_inference_error"
INFERENCE_ERROR_QUEUE_FULL: Final = "infer_queue_full"
INFERENCE_ERROR_TIMEOUT: Final = "inference_timeout"
INFERENCE_ERROR_UNAVAILABLE: Final = "model_unavailable"


# 功能：构造兼容现有消费者、同时可区分失败原因的推理结果；输入与输出详见下方说明
# 参数：
#   - `task`（dict）：`task` 对应的业务输入值
#   - `status`（str）：当前或目标状态值
#   - `detections`（list[dict] | None）：`detections` 对应的业务输入值；默认值为 `None`
#   - `error_code`（str | None）：`error_code` 对应的业务输入值；默认值为 `None`
#   - `error_message`（str | None）：`error_message` 对应的业务输入值；默认值为 `None`
#   - `inference_ms`（float | None）：`inference_ms` 对应的时间间隔或时长；默认值为 `None`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::dispatch_inference_sync` 调用本符号
#   - 内部调用：`task.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def build_inference_result(
    task: dict,
    *,
    status: str,
    detections: list[dict] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    inference_ms: float | None = None,
) -> dict[str, Any]:
    """构造兼容现有消费者、同时可区分失败原因的推理结果。"""
    return {
        "roi_id": task.get("roi_id"),
        "camera_id": task.get("camera_id"),
        "function_name": task.get("function_name"),
        "request_id": task.get("request_id"),
        "model_name": task.get("model_name"),
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
        "inference_ms": inference_ms,
        "detections": [] if detections is None else detections,
    }
