# 文件说明：实现`manager` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/inference/manager.py
推理 Worker 进程生命周期管理 — 替代旧 CapManager.start_inferworker。

启动时按数据库 ai_model 表逐个尝试加载模型元数据，模型文件路径来自本机配置文件。
导入失败 / 模型缺失 / 本机路径未配置时会跳过,
不影响其他模型。Consumer 那边通过 _dispatch_frame 找不到对应模型时也会优雅降级。
"""
from __future__ import annotations
import importlib
import queue
import threading
import time
from dataclasses import dataclass
from multiprocessing import Queue
from typing import Callable

from core.logger import logger
from core.cache import config_cache
from core.settings import settings
from features import all_specs
from .service import model_service


# 功能：定义 `WorkerWatchdogState` 类，封装`manager` 模块相关的状态、约束与操作
# 参数：
#   - `restart_attempts`（int）：`restart_attempts` 对应的业务输入值
#   - `next_restart_at`（float）：`next_restart_at` 对应的业务输入值
#   - `ready_deadline`（float）：`ready_deadline` 对应的业务输入值
#   - `running_since`（float | None）：`running_since` 对应的业务输入值
#   - `last_restart_at`（float | None）：`last_restart_at` 对应的业务输入值
#   - `last_failure_at`（float | None）：`last_failure_at` 对应的业务输入值
#   - `last_failure`（str）：`last_failure` 对应的业务输入值
#   - `exhausted`（bool）：`exhausted` 对应的业务输入值
#   - `exhausted_alerted`（bool）：`exhausted_alerted` 对应的业务输入值
# 返回：WorkerWatchdogState；返回新建的 `WorkerWatchdogState` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::start_all` 实例化本符号；`AiVision/platform/inference/manager.py` 的
#         `InferenceManager::_watchdog_tick` 实例化本符号；`AiVision/platform/inference/manager.py` 的 `InferenceManager::_restart_worker`
#         实例化本符号；`AiVision/platform/inference/manager.py` 的 `InferenceManager::runtime_status` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class WorkerWatchdogState:
    restart_attempts: int = 0
    next_restart_at: float = 0.0
    ready_deadline: float = 0.0
    running_since: float | None = None
    last_restart_at: float | None = None
    last_failure_at: float | None = None
    last_failure: str = ""
    exhausted: bool = False
    exhausted_alerted: bool = False


# 功能：所有推理 Worker 进程的管理器；输入与输出详见下方说明
# 参数：无。
# 返回：InferenceManager；返回新建的 `InferenceManager` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_inference_manager_watchdog.py` 的 `_manager_with_worker` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class InferenceManager:
    """所有推理 Worker 进程的管理器"""

    # 功能：初始化或配置 `__init__` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`threading.RLock`、`threading.Event`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(self):
        # model_name → infer_queue (Consumer 投递任务给 Worker)
        self.infer_queues: dict[str, Queue] = {}
        # function_name → result_queue (Worker 把结果推给对应 Consumer)
        self.result_queues: dict[str, Queue] = {}
        # model_name → BaseModelWorker 实例
        self._workers: dict[str, object] = {}
        self._model_configs: dict[str, dict] = {}
        self._worker_states: dict[str, WorkerWatchdogState] = {}
        self._runtime_alert_handler: Callable[[str, str, str, str], None] | None = None
        self._lock = threading.RLock()
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self._shutting_down = False

    # 功能：启动前预创建所有队列；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`model_service.list_models`、`Queue`、`all_specs`、`logger.info`、`len`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def initialize_queues(self):
        """启动前预创建所有队列"""
        # 一个 model 一个推理输入队列
        for m in model_service.list_models(enabled_only=True):
            self.infer_queues[m["name"]] = Queue(maxsize=10)
        # 一个 feature 一个结果队列
        for fname in all_specs():
            self.result_queues[fname] = Queue(maxsize=10)

        logger.info(
            f"[InferenceManager] 初始化 {len(self.infer_queues)} 个推理队列, "
            f"{len(self.result_queues)} 个结果队列"
        )

    # 功能：加载并启动所有已启用的推理 Worker；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`model_service.list_models`、`dict`、`WorkerWatchdogState`、`self._start_one`、`len`、`self._wait_for_workers_ready`、`time.monotonic`、`self._workers.items`、`worker.is_running`、`self._worker_states.setdefault`
    #          等共 13 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
    def start_all(self):
        """加载并启动所有已启用的推理 Worker"""
        models = model_service.list_models(enabled_only=True)
        with self._lock:
            self._shutting_down = False
            self._model_configs = {model["name"]: dict(model) for model in models}
            self._worker_states = {
                model["name"]: WorkerWatchdogState()
                for model in models
            }
        for model in models:
            self._start_one(model)
        total_workers = len(self._workers)
        self._wait_for_workers_ready()
        now = time.monotonic()
        with self._lock:
            for name, worker in self._workers.items():
                if worker.is_running():
                    self._worker_states.setdefault(name, WorkerWatchdogState()).running_since = now
        self._start_watchdog()
        logger.info(
            f"[InferenceManager] 模型就绪 {len(self.list_running())}/{total_workers}: "
            f"{self.list_running()}"
        )

    # 功能：停止并释放 `stop_all` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_watchdog`、`list`、`self._workers.items`、`self._workers.clear`、`self._model_configs.clear`、`self._worker_states.clear`、`worker.stop`、`logger.warning`。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
    def stop_all(self):
        with self._lock:
            self._shutting_down = True
        self._stop_watchdog()
        with self._lock:
            workers = list(self._workers.items())
            self._workers.clear()
            self._model_configs.clear()
            self._worker_states.clear()
        for name, worker in workers:
            try:
                worker.stop()
            except Exception as e:
                logger.warning(f"[InferenceManager] 停止 {name} 失败: {e}")

    # 功能：初始化或配置 `configure_runtime_alerts` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `handler`（Callable[[str, str, str, str], None] | None）：负责处理事件或结果的回调函数
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def configure_runtime_alerts(self, handler: Callable[[str, str, str, str], None] | None):
        self._runtime_alert_handler = handler

    # 功能：启动或执行 `_start_one` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model_cfg`（dict）：`model_cfg` 对应的业务输入值
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::start_all`
    #         调用本符号；`AiVision/platform/inference/manager.py` 的 `InferenceManager::_restart_worker` 调用本符号
    #   - 内部调用：`model_cfg.get`、`logger.info`、`self._collect_initial_configs`、`self._import_worker_class`、`logger.warning`、`self._notify_runtime_alert`、`str`、`self.infer_queues.get`、`worker_cls`、`worker.start`
    #          等共 11 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _start_one(self, model_cfg: dict) -> bool:
        name = model_cfg["name"]
        import_path = model_cfg.get("import_path")
        if not import_path:
            logger.info(f"[InferenceManager] 模型 {name} 未配置 import_path,跳过")
            return False

        # 收集本模型对应的初始 camera 配置(供 Worker 用)
        initial_configs = self._collect_initial_configs(name)

        try:
            worker_cls = self._import_worker_class(import_path)
        except Exception as e:
            logger.warning(f"[InferenceManager] 模型 {name} 导入失败 ({import_path}): {e}")
            self._notify_runtime_alert(name, name, "模型导入失败", str(e))
            return False

        infer_queue = self.infer_queues.get(name)
        if infer_queue is None:
            logger.warning(f"[InferenceManager] 模型 {name} 缺少 infer_queue")
            self._notify_runtime_alert(name, name, "模型队列缺失", "缺少 infer_queue")
            return False

        try:
            worker = worker_cls(
                infer_queue=infer_queue,
                result_queues=self.result_queues,
                model_cfg=model_cfg,
                initial_configs=initial_configs,
            )
            worker.start()
            with self._lock:
                self._workers[name] = worker
            logger.info(f"[InferenceManager] 推理 Worker 启动: {name}")
            return True
        except Exception as e:
            logger.exception(f"[InferenceManager] 启动 Worker {name} 失败: {e}")
            self._notify_runtime_alert(name, name, "模型 Worker 启动失败", str(e))
            return False

    # 功能：收集所有依赖该模型的 (camera_id, function) 配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model_name`（str）：`model_name` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_start_one` 调用本符号
    #   - 内部调用：`config_cache.get_all_function_configs`、`all_specs`、`all_cfg.items`、`specs.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _collect_initial_configs(self, model_name: str) -> dict:
        """收集所有依赖该模型的 (camera_id, function) 配置"""
        result = {}
        all_cfg = config_cache.get_all_function_configs()
        specs = all_specs()
        for (cam_id, fname), cfg in all_cfg.items():
            spec = specs.get(fname)
            if spec is None:
                continue
            if model_name in spec.required_models:
                result[cam_id] = cfg
        return result

    # 功能：等待子进程完成模型加载,避免状态接口把加载失败的模型误判为在线；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::start_all` 调用本符号
    #   - 内部调用：`time.monotonic`、`max`、`set`、`self._workers.keys`、`list`、`self._workers.get`、`pending.discard`、`worker.is_running`、`worker.is_failed`、`worker.is_alive`
    #          等共 16 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
    def _wait_for_workers_ready(self):
        """等待子进程完成模型加载,避免状态接口把加载失败的模型误判为在线。"""
        timeout = settings.runtime.model_worker_ready_timeout_seconds

        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            pending = set(self._workers.keys())

        while pending and time.monotonic() < deadline:
            for name in list(pending):
                with self._lock:
                    worker = self._workers.get(name)
                if worker is None:
                    pending.discard(name)
                    continue
                if worker.is_running():
                    pending.discard(name)
                    continue
                if worker.is_failed() or not worker.is_alive():
                    logger.warning(f"[InferenceManager] 模型 {name} 未就绪,worker 已失败或退出")
                    self._notify_runtime_alert(name, name, "模型 Worker 未就绪", "worker 已失败或退出")
                    pending.discard(name)
                    continue
            if pending:
                time.sleep(0.2)

        for name in sorted(pending):
            logger.warning(
                f"[InferenceManager] 模型 {name} 在 {timeout:.1f}s 内未完成加载,暂不计入运行模型"
            )
            self._notify_runtime_alert(name, name, "模型 Worker 加载超时", f"{timeout:.1f}s 内未完成加载")
            with self._lock:
                worker = self._workers.get(name)
            if worker is not None:
                try:
                    worker.stop()
                except Exception as e:
                    logger.warning(f"[InferenceManager] 停止未就绪模型 {name} 失败: {e}")

        with self._lock:
            self._workers = {
                name: worker
                for name, worker in self._workers.items()
                if worker.is_running()
            }

    # ---------- Worker 看门狗 ----------

    # 功能：启动或执行 `_start_watchdog` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::start_all` 调用本符号
    #   - 内部调用：`self._watchdog_thread.is_alive`、`self._watchdog_stop.clear`、`threading.Thread`、`self._watchdog_thread.start`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _start_watchdog(self) -> None:
        with self._lock:
            if not self._model_configs:
                return
            if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
                return
            self._watchdog_stop.clear()
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                daemon=True,
                name="inference-worker-watchdog",
            )
            self._watchdog_thread.start()
        logger.info("[InferenceManager] 模型 Worker 看门狗已启动")

    # 功能：停止并释放 `_stop_watchdog` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::stop_all` 调用本符号
    #   - 内部调用：`self._watchdog_stop.set`、`threading.current_thread`、`thread.join`、`max`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def _stop_watchdog(self) -> None:
        self._watchdog_stop.set()
        with self._lock:
            thread = self._watchdog_thread
            self._watchdog_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, settings.runtime.model_worker_watchdog_interval_seconds * 2))

    # 功能：实现 `_watchdog_loop` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._watchdog_stop.wait`、`self._watchdog_tick`、`logger.exception`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _watchdog_loop(self) -> None:
        interval = settings.runtime.model_worker_watchdog_interval_seconds
        while not self._watchdog_stop.wait(interval):
            try:
                self._watchdog_tick()
            except Exception:
                logger.exception("[InferenceManager] 模型 Worker 看门狗异常")

    # 功能：执行一次存活检查；独立成方法便于确定性测试；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `now`（float | None）：`now` 对应的业务输入值；默认值为 `None`
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_watchdog_loop`
    #         调用本符号；`AiVision/tests/test_inference_manager_watchdog.py` 的 `test_watchdog_restarts_dead_worker_after_backoff`
    #         调用本符号；`AiVision/tests/test_inference_manager_watchdog.py` 的
    #         `test_watchdog_stops_retrying_and_alerts_once_when_attempts_exhausted` 调用本符号
    #   - 内部调用：`time.monotonic`、`list`、`self._workers.get`、`self._worker_states.setdefault`、`WorkerWatchdogState`、`dict`、`worker.is_running`、`self._mark_worker_running`、`worker.is_alive`、`worker.is_failed`
    #          等共 17 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _watchdog_tick(self, now: float | None = None) -> None:
        """执行一次存活检查；独立成方法便于确定性测试。"""
        current = time.monotonic() if now is None else now
        with self._lock:
            if self._shutting_down:
                return
            model_names = list(self._model_configs)

        for name in model_names:
            with self._lock:
                worker = self._workers.get(name)
                state = self._worker_states.setdefault(name, WorkerWatchdogState())
                model_cfg = dict(self._model_configs[name])

            if worker is not None and worker.is_running():
                self._mark_worker_running(state, current)
                continue

            if (
                worker is not None
                and worker.is_alive()
                and not worker.is_failed()
                and state.ready_deadline > current
            ):
                continue

            reason = self._worker_failure_reason(worker, state, current)
            should_restart = False
            notify_exit = False
            notify_exhausted = False
            delay = 0.0
            attempt = 0

            with self._lock:
                state = self._worker_states.setdefault(name, WorkerWatchdogState())
                state.running_since = None
                state.ready_deadline = 0.0
                state.last_failure = reason
                state.last_failure_at = time.time()

                max_attempts = settings.runtime.model_worker_restart_max_attempts
                if state.next_restart_at <= 0:
                    if state.restart_attempts >= max_attempts:
                        state.exhausted = True
                        if not state.exhausted_alerted:
                            state.exhausted_alerted = True
                            notify_exhausted = True
                    else:
                        delay = self._restart_backoff_seconds(state.restart_attempts)
                        state.next_restart_at = current + delay
                        state.exhausted = False
                        state.exhausted_alerted = False
                        notify_exit = True
                elif current >= state.next_restart_at:
                    state.next_restart_at = 0.0
                    state.restart_attempts += 1
                    attempt = state.restart_attempts
                    state.last_restart_at = time.time()
                    should_restart = True

            if notify_exit:
                logger.warning(
                    f"[InferenceManager] 模型 {name} Worker 异常: {reason}; "
                    f"{delay:.1f}s 后尝试重启"
                )
                self._notify_runtime_alert(
                    name,
                    name,
                    "模型 Worker 退出",
                    f"{reason}; {delay:.1f}s 后尝试自动重启",
                )
            if notify_exhausted:
                logger.error(
                    f"[InferenceManager] 模型 {name} Worker 已耗尽 "
                    f"{settings.runtime.model_worker_restart_max_attempts} 次重启机会"
                )
                self._notify_runtime_alert(
                    name,
                    name,
                    "模型 Worker 重启耗尽",
                    f"最后错误: {reason}",
                )
            if should_restart:
                self._restart_worker(name, model_cfg, attempt, current)

    # 功能：实现 `_mark_worker_running` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `state`（WorkerWatchdogState）：`state` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_watchdog_tick` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _mark_worker_running(self, state: WorkerWatchdogState, now: float) -> None:
        with self._lock:
            if state.running_since is None:
                state.running_since = now
            state.next_restart_at = 0.0
            state.ready_deadline = 0.0
            state.last_failure = ""
            state.exhausted = False
            state.exhausted_alerted = False
            reset_seconds = settings.runtime.model_worker_restart_reset_seconds
            if state.restart_attempts and now - state.running_since >= reset_seconds:
                state.restart_attempts = 0

    # 功能：实现 `_worker_failure_reason` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `worker`（object | None）：`worker` 对应的业务输入值
    #   - `state`（WorkerWatchdogState）：`state` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_watchdog_tick` 调用本符号
    #   - 内部调用：`worker.is_failed`、`worker.is_alive`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _worker_failure_reason(
        worker: object | None,
        state: WorkerWatchdogState,
        now: float,
    ) -> str:
        if worker is None:
            return "worker 不存在"
        if worker.is_failed():
            return "worker 报告失败"
        if not worker.is_alive():
            return "worker 进程已退出"
        if state.ready_deadline and now >= state.ready_deadline:
            return "worker 加载超时"
        return "worker 未就绪"

    # 功能：实现 `_restart_backoff_seconds` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `previous_attempts`（int）：`previous_attempts` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_watchdog_tick` 调用本符号
    #   - 内部调用：`min`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _restart_backoff_seconds(previous_attempts: int) -> float:
        base = settings.runtime.model_worker_restart_backoff_seconds
        maximum = settings.runtime.model_worker_restart_max_backoff_seconds
        return min(base * (2 ** previous_attempts), maximum)

    # 功能：实现 `_restart_worker` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `name`（str）：业务对象名称
    #   - `model_cfg`（dict）：`model_cfg` 对应的业务输入值
    #   - `attempt`（int）：`attempt` 对应的业务输入值
    #   - `now`（float）：`now` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_watchdog_tick` 调用本符号
    #   - 内部调用：`self._workers.pop`、`old_worker.stop`、`logger.warning`、`self._discard_pending_tasks`、`self._start_one`、`self._worker_states.setdefault`、`WorkerWatchdogState`、`time.time`、`self._notify_runtime_alert`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _restart_worker(
        self,
        name: str,
        model_cfg: dict,
        attempt: int,
        now: float,
    ) -> None:
        with self._lock:
            if self._shutting_down:
                return
            old_worker = self._workers.pop(name, None)
        if old_worker is not None:
            try:
                old_worker.stop()
            except Exception as e:
                logger.warning(f"[InferenceManager] 回收异常 Worker {name} 失败: {e}")
        discarded = self._discard_pending_tasks(name)
        if discarded:
            logger.warning(f"[InferenceManager] 重启模型 {name} 前丢弃 {discarded} 个过期任务")

        logger.warning(f"[InferenceManager] 正在第 {attempt} 次重启模型 Worker: {name}")
        started = self._start_one(model_cfg)
        with self._lock:
            state = self._worker_states.setdefault(name, WorkerWatchdogState())
            if started:
                state.ready_deadline = now + settings.runtime.model_worker_ready_timeout_seconds
                state.last_failure = ""
            else:
                state.ready_deadline = 0.0
                state.last_failure = "worker 重启启动失败"
                state.last_failure_at = time.time()

        if not started:
            self._notify_runtime_alert(
                name,
                name,
                "模型 Worker 重启失败",
                f"第 {attempt} 次重启未能启动进程",
            )

    # 功能：实现 `_discard_pending_tasks` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `name`（str）：业务对象名称
    # 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_restart_worker` 调用本符号
    #   - 内部调用：`self.infer_queues.get`、`infer_queue.get_nowait`、`logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _discard_pending_tasks(self, name: str) -> int:
        infer_queue = self.infer_queues.get(name)
        if infer_queue is None:
            return 0
        discarded = 0
        while True:
            try:
                infer_queue.get_nowait()
                discarded += 1
            except queue.Empty:
                return discarded
            except (OSError, ValueError) as exc:
                logger.warning(f"[InferenceManager] 清理模型 {name} 待处理队列失败: {exc}")
                return discarded

    # 功能：支持两种格式:；输入与输出详见下方说明
    # 参数：
    #   - `path`（str）：目标路径
    # 返回：type；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_start_one` 调用本符号
    #   - 内部调用：`ImportError`、`path.rsplit`、`importlib.import_module`、`getattr`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @staticmethod
    def _import_worker_class(path: str) -> type:
        """支持两种格式:
        - module 路径(模块内有 ModelWorker 类): 'platform.inference.workers.yolo_detector'
        - 完整类路径: 'platform.inference.workers.yolo_detector.YoloDetectorWorker'
        """
        if "." not in path:
            raise ImportError(f"无效的 import_path: {path}")
        # 尝试当作完整类路径
        try:
            mod_path, cls_name = path.rsplit(".", 1)
            module = importlib.import_module(mod_path)
            cls = getattr(module, cls_name, None)
            if cls is not None:
                return cls
        except ImportError:
            pass
        # fallback: 当作 module 路径,用 ModelWorker 名字
        module = importlib.import_module(path)
        return module.ModelWorker

    # ---------- 状态查询 ----------

    # 功能：读取或查询 `list_running` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::start_all` 调用本符号
    #   - 内部调用：`list`、`self._workers.items`、`worker.is_running`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def list_running(self) -> list[str]:
        with self._lock:
            workers = list(self._workers.items())
        return [name for name, worker in workers if worker.is_running()]

    # 功能：返回 Worker 与自动恢复状态，不改变任何运行状态；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`time.monotonic`、`sorted`、`self._workers.get`、`self._worker_states.setdefault`、`WorkerWatchdogState`、`worker.is_running`、`worker.is_alive`、`models.append`、`round`、`max`
    #          等共 11 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def runtime_status(self) -> dict:
        """返回 Worker 与自动恢复状态，不改变任何运行状态。"""
        now = time.monotonic()
        with self._lock:
            models = []
            for name in sorted(self._model_configs):
                worker = self._workers.get(name)
                state = self._worker_states.setdefault(name, WorkerWatchdogState())
                running = worker is not None and worker.is_running()
                alive = worker is not None and worker.is_alive()
                if running:
                    status = "running"
                elif state.exhausted:
                    status = "exhausted"
                elif alive and state.ready_deadline > now:
                    status = "starting"
                elif state.next_restart_at > now:
                    status = "backoff"
                else:
                    status = "stopped"
                models.append({
                    "model_name": name,
                    "status": status,
                    "running": running,
                    "alive": alive,
                    "restart_attempts": state.restart_attempts,
                    "next_restart_in_seconds": round(max(0.0, state.next_restart_at - now), 3),
                    "last_restart_at": state.last_restart_at,
                    "last_failure_at": state.last_failure_at,
                    "last_failure": state.last_failure,
                })
            thread = self._watchdog_thread
            return {
                "watchdog_running": thread is not None and thread.is_alive(),
                "models": models,
            }

    # 功能：发送或分发 `_notify_runtime_alert` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `target_name`（str）：`target_name` 对应的业务输入值
    #   - `target_key`（str）：`target_key` 对应的业务输入值
    #   - `event_type`（str）：事件类型标识
    #   - `detail`（str）：`detail` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/manager.py` 的 `InferenceManager::_start_one`
    #         调用本符号；`AiVision/platform/inference/manager.py` 的 `InferenceManager::_wait_for_workers_ready`
    #         调用本符号；`AiVision/platform/inference/manager.py` 的 `InferenceManager::_watchdog_tick`
    #         调用本符号；`AiVision/platform/inference/manager.py` 的 `InferenceManager::_restart_worker` 调用本符号
    #   - 内部调用：`threading.Thread(target=_send, daemon=True, name=f'inference-runtime-alert-{target_key}').start`、`threading.Thread`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源。
    def _notify_runtime_alert(self, target_name: str, target_key: str, event_type: str, detail: str):
        handler = self._runtime_alert_handler
        if handler is None:
            return

        # 功能：发送或分发 `_send` 对应的`manager` 模块逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`handler`、`logger.warning`。
        # 副作用/注意事项：会向日志系统输出运行或异常信息。
        def _send():
            try:
                handler(target_name, target_key, event_type, detail)
            except Exception as e:
                logger.warning(f"[InferenceManager] 异常企微推送失败 {target_key}: {e}")

        threading.Thread(
            target=_send,
            daemon=True,
            name=f"inference-runtime-alert-{target_key}",
        ).start()


inference_manager = InferenceManager()
