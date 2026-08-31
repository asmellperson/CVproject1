# 文件说明：包含后台任务的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import vlm_worker


# 功能：验证 `test_pending_task_lock_entries_release_after_all_waiters_exit` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`vlm_worker.PendingTaskProcessor`、`threading.Event`、`threading.Thread`、`first_thread.start`、`second_thread.start`、`first_entered.wait`、`second_entered.wait`、`len`、`release_first.set`、`first_thread.join`
#          等共 14 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_pending_task_lock_entries_release_after_all_waiters_exit():
    processor = vlm_worker.PendingTaskProcessor(
        stores=None,
        accumulators=None,
        judge=None,
        queue_timeout=1,
    )
    key = ("general_electric", "camera-a", "session-a")
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    # 功能：实现 `first` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/violation/service.py` 的 `AsyncViolationWriter::update_video_status`
    #         调用本符号；`AiVision/platform/camera/service.py` 的 `CameraService::create_camera_record`
    #         调用本符号；`AiVision/platform/camera/service.py` 的 `CameraService::ensure_feature_configs`
    #         调用本符号；`AiVision/platform/camera/service.py` 的 `CameraService::_get_orm_by_key` 调用本符号；另有 12 处静态调用
    #   - 内部调用：`processor._hold_task_lock`、`first_entered.set`、`release_first.wait`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def first():
        with processor._hold_task_lock(key):
            first_entered.set()
            assert release_first.wait(timeout=2)

    # 功能：实现 `second` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`first_entered.wait`、`processor._hold_task_lock`、`second_entered.set`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def second():
        assert first_entered.wait(timeout=2)
        with processor._hold_task_lock(key):
            second_entered.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()
    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.05)
    assert len(processor._task_locks) == 1

    release_first.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert second_entered.is_set()
    assert processor._task_locks == {}


# 功能：验证 `test_department_fair_queue_concurrent_semantics_and_counts` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`vlm_worker.DepartmentFairTaskQueue`、`vlm_worker.PendingTask`、`range`、`threading.Thread`、`consumer_thread.start`、`producer_thread.start`、`producer_thread.join`、`consumer_thread.join`、`producer_thread.is_alive`、`consumer_thread.is_alive`
#          等共 16 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_department_fair_queue_concurrent_semantics_and_counts(tmp_path):
    task_q = vlm_worker.DepartmentFairTaskQueue()
    tasks = [
        vlm_worker.PendingTask(
            (
                "general_electric"
                if index % 2 == 0
                else "electronics_electrician"
            ),
            f"camera-{index % 3}",
            tmp_path / f"{index}.pkl",
        )
        for index in range(30)
    ]
    consumed = []

    # 功能：实现 `producer` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`task_q.put`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def producer():
        for task in tasks:
            task_q.put(task)

    # 功能：实现 `consumer` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：无。
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`range`、`len`、`consumed.append`、`task_q.get`、`task_q.task_done`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def consumer():
        for _index in range(len(tasks)):
            consumed.append(task_q.get(timeout=2))
            task_q.task_done()

    producer_thread = threading.Thread(target=producer)
    consumer_thread = threading.Thread(target=consumer)
    consumer_thread.start()
    producer_thread.start()
    producer_thread.join(timeout=2)
    consumer_thread.join(timeout=2)

    assert not producer_thread.is_alive()
    assert not consumer_thread.is_alive()
    assert {task.path for task in consumed} == {task.path for task in tasks}
    assert task_q.unfinished_tasks == 0
    assert task_q.qsize() == 0
    assert task_q.empty() is True
    assert vlm_worker.queued_department_counts(task_q) == {
        department: 0 for department in vlm_worker.SECURITY_DEPARTMENTS
    }
    with pytest.raises(queue.Empty):
        task_q.get(timeout=0.01)
    with pytest.raises(ValueError, match="task_done"):
        task_q.task_done()


# 功能：验证 `test_process_queued_item_contains_task_exception` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `capsys`（未显式标注）：`capsys` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`queue.Queue`、`Path`、`task_q.put`、`vlm_worker.process_queued_item`、`capsys.readouterr`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_process_queued_item_contains_task_exception(capsys):
    task_q = queue.Queue()
    first = Path("first.pkl")
    second = Path("second.pkl")
    task_q.put(first)
    task_q.put(second)
    processed = []

    # 功能：处理 `process_one` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `path`（未显式标注）：目标路径
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`processed.append`、`RuntimeError`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；校验或执行失败时会主动抛出异常。
    def process_one(path):
        processed.append(path)
        if path == first:
            raise RuntimeError("broken task")

    vlm_worker.process_queued_item(task_q, process_one)
    vlm_worker.process_queued_item(task_q, process_one)

    assert processed == [first, second]
    assert task_q.unfinished_tasks == 0
    assert "broken task" in capsys.readouterr().err


# 功能：验证 `test_shutdown_drains_task_put_after_global_stop_during_scanner_scan` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`vlm_worker.DepartmentFairTaskQueue`、`vlm_worker.PendingTask`、`threading.Event`、`DelayedScanner`、`threading.Thread`、`range`、`worker.start`、`scanner.start`、`scan_started.wait`、`vlm_worker._STOP.set`
#          等共 19 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_shutdown_drains_task_put_after_global_stop_during_scanner_scan(tmp_path):
    task_q = vlm_worker.DepartmentFairTaskQueue()
    late_task = vlm_worker.PendingTask(
        "general_electric",
        "camera-late",
        tmp_path / "late.pkl",
    )
    scan_started = threading.Event()
    allow_late_put = threading.Event()
    worker_stop = threading.Event()
    processed = []
    worker_stop_states = []

    # 功能：定义 `DelayedScanner` 类，封装后台任务相关的状态、约束与操作
    # 参数：无。
    # 返回：DelayedScanner；返回新建的 `DelayedScanner` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_shutdown_drains_task_put_after_global_stop_during_scanner_scan` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class DelayedScanner(threading.Thread):
        # 功能：启动或执行 `run` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`scan_started.set`、`allow_late_put.wait`、`task_q.put`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def run(self):
            scan_started.set()
            assert allow_late_put.wait(timeout=2)
            task_q.put(late_task)

        # 功能：停止并释放 `stop` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`allow_late_put.set`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def stop(self):
            allow_late_put.set()

    # 功能：处理 `process_one` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `task`（未显式标注）：`task` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`worker_stop_states.append`、`worker_stop.is_set`、`processed.append`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def process_one(task):
        worker_stop_states.append(worker_stop.is_set())
        processed.append(task)

    scanner = DelayedScanner()
    workers = [
        threading.Thread(
            target=vlm_worker.run_task_worker,
            args=(task_q, process_one, worker_stop),
            kwargs={"poll_sec": 0.01},
        )
        for _index in range(2)
    ]
    for worker in workers:
        worker.start()
    scanner.start()
    assert scan_started.wait(timeout=2)

    try:
        vlm_worker._STOP.set()
        drained = vlm_worker.shutdown_task_workers(
            scanner,
            task_q,
            worker_stop,
            workers,
            drain_timeout_sec=2,
            poll_sec=0.01,
        )
    finally:
        vlm_worker._STOP.clear()
        allow_late_put.set()
        scanner.join(timeout=2)
        worker_stop.set()
        for worker in workers:
            worker.join(timeout=2)

    assert drained is True
    assert processed == [late_task]
    assert worker_stop_states == [False]
    assert task_q.unfinished_tasks == 0
    assert task_q.empty() is True
    assert all(not worker.is_alive() for worker in workers)


# 功能：验证 `test_shutdown_timeout_leaves_in_progress_task_for_recovery` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`task_path.parent.mkdir`、`task_path.write_bytes`、`vlm_worker.PendingTask`、`vlm_worker.DepartmentFairTaskQueue`、`task_q.put`、`threading.Event`、`IdleScanner`、`threading.Thread`、`scanner.start`、`worker.start`
#          等共 19 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
def test_shutdown_timeout_leaves_in_progress_task_for_recovery(tmp_path):
    task_path = tmp_path / "global" / "processing" / "camera-a" / "slow.pkl"
    task_path.parent.mkdir(parents=True)
    task_path.write_bytes(b"recoverable")
    task = vlm_worker.PendingTask(
        "general_electric",
        "camera-a",
        task_path,
    )
    task_q = vlm_worker.DepartmentFairTaskQueue()
    task_q.put(task)
    process_started = threading.Event()
    release_process = threading.Event()
    scanner_stopped = threading.Event()
    worker_stop = threading.Event()

    # 功能：定义 `IdleScanner` 类，封装后台任务相关的状态、约束与操作
    # 参数：无。
    # 返回：IdleScanner；返回新建的 `IdleScanner` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的
    #         `test_shutdown_timeout_leaves_in_progress_task_for_recovery` 实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class IdleScanner(threading.Thread):
        # 功能：启动或执行 `run` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`scanner_stopped.wait`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def run(self):
            scanner_stopped.wait()

        # 功能：停止并释放 `stop` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`scanner_stopped.set`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def stop(self):
            scanner_stopped.set()

    # 功能：处理 `process_one` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `_task`（未显式标注）：`_task` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`process_started.set`、`release_process.wait`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def process_one(_task):
        process_started.set()
        assert release_process.wait(timeout=2)

    scanner = IdleScanner()
    worker = threading.Thread(
        target=vlm_worker.run_task_worker,
        args=(task_q, process_one, worker_stop),
        kwargs={"poll_sec": 0.01},
    )
    scanner.start()
    worker.start()
    assert process_started.wait(timeout=2)

    try:
        drained = vlm_worker.shutdown_task_workers(
            scanner,
            task_q,
            worker_stop,
            [worker],
            drain_timeout_sec=0.01,
            poll_sec=0.005,
            worker_join_timeout_sec=0.01,
        )
        assert drained is False
        assert task_path.read_bytes() == b"recoverable"
        assert task_q.unfinished_tasks == 1
    finally:
        release_process.set()
        worker_stop.set()
        worker.join(timeout=2)
        scanner_stopped.set()
        scanner.join(timeout=2)

    assert not worker.is_alive()
    assert task_q.unfinished_tasks == 0


# 功能：验证 `test_shutdown_returns_when_scanner_does_not_exit` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`threading.Event`、`StuckScanner`、`scanner.start`、`vlm_worker.shutdown_task_workers`、`vlm_worker.DepartmentFairTaskQueue`、`scanner.is_alive`、`release_scanner.set`、`scanner.join`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_shutdown_returns_when_scanner_does_not_exit():
    release_scanner = threading.Event()

    # 功能：定义 `StuckScanner` 类，封装后台任务相关的状态、约束与操作
    # 参数：无。
    # 返回：StuckScanner；返回新建的 `StuckScanner` 实例。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/security_vlm/tests/test_vlm_worker.py` 的 `test_shutdown_returns_when_scanner_does_not_exit`
    #         实例化本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class StuckScanner(threading.Thread):
        # 功能：启动或执行 `run` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`release_scanner.wait`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def run(self):
            release_scanner.wait()

        # 功能：停止并释放 `stop` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `self`（未显式标注）：当前类实例
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        def stop(self):
            pass

    scanner = StuckScanner()
    scanner.start()
    try:
        result = vlm_worker.shutdown_task_workers(
            scanner,
            vlm_worker.DepartmentFairTaskQueue(),
            threading.Event(),
            [],
            drain_timeout_sec=0.01,
            scanner_join_timeout_sec=0.01,
        )
        assert result is False
        assert scanner.is_alive()
    finally:
        release_scanner.set()
        scanner.join(timeout=2)


# 功能：验证 `test_vlm_max_concurrent_must_be_positive` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `value`（未显式标注）：待转换、校验或写入的值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`pytest.raises`、`vlm_worker.vlm_max_concurrent`、`pytest.mark.parametrize`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@pytest.mark.parametrize("value", [0, -1])
def test_vlm_max_concurrent_must_be_positive(value):
    with pytest.raises(ValueError, match="正整数"):
        vlm_worker.vlm_max_concurrent({"max_concurrent": value})


# 功能：验证 `test_strict_state_reader_rejects_non_object_without_overwriting` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`vlm_worker.DepartmentResultStores`、`stores.get`、`store._path`、`state_path.write_text`、`vlm_worker.read_strict_result_object`、`state_path.read_text`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_strict_state_reader_rejects_non_object_without_overwriting(tmp_path):
    stores = vlm_worker.DepartmentResultStores(tmp_path / "data")
    store = stores.get("general_electric")
    state_path = store._path("vlm_state")
    state_path.write_text("[]", encoding="utf-8")

    assert vlm_worker.read_strict_result_object(store, "vlm_state") == {}
    assert state_path.read_text(encoding="utf-8") == "[]"


# 功能：验证 `test_corrupt_shared_budget_is_quarantined_before_reinitialization` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`vlm_worker.DepartmentResultStores`、`stores.budget_store._path`、`budget_path.write_text`、`vlm_worker.read_strict_result_object`、`budget_path.exists`、`list`、`budget_path.parent.glob`、`len`、`backups[0].read_text`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件。
def test_corrupt_shared_budget_is_quarantined_before_reinitialization(tmp_path):
    stores = vlm_worker.DepartmentResultStores(tmp_path / "data")
    budget_path = stores.budget_store._path("vlm_budget")
    budget_path.write_text("[]", encoding="utf-8")

    assert vlm_worker.read_strict_result_object(
        stores.budget_store,
        "vlm_budget",
        quarantine_corrupt=True,
    ) == {}
    assert not budget_path.exists()
    backups = list(budget_path.parent.glob("vlm_budget.corrupt.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "[]"


# 功能：验证 `test_draw_text_falls_back_when_configured_font_cannot_be_opened` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`monkeypatch.setattr`、`np.zeros`、`vlm_worker._draw_text_pil`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_draw_text_falls_back_when_configured_font_cannot_be_opened(monkeypatch):
    original_truetype = vlm_worker.ImageFont.truetype

    # 功能：实现 `unavailable_file_font` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `font`（未显式标注）：`font` 对应的业务输入值
    #   - `*args`（未显式标注）：`args` 对应的业务输入值
    #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`isinstance`、`OSError`、`original_truetype`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    def unavailable_file_font(font, *args, **kwargs):
        if isinstance(font, (str, Path)):
            raise OSError("cannot open resource")
        return original_truetype(font, *args, **kwargs)

    monkeypatch.setattr(vlm_worker.ImageFont, "truetype", unavailable_file_font)
    image = np.zeros((90, 480, 3), dtype=np.uint8)

    rendered = vlm_worker._draw_text_pil(
        image,
        "session-1 [不合规：安检流程未完成]",
        (10, 8),
    )

    assert rendered.shape == image.shape
    assert rendered.dtype == image.dtype


# 功能：验证 `test_vlm_judge_passes_request_timeout` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `tmp_path`（未显式标注）：`tmp_path` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`object.__new__`、`SimpleNamespace`、`judge.judge`、`np.zeros`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_vlm_judge_passes_request_timeout(tmp_path):
    calls = []

    # 功能：定义 `FakeMMC` 类，封装后台任务相关的状态、约束与操作
    # 参数：无。
    # 返回：FakeMMC；返回新建的 `FakeMMC` 实例。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    class FakeMMC:
        # 功能：实现 `call` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：
        #   - `cls`（未显式标注）：当前类对象
        #   - `**kwargs`（未显式标注）：`kwargs` 对应的业务输入值
        # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
        # 调用关系：
        #   - 调用方：`AiVision/integrations/security_vlm/src/vlm_worker.py` 的 `VLMJudge::judge` 调用本符号
        #   - 内部调用：`calls.append`、`SimpleNamespace`。
        # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
        @classmethod
        def call(cls, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content='{"compliant": true}')
            choice = SimpleNamespace(message=message)
            output = SimpleNamespace(choices=[choice])
            return SimpleNamespace(status_code=200, output=output, usage=None)

    judge = object.__new__(vlm_worker.VLMJudge)
    judge.MMC = FakeMMC
    judge.model = "test-model"
    judge.api_timeout = 45.0
    judge.image_max_side = 960
    judge.image_quality = 85
    judge.budget = SimpleNamespace(try_consume=lambda: True)
    judge.tmp_dir = tmp_path

    result = judge.judge(
        "session-1",
        "security_staff_1",
        [0, 0, 10, 10],
        [np.zeros((10, 10, 3), dtype=np.uint8)],
        department="electrical_components",
    )

    assert result["compliant"] is True
    assert calls[0]["request_timeout"] == 45.0
    assert "timeout" not in calls[0]
    image_uri = calls[0]["messages"][1]["content"][0]["image"]
    assert "/electrical_components/" in image_uri


# 功能：验证 `test_budget_guard_restores_same_day_and_persists_each_consumption` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`vlm_worker.datetime.now().strftime`、`vlm_worker.datetime.now`、`vlm_worker.BudgetGuard`、`budget.try_consume`、`budget.snapshot`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_budget_guard_restores_same_day_and_persists_each_consumption():
    today = vlm_worker.datetime.now().strftime("%Y-%m-%d")
    persisted = []
    budget = vlm_worker.BudgetGuard(
        daily_limit=10,
        est_cost_per_call=0.5,
        initial_state={
            "date": today,
            "call_count": 3,
            "spent_yuan": 1.5,
        },
        on_change=persisted.append,
    )

    assert budget.try_consume() is True
    assert budget.snapshot()["call_count"] == 4
    assert budget.snapshot()["spent_yuan"] == 2.0
    assert persisted[-1]["call_count"] == 4


# 功能：验证 `test_budget_persistence_snapshots_never_move_backwards_under_concurrency` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`vlm_worker.BudgetGuard`、`persisted.append`、`ThreadPoolExecutor`、`list`、`executor.map`、`budget.try_consume`、`range`、`all`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_budget_persistence_snapshots_never_move_backwards_under_concurrency():
    persisted = []
    budget = vlm_worker.BudgetGuard(
        daily_limit=100,
        est_cost_per_call=0.5,
        on_change=lambda snapshot: persisted.append(snapshot["call_count"]),
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: budget.try_consume(), range(20)))

    assert all(results)
    assert persisted == list(range(1, 21))
