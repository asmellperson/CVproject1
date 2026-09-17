# 文件说明：包含模型推理运行管理器看门狗的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import importlib
import queue
import pytest

from AiVision.inference.runtime_manager import (
    InferenceRuntimeManager,
    WorkerWatchdogState,
)


manager_module = importlib.import_module("AiVision.inference.runtime_manager")


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
        self.model_path = "/test/model.pt"

    def failure_message(self):
        return "load failed" if self.failed else ""

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
            "model_names": ["test-model"],
        }
    }
    manager._workers = {"test-model": worker}
    manager._model_owners = {"test-model": "test-model"}
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


class ManagedWorker(FakeWorker):
    instances = []

    def __init__(self, *, infer_queues, result_queues, model_name, model_path):
        super().__init__(running=False, alive=False)
        self.infer_queues = infer_queues
        self.model_name = model_name
        self.model_path = model_path
        self.instances.append(self)

    def start(self):
        self.failed = "bad" in self.model_path
        self.running = not self.failed
        self.alive = not self.failed

    def stop(self):
        super().stop()
        self.running = False
        self.alive = False


@pytest.fixture
def fixed_runtime(tmp_path, monkeypatch):
    from dataclasses import replace
    from AiVision.inference import model_paths
    from AiVision.inference.model_registry import MODEL_SPECS

    config = tmp_path / "model_paths.yaml"
    shared = tmp_path / "shared.pt"
    face = tmp_path / "det_10g.onnx"
    shared.write_bytes(b"shared weights")
    face.write_bytes(b"face weights")
    config.write_text(
        f"models:\n  yolo_human:\n    path: {shared}\n"
        f"  yolo_phone:\n    path: {shared}\n  insightface_detection:\n    path: {face}\n"
    )
    monkeypatch.setattr(model_paths.settings.model_paths, "config_path", str(config))
    model_paths.clear_model_paths_cache()
    monkeypatch.setattr(manager_module, "MODEL_SPECS", {
        name: replace(spec, worker_class=ManagedWorker) for name, spec in MODEL_SPECS.items()
    })
    monkeypatch.setattr(manager_module, "Queue", queue.Queue)
    ManagedWorker.instances = []
    manager = InferenceRuntimeManager()
    monkeypatch.setattr(manager, "_start_watchdog", lambda: None)
    manager.initialize_queues()
    manager.start_all()
    yield manager, config, shared, face
    manager.stop_all()
    model_paths.clear_model_paths_cache()


def test_fixed_models_share_one_physical_worker_and_report_logical_status(fixed_runtime):
    manager, _, shared, _ = fixed_runtime
    assert len(ManagedWorker.instances) == 2
    assert set(manager.list_running()) == {"yolo_human", "yolo_phone", "insightface_detection"}
    assert manager._model_owners["yolo_human"] == manager._model_owners["yolo_phone"]
    shared_worker = manager._workers["yolo_human"]
    assert set(shared_worker.infer_queues) == {"yolo_human", "yolo_phone"}
    items = {item["name"]: item for item in manager.list_models()}
    assert items["yolo_phone"]["runtime"]["loaded_path"] == str(shared)
    assert items["yolo_phone"]["runtime"]["shared_models"] == ["yolo_human", "yolo_phone"]
    assert not any("enable" in item or "id" in item or "database_path" in item for item in items.values())


def test_reload_splits_and_merges_shared_weights_without_changing_consumer_queues(fixed_runtime, tmp_path):
    manager, _, shared, _ = fixed_runtime
    queues = dict(manager.infer_queues)
    original_shared = manager._workers["yolo_human"]
    original_face = manager._workers["insightface_detection"]
    manager._worker_states["insightface_detection"].restart_attempts = 2
    phone = tmp_path / "phone.pt"
    phone.write_bytes(b"phone weights")

    result = manager.update_model_path("yolo_phone", str(phone))
    assert result["configuration_saved"] is True
    assert result["load_status"] == "loading"
    manager._reload_thread.join(timeout=2)
    assert not manager._reload_thread.is_alive()
    assert len(manager._workers) == 3
    assert original_shared.stop_calls == 1
    assert original_face.stop_calls == 0
    assert manager._workers["insightface_detection"] is original_face
    assert manager._worker_states["insightface_detection"].restart_attempts == 2
    assert manager._workers["yolo_phone"].model_path == str(phone)
    assert manager.infer_queues == queues
    assert manager._reload_results["yolo_phone"]["status"] == "succeeded"

    manager.update_model_path("yolo_phone", str(shared))
    manager._reload_thread.join(timeout=2)
    assert len(manager._workers) == 2
    assert manager._model_owners["yolo_phone"] == "yolo_human"
    assert manager.infer_queues == queues
    assert manager._workers["insightface_detection"] is original_face


def test_physical_identity_deduplicates_symlinks_and_hardlinks(fixed_runtime, tmp_path):
    import os

    manager, _, shared, _ = fixed_runtime
    alias = tmp_path / "linked.pt"
    os.link(shared, alias)
    manager.update_model_path("yolo_phone", str(alias))
    manager._reload_thread.join(timeout=2)
    assert len(manager._workers) == 2
    assert manager._model_owners["yolo_phone"] == "yolo_human"
    symlink = tmp_path / "symlink.pt"
    symlink.symlink_to(shared)
    result = manager.update_model_path("yolo_phone", str(symlink))
    manager._reload_thread.join(timeout=2)
    assert result["path"] == str(shared)
    assert len(manager._workers) == 2


def test_failed_reload_is_saved_but_failed_and_still_watched(fixed_runtime, tmp_path, monkeypatch):
    from AiVision.inference.model_paths import load_model_paths

    manager, _, _, _ = fixed_runtime
    bad = tmp_path / "bad.pt"
    bad.write_bytes(b"invalid weights")
    result = manager.update_model_path("yolo_phone", str(bad))
    manager._reload_thread.join(timeout=2)
    assert result["configuration_saved"] is True
    assert load_model_paths()["yolo_phone"] == str(bad)
    phone = next(item for item in manager.list_models() if item["name"] == "yolo_phone")
    assert phone["reload"] == {"status": "failed", "error": "load failed"}
    assert phone["runtime"]["running"] is False
    assert phone["runtime"]["loaded_path"] == ""
    monkeypatch.setattr(manager_module.settings.runtime, "model_worker_restart_backoff_seconds", 1)
    manager._watchdog_tick(now=100)
    assert manager._worker_states["yolo_phone"].next_restart_at == 101
    manager._watchdog_tick(now=101)
    assert manager._worker_states["yolo_phone"].restart_attempts == 1


def test_concurrent_save_is_rejected_before_second_write(fixed_runtime, tmp_path, monkeypatch):
    import threading
    from AiVision.inference.model_paths import load_model_paths

    manager, _, _, _ = fixed_runtime
    entered, release = threading.Event(), threading.Event()

    def held_reload(name):
        entered.set()
        release.wait(timeout=2)

    monkeypatch.setattr(manager, "_reload_affected", held_reload)
    first = tmp_path / "first.pt"
    second = tmp_path / "second.pt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    try:
        assert manager.update_model_path("yolo_phone", str(first))["configuration_saved"]
        assert entered.wait(timeout=1)
        with pytest.raises(RuntimeError, match="正在重载"):
            manager.update_model_path("yolo_phone", str(second))
        assert load_model_paths()["yolo_phone"] == str(first)
    finally:
        release.set()
        manager._reload_thread.join(timeout=2)


def test_save_while_service_stopped_does_not_start_or_claim_loaded(fixed_runtime, tmp_path):
    manager, _, _, _ = fixed_runtime
    manager.stop_all()
    weight = tmp_path / "later.pt"
    weight.write_bytes(b"later")
    result = manager.update_model_path("yolo_phone", str(weight))
    assert result["configuration_saved"]
    assert result["load_status"] == "not_started"
    assert manager._reload_thread is None
    assert manager.list_running() == []
    manager.start_all()
    assert manager._workers["yolo_phone"].model_path == str(weight)


def test_startup_rejects_unregistered_feature_model(fixed_runtime, monkeypatch):
    from types import SimpleNamespace

    manager, _, _, _ = fixed_runtime
    manager.stop_all()
    monkeypatch.setattr(manager_module, "all_specs", lambda: {
        "test": SimpleNamespace(required_models=("custom",), model_names=("custom",))
    })
    with pytest.raises(ValueError, match="未注册模型"):
        manager.start_all()
    assert not manager._active
    assert manager._workers == {}


def test_startup_and_watchdog_ignore_models_unused_by_registered_features(fixed_runtime, monkeypatch):
    manager, _, _, _ = fixed_runtime
    manager.stop_all()
    alerts = []
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *args: alerts.append(args))
    manager.start_all()
    unused = {"yolo_guard_person_phone", "guard_uniform", "yolo_guard_pose", "yolo_vehicle"}
    assert manager._required_model_names() == {
        "yolo_human", "yolo_phone", "insightface_detection", "insightface",
    }
    assert unused <= manager.infer_queues.keys()
    assert not unused.intersection(manager._model_owners)
    assert not unused.intersection(manager._model_configs)
    assert not unused.intersection(manager._worker_states)
    assert not unused.intersection(worker.model_name for worker in ManagedWorker.instances)
    manager._watchdog_tick(now=100)
    manager._watchdog_tick(now=200)
    assert not unused.intersection(alert[0] for alert in alerts)
    for item in manager.list_models():
        if item["name"] in unused:
            assert item["runtime"]["status"] == "not_started"
            assert not item["runtime"]["alive"] and not item["runtime"]["running"]


@pytest.mark.parametrize("name", [
    "yolo_guard_person_phone", "guard_uniform", "yolo_guard_pose", "yolo_vehicle",
])
def test_unused_model_save_never_reloads_or_disturbs_running_shared_worker(fixed_runtime, monkeypatch, name):
    from AiVision.inference.model_paths import load_model_paths

    manager, _, shared, _ = fixed_runtime
    workers = dict(manager._workers)
    instances = list(ManagedWorker.instances)
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *_: pytest.fail("unused model alerted"))
    result = manager.update_model_path(name, str(shared))
    assert result["load_status"] == "not_started"
    assert load_model_paths()[name] == str(shared)
    assert manager._reload_thread is None
    assert manager._workers == workers
    assert ManagedWorker.instances == instances
    assert name not in manager._model_owners
    assert all(worker.stop_calls == 0 for worker in workers.values())


def test_required_set_is_generic_and_empty_features_start_no_models(fixed_runtime, monkeypatch):
    manager, _, shared, _ = fixed_runtime
    manager.stop_all()
    monkeypatch.setattr(manager_module, "all_specs", lambda: {})
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *_: pytest.fail("unused model alerted"))
    manager.start_all()
    assert manager._model_configs == {}
    assert manager._workers == {}
    assert manager.update_model_path("yolo_human", str(shared))["load_status"] == "not_started"
    assert manager._reload_thread is None


def test_three_required_yolo_models_share_one_physical_worker(fixed_runtime, monkeypatch, tmp_path):
    import os
    from types import SimpleNamespace
    from AiVision.inference.model_registry import MODEL_SPECS

    manager, _, shared, _ = fixed_runtime
    alias = tmp_path / "person_phone.pt"
    os.link(shared, alias)
    manager.update_model_path("yolo_guard_person_phone", str(alias))
    manager.stop_all()
    names = ("yolo_human", "yolo_phone", "yolo_guard_person_phone")
    monkeypatch.setattr(manager_module, "all_specs", lambda: {
        "synthetic": SimpleNamespace(required_models=names, model_names=names),
    })
    # 正式 WorkerClass 与 inode 决定共享；与逻辑模型标签及文件名无关。
    with monkeypatch.context() as context:
        context.setattr(manager_module, "MODEL_SPECS", MODEL_SPECS)
        groups, owners = manager._build_model_groups()
        assert len(groups) == 1
        assert groups["yolo_human"]["worker_class"] is MODEL_SPECS["yolo_human"].worker_class
        assert groups["yolo_human"]["model_names"] == list(names)
        assert set(owners.values()) == {"yolo_human"}
    ManagedWorker.instances = []
    manager.start_all()
    assert len(ManagedWorker.instances) == 1
    assert set(manager._workers["yolo_human"].infer_queues) == set(names)
    assert set(manager.list_running()) == set(names)


def test_reload_timeout_stops_worker_and_reports_failed(fixed_runtime, monkeypatch):
    manager, _, shared, _ = fixed_runtime

    def start_loading(self):
        self.alive = True
        self.running = False
        self.failed = False

    monkeypatch.setattr(ManagedWorker, "start", start_loading)
    monkeypatch.setattr(manager_module.settings.runtime, "model_worker_ready_timeout_seconds", 0.01)
    manager.update_model_path("yolo_phone", str(shared))
    manager._reload_thread.join(timeout=2)
    assert manager._reload_results["yolo_phone"] == {"status": "failed", "error": "模型加载超时"}
    assert not manager._workers["yolo_human"].is_alive()


@pytest.mark.parametrize("configured", [False, True])
def test_optional_models_start_only_with_valid_path_and_can_reload(fixed_runtime, monkeypatch, tmp_path, configured):
    from dataclasses import replace
    from AiVision.features.registry import all_specs
    from AiVision.inference.model_paths import save_model_path

    manager, _, shared, _ = fixed_runtime
    manager.stop_all()
    optional = tmp_path / "optional.pt"
    optional.write_bytes(b"optional weights")
    if configured:
        save_model_path("yolo_vehicle", str(optional))
    spec = replace(all_specs()["blocks"], required_models=("yolo_human",), optional_models=("yolo_vehicle",))
    monkeypatch.setattr(manager_module, "all_specs", lambda: {"synthetic": spec})
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *_: pytest.fail("optional missing path alerted"))
    manager.start_all()
    assert manager._required_model_names() == {"yolo_human"}
    assert manager._declared_model_names() == {"yolo_human", "yolo_vehicle"}
    assert manager.is_model_running("yolo_human")
    assert manager.is_model_running("yolo_vehicle") is configured
    if not configured:
        assert "yolo_vehicle" not in manager._worker_states
        assert next(m for m in manager.list_models() if m["name"] == "yolo_vehicle")["runtime"]["status"] == "not_started"
    core = manager._workers["yolo_human"]
    assert manager.update_model_path("yolo_vehicle", str(optional))["load_status"] == "loading"
    manager._reload_thread.join(timeout=2)
    assert not manager._reload_thread.is_alive()
    assert manager.is_model_running("yolo_vehicle")
    assert manager._workers["yolo_human"] is core and core.stop_calls == 0
    # 可选模型仍参与物理文件共享。
    manager.update_model_path("yolo_vehicle", str(shared))
    manager._reload_thread.join(timeout=2)
    assert manager._model_owners["yolo_vehicle"] == manager._model_owners["yolo_human"]


def test_unregistered_optional_model_is_rejected(fixed_runtime, monkeypatch):
    from dataclasses import replace
    from AiVision.features.registry import all_specs

    manager, *_ = fixed_runtime
    manager.stop_all()
    spec = replace(all_specs()["blocks"], optional_models=("unknown",))
    monkeypatch.setattr(manager_module, "all_specs", lambda: {"synthetic": spec})
    with pytest.raises(ValueError, match="未注册模型"):
        manager.start_all()
    assert not manager._active


def test_feature_model_names_deduplicate_required_and_optional():
    from dataclasses import replace
    from AiVision.features.registry import all_specs

    assert all(spec.optional_models == () for spec in all_specs().values())
    spec = replace(all_specs()["blocks"], required_models=("core",), optional_models=("optional", "core"))
    assert spec.model_names == ("core", "optional")


def test_optional_invalid_path_is_not_started_without_retry(fixed_runtime, monkeypatch):
    from dataclasses import replace
    from AiVision.features.registry import all_specs

    manager, *_ = fixed_runtime
    manager.stop_all()
    spec = replace(all_specs()["blocks"], required_models=("yolo_human",), optional_models=("yolo_vehicle",))
    paths = manager_module.load_model_paths()
    paths["yolo_vehicle"] = "/missing/optional-model.pt"
    monkeypatch.setattr(manager_module, "all_specs", lambda: {"synthetic": spec})
    monkeypatch.setattr(manager_module, "load_model_paths", lambda: paths)
    monkeypatch.setattr(manager, "_notify_runtime_alert", lambda *_: pytest.fail("unconfigured optional alerted"))
    manager.start_all()
    assert manager.is_model_running("yolo_human")
    assert not manager.is_model_running("yolo_vehicle")
    assert "yolo_vehicle" not in manager._worker_states
    manager._watchdog_tick(now=1000.)


def test_optional_model_load_failure_does_not_stop_core(fixed_runtime, monkeypatch, tmp_path):
    from dataclasses import replace
    from AiVision.features.registry import all_specs
    from AiVision.inference.model_paths import save_model_path

    manager, *_ = fixed_runtime
    manager.stop_all()
    path = tmp_path / "optional.pt"
    path.write_bytes(b"optional")
    save_model_path("yolo_vehicle", str(path))
    spec = replace(all_specs()["blocks"], required_models=("yolo_human",), optional_models=("yolo_vehicle",))
    monkeypatch.setattr(manager_module, "all_specs", lambda: {"synthetic": spec})
    start = ManagedWorker.start

    def failed_optional(worker):
        if worker.model_name == "yolo_vehicle":
            worker.alive, worker.running, worker.failed = False, False, True
        else:
            start(worker)

    monkeypatch.setattr(ManagedWorker, "start", failed_optional)
    manager.start_all()
    assert manager.is_model_running("yolo_human")
    assert not manager.is_model_running("yolo_vehicle")
    assert manager._worker_states["yolo_vehicle"].last_failure
