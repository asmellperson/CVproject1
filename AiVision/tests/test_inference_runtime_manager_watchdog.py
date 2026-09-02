# 文件说明：包含模型推理运行管理器看门狗的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import importlib
import queue

from AiVision.platform.inference.runtime_manager import (
    InferenceRuntimeManager,
    WorkerWatchdogState,
)


manager_module = importlib.import_module("AiVision.platform.inference.runtime_manager")


# 功能：定义 `FakeWorker` 类，封装模型推理相关的状态、约束与操作
# 参数：
#   - `running`（bool）：`running` 对应的业务输入值
#   - `alive`（bool）：`alive` 对应的业务输入值
#   - `failed`（bool）：`failed` 对应的业务输入值；默认值为 `False`
# 返回：FakeWorker；返回新建的 `FakeWorker` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_inference_runtime_manager_watchdog.py` 的 `test_watchdog_restarts_dead_worker_after_backoff`
#         实例化本符号；`AiVision/tests/test_inference_runtime_manager_watchdog.py` 的
#         `test_watchdog_stops_retrying_and_alerts_once_when_attempts_exhausted` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class FakeWorker:
    # 功能：初始化或配置 `__init__` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `running`（bool）：`running` 对应的业务输入值
    #   - `alive`（bool）：`alive` 对应的业务输入值
    #   - `failed`（bool）：`failed` 对应的业务输入值；默认值为 `False`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self, *, running: bool, alive: bool, failed: bool = False):
        self.running = running
        self.alive = alive
        self.failed = failed
        self.stop_calls = 0

    # 功能：检查或判断 `is_running` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_running(self) -> bool:
        return self.running

    # 功能：检查或判断 `is_alive` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_alive(self) -> bool:
        return self.alive

    # 功能：检查或判断 `is_failed` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_failed(self) -> bool:
        return self.failed

    # 功能：停止并释放 `stop` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def stop(self) -> None:
        self.stop_calls += 1


# 功能：实现 `_manager_with_worker` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `worker`（FakeWorker）：`worker` 对应的业务输入值
# 返回：InferenceRuntimeManager；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/tests/test_inference_runtime_manager_watchdog.py` 的 `test_watchdog_restarts_dead_worker_after_backoff`
#         调用本符号；`AiVision/tests/test_inference_runtime_manager_watchdog.py` 的
#         `test_watchdog_stops_retrying_and_alerts_once_when_attempts_exhausted` 调用本符号
#   - 内部调用：`InferenceRuntimeManager`、`WorkerWatchdogState`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _manager_with_worker(worker: FakeWorker) -> InferenceRuntimeManager:
    manager = InferenceRuntimeManager()
    manager._model_configs = {
        "test-model": {
            "name": "test-model",
            "import_path": "tests.fake.Worker",
        }
    }
    manager._workers = {"test-model": worker}
    manager._worker_states = {"test-model": WorkerWatchdogState()}
    return manager


def test_watchdog_tick_runs_configured_runtime_monitor_without_workers():
    manager = InferenceRuntimeManager()
    calls = []
    manager.configure_runtime_monitor(lambda: calls.append("tick"))

    manager._watchdog_tick(now=100.0)

    assert calls == ["tick"]


# 功能：验证 `test_watchdog_restarts_dead_worker_after_backoff` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`FakeWorker`、`_manager_with_worker`、`queue.Queue`、`manager.infer_queues['test-model'].put`、`alerts.append`、`manager._watchdog_tick`、`manager.list_running`、`manager.infer_queues['test-model'].empty`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_watchdog_restarts_dead_worker_after_backoff(monkeypatch):
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_max_attempts",
        3,
    )
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_backoff_seconds",
        2.0,
    )
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_max_backoff_seconds",
        30.0,
    )
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_ready_timeout_seconds",
        10.0,
    )
    dead_worker = FakeWorker(running=False, alive=False)
    replacement = FakeWorker(running=True, alive=True)
    manager = _manager_with_worker(dead_worker)
    manager.infer_queues["test-model"] = queue.Queue()
    manager.infer_queues["test-model"].put({"request_id": "stale-1"})
    manager.infer_queues["test-model"].put({"request_id": "stale-2"})
    alerts = []
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *args: alerts.append(args))

    # 功能：启动或执行 `start_replacement` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_model_cfg`（未显式标注）：`_model_cfg` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def start_replacement(_model_cfg):
        manager._workers["test-model"] = replacement
        return True

    monkeypatch.setattr(manager, "_start_one", start_replacement)

    manager._watchdog_tick(now=100.0)
    state = manager._worker_states["test-model"]
    assert state.next_restart_at == 102.0
    assert state.restart_attempts == 0
    assert manager.list_running() == []
    assert manager._workers["test-model"] is dead_worker

    manager._watchdog_tick(now=101.0)
    assert dead_worker.stop_calls == 0

    manager._watchdog_tick(now=102.0)
    assert dead_worker.stop_calls == 1
    assert manager._workers["test-model"] is replacement
    assert manager.infer_queues["test-model"].empty() is True
    assert state.restart_attempts == 1
    assert state.ready_deadline == 112.0

    manager._watchdog_tick(now=103.0)
    assert manager.list_running() == ["test-model"]
    assert state.ready_deadline == 0.0
    assert alerts[0][2] == "模型 Worker 退出"


# 功能：验证 `test_watchdog_stops_retrying_and_alerts_once_when_attempts_exhausted` 对应的模型推理逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`_manager_with_worker`、`FakeWorker`、`alerts.append`、`manager._watchdog_tick`、`manager.runtime_status`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_watchdog_stops_retrying_and_alerts_once_when_attempts_exhausted(monkeypatch):
    monkeypatch.setattr(
        manager_module.settings.runtime,
        "model_worker_restart_max_attempts",
        1,
    )
    manager = _manager_with_worker(FakeWorker(running=False, alive=False))
    manager._worker_states["test-model"].restart_attempts = 1
    alerts = []
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *args: alerts.append(args))

    manager._watchdog_tick(now=200.0)
    manager._watchdog_tick(now=201.0)

    state = manager._worker_states["test-model"]
    assert state.exhausted is True
    assert state.next_restart_at == 0.0
    assert [item[2] for item in alerts] == ["模型 Worker 重启耗尽"]
    assert manager.runtime_status()["models"][0]["status"] == "exhausted"
