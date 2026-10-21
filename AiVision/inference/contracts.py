"""Consumer、Worker 与结果路由器共享的推理结果契约。

status 区分成功空检测、执行错误、队列丢弃、超时与不可用；error_code 细分原因。
统一结果保留请求身份，便于按 request_id 匹配并校验来源。这里不执行推理或业务判定。
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
# 主进程结果路由不可用，与模型执行失败分开记录。
INFERENCE_ERROR_ROUTER_STOPPED: Final = "inference_router_stopped"
INFERENCE_ERROR_ROUTER_FAILED: Final = "inference_router_failed"

def build_inference_result(
    task: dict,
    *,
    status: str,
    detections: list[dict] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    inference_ms: float | None = None,
    input_wait_ms: float | None = None,
    completed_at_monotonic: float | None = None,
) -> dict[str, Any]:
    """构造带任务身份的统一结果，不校验状态枚举或检测项内容。

    Args:
        task: 原任务或身份字典，缺失身份字段会写为 None。
        status: 推理状态，调用方应使用本模块的状态常量。
        detections: 检测列表；None 转成新的空列表，已有列表不复制。
        error_code: 失败原因标识，成功时通常为 None。
        error_message: 可供排障的错误说明。
        inference_ms: 模型执行耗时，单位毫秒；未测量时为 None。
        input_wait_ms: 投递至 Worker 开始执行的耗时，包含输入传输和排队。
        completed_at_monotonic: Worker 完成时的单调时钟，仅用于计算结果回传耗时。

    Returns:
        dict: 包含五个身份字段、状态、检测、错误与耗时的统一结构。
    """
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
        "input_wait_ms": input_wait_ms,
        "completed_at_monotonic": completed_at_monotonic,
        "detections": [] if detections is None else detections,
    }
