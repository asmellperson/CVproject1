# 文件说明：包含模型推理的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import queue
from types import SimpleNamespace

import numpy as np
import pytest

from AiVision.features._shared.consumer import BaseFunctionConsumer
from AiVision.inference.base_worker import BaseModelWorker
from AiVision.inference.contracts import (
    INFERENCE_ERROR_MODEL,
    INFERENCE_ERROR_INVALID_RESULT,
    INFERENCE_ERROR_QUEUE_FULL,
    INFERENCE_ERROR_TIMEOUT,
    INFERENCE_ERROR_UNAVAILABLE,
    INFERENCE_STATUS_DROPPED,
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_OK,
    INFERENCE_STATUS_TIMEOUT,
    INFERENCE_STATUS_UNAVAILABLE,
)


# 功能：定义 `OutcomeConsumer` 类，封装模型推理相关的状态、约束与操作
# 参数：无。
# 返回：OutcomeConsumer；返回新建的 `OutcomeConsumer` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_inference_outcomes.py` 的 `_consumer` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class OutcomeConsumer(BaseFunctionConsumer):
    # 功能：处理 `_process` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（未显式标注）：`roi_list` 对应的业务输入值
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process(self, roi_list, camera_id):
        return []

    # 功能：处理 `post_process` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（未显式标注）：摄像头唯一标识
    #   - `result`（未显式标注）：`result` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def post_process(self, camera_id, result):
        return None


# 功能：定义 `OutcomeWorker` 类，封装模型推理相关的状态、约束与操作
# 参数：
#   - `should_fail`（bool）：`should_fail` 对应的业务输入值；默认值为 `False`
# 返回：OutcomeWorker；返回新建的 `OutcomeWorker` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_inference_outcomes.py` 的 `test_worker_distinguishes_success_from_model_error` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class OutcomeWorker(BaseModelWorker):
    # 功能：初始化或配置 `__init__` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `should_fail`（bool）：`should_fail` 对应的业务输入值；默认值为 `False`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`super().__init__`、`super`、`queue.Queue`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, *, should_fail: bool = False):
        super().__init__(
            infer_queues={"yolo_human": queue.Queue()},
            result_queues={},
            model_name="yolo_human",
            model_path="unused-test-model.pt",
        )
        self.should_fail = should_fail

    # 功能：读取或查询 `load_model` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`object`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def load_model(self):
        return object()

    # 功能：实现 `infer` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model`（未显式标注）：模型配置或实例
    #   - `frame`（未显式标注）：待处理的视频图像帧
    #   - `task_meta`（未显式标注）：`task_meta` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`RuntimeError`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def infer(self, model, frame, task_meta):
        if self.should_fail:
            raise RuntimeError("broken inference")
        return [{"type": "person", "confidence": 0.9}]


class ProcessOutcomeWorker(BaseModelWorker):
    def load_model(self):
        return object()

    def infer(self, model, frame, task_meta):
        return [{"type": task_meta["model_name"], "confidence": 0.9}]


class FailedLoadWorker(ProcessOutcomeWorker):
    def load_model(self):
        raise RuntimeError("invalid test weights")


def test_shared_process_preserves_each_logical_models_result_contract():
    import multiprocessing as mp

    inputs = {name: mp.Queue() for name in ("yolo_human", "yolo_phone")}
    results = mp.Queue()
    worker = ProcessOutcomeWorker(
        infer_queues=inputs, result_queues={"test": results},
        model_name="test-inference-shared", model_path="/unused-test.pt",
    )
    try:
        worker.start()
        assert worker._ready_event.wait(timeout=5)
        for index, (name, inbox) in enumerate(inputs.items()):
            inbox.put({
                "frame": None, "model_name": name, "function_name": "test",
                "camera_id": 7, "roi_id": index, "request_id": name,
            })
        received = {result["model_name"]: result for result in (
            results.get(timeout=5), results.get(timeout=5),
        )}
        assert set(received) == set(inputs)
        for index, name in enumerate(inputs):
            assert received[name]["status"] == INFERENCE_STATUS_OK
            assert received[name]["request_id"] == name
            assert received[name]["roi_id"] == index
            assert received[name]["camera_id"] == 7
            assert received[name]["function_name"] == "test"
    finally:
        worker.stop()
        for channel in (*inputs.values(), results):
            channel.close()
            channel.join_thread()
    assert not worker.is_alive()


def test_loading_error_reaches_parent_and_never_reports_ready():
    worker = FailedLoadWorker(
        infer_queues={}, result_queues={},
        model_name="test-inference-failure", model_path="/unused-test.pt",
    )
    try:
        worker.start()
        assert worker._failed_event.wait(timeout=5)
        assert worker.failure_message() == "invalid test weights"
        assert not worker.is_running()
        assert not worker.is_ready()
    finally:
        worker.stop()
    assert not worker.is_alive()


# 功能：实现 `_consumer` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `infer_dict`（dict）：`infer_dict` 对应的业务输入值
#   - `result_queue`（queue.Queue | None）：`result_queue` 对应的业务输入值；默认值为 `None`
# 返回：OutcomeConsumer；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`OutcomeConsumer`、`SimpleNamespace`、`queue.Queue`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _consumer(infer_dict: dict, result_queue: queue.Queue | None = None) -> OutcomeConsumer:
    return OutcomeConsumer(
        spec=SimpleNamespace(name="outcome-test"),
        infer_dict=infer_dict,
        result_queue=result_queue or queue.Queue(),
        latest_frames={},
        is_camera_active=lambda _name: True,
    )


# 功能：实现 `_task` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `roi_id`（int）：`roi_id` 对应业务对象的唯一标识；默认值为 `0`
# 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_inference_outcomes.py` 的 `test_worker_distinguishes_success_from_model_error` 调用本符号
#   - 内部调用：`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _task(roi_id: int = 0) -> dict:
    return {
        "roi_id": roi_id,
        "camera_id": 7,
        "frame": np.zeros((8, 8, 3), dtype=np.uint8),
        "function_name": "outcome-test",
        "request_id": "outcome-test:7:123",
        "model_name": "test-model",
    }


# 功能：验证 `test_worker_distinguishes_success_from_model_error` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`OutcomeWorker()._execute_task`、`OutcomeWorker`、`object`、`_task`、`OutcomeWorker(should_fail=True)._execute_task`。
# 副作用/注意事项：可能读取或修改数据库事务。
def test_worker_distinguishes_success_from_model_error():
    success = OutcomeWorker()._execute_task(object(), _task())
    failure = OutcomeWorker(should_fail=True)._execute_task(object(), _task())

    assert success["status"] == INFERENCE_STATUS_OK
    assert success["error_code"] is None
    assert success["detections"] == [{"type": "person", "confidence": 0.9}]
    assert success["inference_ms"] is not None

    assert failure["status"] == INFERENCE_STATUS_ERROR
    assert failure["error_code"] == INFERENCE_ERROR_MODEL
    assert failure["error_message"] == "broken inference"
    assert failure["detections"] == []


# 功能：验证 `test_dispatch_reports_model_unavailable_for_camera_roi` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`_consumer`、`consumer.dispatch_inference_sync`、`np.zeros`、`range`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dispatch_reports_model_unavailable_for_camera_roi():
    consumer = _consumer({})

    results = consumer.dispatch_inference_sync(
        7,
        "missing-model",
        np.zeros((4, 4, 3), dtype=np.uint8),
    )

    assert results["roi_id"] == 0
    assert results["status"] == INFERENCE_STATUS_UNAVAILABLE
    assert results["error_code"] == INFERENCE_ERROR_UNAVAILABLE


# 功能：验证 `test_dispatch_reports_queue_full_without_losing_roi_identity` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`queue.Queue`、`infer_queue.put`、`_consumer`、`consumer.dispatch_inference_sync`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dispatch_reports_queue_full_without_losing_roi_identity():
    infer_queue = queue.Queue(maxsize=1)
    infer_queue.put({"occupied": True})
    consumer = _consumer({"test-model": infer_queue})

    results = consumer.dispatch_inference_sync(
        7,
        "test-model",
        np.zeros((4, 4, 3), dtype=np.uint8),
    )

    assert results["roi_id"] == 0
    assert results["status"] == INFERENCE_STATUS_DROPPED
    assert results["error_code"] == INFERENCE_ERROR_QUEUE_FULL
    assert results["detections"] == []


# 功能：验证 `test_dispatch_keeps_partial_result_roi_and_marks_other_roi_timeout` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`queue.Queue`、`result_queue.put`、`_consumer`、`consumer.dispatch_inference_sync`、`np.zeros`、`range`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_dispatch_ignores_stale_request_then_accepts_current_result(monkeypatch):
    monkeypatch.setattr("AiVision.features._shared.consumer.time.monotonic_ns", lambda: 123)
    infer_queue, result_queue = queue.Queue(), queue.Queue()
    task = _task()
    result_queue.put({**task, "request_id": "stale", "detections": [{"type": "wrong"}]})
    result_queue.put({**task, "status": INFERENCE_STATUS_OK, "detections": [{"type": "person"}]})
    consumer = _consumer({"test-model": infer_queue}, result_queue)
    roi = np.zeros((4, 4, 3), dtype=np.uint8)
    result = consumer.dispatch_inference_sync(7, "test-model", roi, timeout=0.01)
    assert result["status"] == INFERENCE_STATUS_OK
    assert result["detections"] == [{"type": "person"}]
    assert consumer.inference_outcome_counts == {INFERENCE_STATUS_OK: 1}
    assert infer_queue.qsize() == 1
    assert infer_queue.get_nowait()["frame"] is roi


@pytest.mark.parametrize("payload", [
    {"detections": []}, {"status": INFERENCE_STATUS_OK},
    {"status": "unexpected", "detections": []},
    {"status": INFERENCE_STATUS_OK, "detections": None},
    {"status": INFERENCE_STATUS_OK, "detections": {}},
])
def test_dispatch_rejects_incomplete_results_instead_of_defaulting_to_success(monkeypatch, payload):
    monkeypatch.setattr("AiVision.features._shared.consumer.time.monotonic_ns", lambda: 123)
    infer_queue, result_queue = queue.Queue(), queue.Queue()
    result_queue.put({**_task(), **payload})
    consumer = _consumer({"test-model": infer_queue}, result_queue)
    result = consumer.dispatch_inference_sync(7, "test-model", np.zeros((4, 4, 3)), timeout=.01)
    assert result["status"] == INFERENCE_STATUS_ERROR
    assert result["error_code"] == INFERENCE_ERROR_INVALID_RESULT
    assert consumer.inference_outcome_counts == {INFERENCE_STATUS_ERROR: 1}


def test_dispatch_reports_timeout_for_missing_current_camera_result():
    consumer = _consumer({"test-model": queue.Queue()})
    result = consumer.dispatch_inference_sync(7, "test-model", np.zeros((4, 4, 3), np.uint8), timeout=0)
    assert result["status"] == INFERENCE_STATUS_TIMEOUT
    assert result["error_code"] == INFERENCE_ERROR_TIMEOUT
    assert result["camera_id"] == 7


# 功能：验证 `test_consecutive_failures_emit_one_alert_and_are_exposed` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`_consumer`、`queue.Queue`、`alerts.append`、`range`、`consumer.dispatch_inference_sync`、`np.zeros`、`consumer.inference_status`、`len`、`consumer._record_inference_outcomes`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_consecutive_failures_emit_one_alert_and_are_exposed(monkeypatch):
    monkeypatch.setattr(
        "AiVision.features._shared.consumer.settings.runtime.inference_alert_consecutive_failures",
        2,
    )
    monkeypatch.setattr(
        "AiVision.features._shared.consumer.settings.runtime.inference_alert_cooldown_seconds",
        300.0,
    )
    consumer = _consumer({"test-model": queue.Queue()})
    consumer.config_cache[7] = {"name": "东门摄像头"}
    alerts = []
    monkeypatch.setattr(
        consumer,
        "_notify_runtime_alert",
        lambda event_type, detail, **kwargs: alerts.append((event_type, detail, kwargs)),
    )

    for _index in range(2):
        consumer.dispatch_inference_sync(
            7,
            "test-model",
            np.zeros((4, 4, 3), dtype=np.uint8),
            timeout=0,
        )

    snapshot = consumer.inference_status()
    assert snapshot["totals"] == {INFERENCE_STATUS_TIMEOUT: 2}
    assert snapshot["targets"] == [{
        "model_name": "test-model",
        "camera_id": 7,
        "counts": {INFERENCE_STATUS_TIMEOUT: 2},
        "consecutive_failures": 2,
        "last_outcome": {
            "status": INFERENCE_STATUS_TIMEOUT,
            "error_code": INFERENCE_ERROR_TIMEOUT,
            "updated_at": snapshot["targets"][0]["last_outcome"]["updated_at"],
        },
    }]
    assert len(alerts) == 1
    assert alerts[0][0] == "推理连续异常"
    assert "东门摄像头" in alerts[0][1]
    assert alerts[0][2]["target_key"] == "outcome-test:test-model:7"

    consumer._record_inference_outcomes(
        camera_id=7,
        model_name="test-model",
        outcomes=[{"status": INFERENCE_STATUS_OK}],
    )
    assert consumer.inference_status()["targets"][0]["consecutive_failures"] == 0
