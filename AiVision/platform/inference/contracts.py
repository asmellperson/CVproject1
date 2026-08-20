"""推理任务结果的稳定字段与状态常量。"""
from __future__ import annotations

from typing import Any, Final


INFERENCE_STATUS_OK: Final = "ok"
INFERENCE_STATUS_ERROR: Final = "error"
INFERENCE_STATUS_DROPPED: Final = "dropped"
INFERENCE_STATUS_TIMEOUT: Final = "timeout"
INFERENCE_STATUS_UNAVAILABLE: Final = "unavailable"

INFERENCE_ERROR_MODEL: Final = "model_inference_error"
INFERENCE_ERROR_QUEUE_FULL: Final = "infer_queue_full"
INFERENCE_ERROR_TIMEOUT: Final = "inference_timeout"
INFERENCE_ERROR_UNAVAILABLE: Final = "model_unavailable"


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
