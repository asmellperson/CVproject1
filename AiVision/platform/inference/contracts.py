"""
/platform/inference/contracts.py
统一规定模型推理结果应该长什么样，以及失败状态叫什么
"""
from __future__ import annotations

from typing import Any, Final

# 模型正常推理完成
INFERENCE_STATUS_OK: Final = "ok"
# 模型执行过程中报错
INFERENCE_STATUS_ERROR: Final = "error"
# 任务被丢弃（任务满了）
INFERENCE_STATUS_DROPPED: Final = "dropped"
# 推理超时
INFERENCE_STATUS_TIMEOUT: Final = "timeout"
# 模型当前不可用（模型worker没启动、模型挂了、当前模型不存在）
INFERENCE_STATUS_UNAVAILABLE: Final = "unavailable"
# 把所有失败状态放一起
INFERENCE_FAILURE_STATUSES: Final = frozenset({
    INFERENCE_STATUS_ERROR,                
    INFERENCE_STATUS_DROPPED,
    INFERENCE_STATUS_TIMEOUT,
    INFERENCE_STATUS_UNAVAILABLE,
})
# 具体失败原因
INFERENCE_ERROR_MODEL: Final = "model_inference_error"
INFERENCE_ERROR_QUEUE_FULL: Final = "infer_queue_full"
INFERENCE_ERROR_TIMEOUT: Final = "inference_timeout"
INFERENCE_ERROR_UNAVAILABLE: Final = "model_unavailable"
INFERENCE_ERROR_INVALID_RESULT: Final = "invalid_inference_result"

def build_inference_result(
    task: dict,
    *,
    status: str,
    detections: list[dict] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    inference_ms: float | None = None,
) -> dict[str, Any]:
    """无论模型成功还是失败。都统一生成同一种结果结构"""
    return {
        # 前五个字段从task继承
        "roi_id": task.get("roi_id"),
        "camera_id": task.get("camera_id"),
        "function_name": task.get("function_name"),
        "request_id": task.get("request_id"),          # 一次推理请求的流水号
        "model_name": task.get("model_name"),
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
        "inference_ms": inference_ms,           # 模型推理耗时
        "detections": [] if detections is None else detections,
    }
