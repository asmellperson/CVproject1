"""
inference/runtime_manager.py
所有模型Worker的总运行调度器

负责建队列、查模型配置、启动Worker、判断是否就绪、Worker挂掉后自动恢复、提供运行状态

只启动已注册 Feature 依赖的模型，模型文件路径来自本机配置文件。
所需模型缺失 / 本机路径未配置时记录失败，由 Watchdog 重试，
不影响其他模型。Consumer 继续通过推理结果 contract 处理超时或失败。

"""
from __future__ import annotations
import queue
import threading
import time
from dataclasses import dataclass
from multiprocessing import Queue
from pathlib import Path
from typing import Callable

from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.features.registry import all_specs
from .model_registry import MODEL_SPECS, get_model_spec
from .model_paths import load_model_paths, save_model_path, validate_model_path

@dataclass
class WorkerWatchdogState:
    """记录某一个模型Worker当前自动恢复到什么状态了"""
    # 已经重启几次
    restart_attempts: int = 0
    # 下一次允许什么时候重启
    next_restart_at: float = 0.0
    # 新Worker最迟什么时候必须加载完成
    ready_deadline: float = 0.0
    # 从什么时候开始稳定运行
    running_since: float | None = None
    last_restart_at: float | None = None
    # 上次失败原因
    last_failure_at: float | None = None
    last_failure: str = ""
    # 重启机会是不是已经用完
    exhausted: bool = False
    exhausted_alerted: bool = False

class InferenceRuntimeManager:
    """所有推理 Worker 进程的管理器"""
    def __init__(self):
        # model_name → infer_queue (Consumer 投递任务给 Worker)
        self.infer_queues: dict[str, Queue] = {}
        # function_name → result_queue (Worker 把结果推给对应 Consumer)
        self.result_queues: dict[str, Queue] = {}
        # model_name → BaseModelWorker 实例
        self._workers: dict[str, object] = {}
        self._model_configs: dict[str, dict] = {}
        self._model_owners: dict[str, str] = {}
        self._worker_states: dict[str, WorkerWatchdogState] = {}
        self._runtime_alert_handler: Callable[[str, str, str, str], None] | None = None
        self._runtime_monitor_handler: Callable[[], None] | None = None
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._configuration_lock = threading.RLock()
        self._reload_thread: threading.Thread | None = None
        self._reload_results: dict[str, dict] = {}
        self._active = False
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self._shutting_down = False
    
    def initialize_queues(self):
        """启动前预创建所有队列
        一个模型一个输入队列
        一个功能一个输出队列
        """
        # 一个逻辑模型一个推理输入队列
        for name in MODEL_SPECS:
            if name not in self.infer_queues:
                self.infer_queues[name] = Queue(maxsize=10)
        # 一个 feature 一个结果队列
        for fname in all_specs():
            if fname not in self.result_queues:
                self.result_queues[fname] = Queue(maxsize=10)

        logger.info(
            f"[InferenceRuntimeManager] 初始化 {len(self.infer_queues)} 个推理队列, "
            f"{len(self.result_queues)} 个结果队列"
        )

    def start_all(self):
        """加载 Feature 所需模型；同类 Worker 共享同一物理权重。"""
        with self._lifecycle_lock:
            self._start_all()

    def _start_all(self):
        if self._active:
            return
        groups, owners = self._build_model_groups()
        models = list(groups.values())
        with self._lock:
            self._active = True
            self._shutting_down = False
            self._model_configs = groups
            self._model_owners = owners
            self._worker_states = {
                model["name"]: WorkerWatchdogState()
                for model in models
            }
        for model in models:
            # 给一个模型配置，创建并启动它对应的Worker
            self._start_one(model)
        total_workers = len(self._model_owners)
        # 等待Working已经准备加载好
        self._wait_for_workers_ready()
        now = time.monotonic()
        with self._lock:
            for name, worker in self._workers.items():
                if worker.is_running():
                    self._worker_states.setdefault(name, WorkerWatchdogState()).running_since = now
        # 启动看门狗
        self._start_watchdog()
        logger.info(
            f"[InferenceRuntimeManager] 模型就绪 {len(self.list_running())}/{total_workers}: "
            f"{self.list_running()}"
        )

    def stop_all(self):
        """
        流程：
            self._shutting_down = True
            先停watchdog
            取出所有Worker
            逐个worker.stop()
            清内部注册
        """
        with self._lock:
            self._shutting_down = True
            self._active = False
        self._stop_watchdog()
        with self._lifecycle_lock:
            with self._lock:
                workers = list(self._workers.items())
            for name, worker in workers:
                worker.stop()
                with self._lock:
                    self._workers.pop(name, None)
            with self._lock:
                self._model_configs.clear()
                self._model_owners.clear()
                self._worker_states.clear()

    def configure_runtime_alerts(self, handler: Callable[[str, str, str, str], None] | None):
        """模型异常报警（model worker）"""
        self._runtime_alert_handler = handler

    def configure_runtime_monitor(self, handler: Callable[[], None] | None) -> None:
        """注册由现有 watchdog 周期调用的额外运行状态检查。（顺便执行运行状态监控）"""
        with self._lock:
            self._runtime_monitor_handler = handler

    def _start_one(self, model_cfg: dict) -> bool:
        """启动单个模型"""
        name = model_cfg["name"]
        try:
            model_path = validate_model_path(model_cfg["path"], model_type=get_model_spec(name).type)
            worker_cls = model_cfg["worker_class"]
            # 创建Worker
            worker = worker_cls(
                infer_queues={key: self.infer_queues[key] for key in model_cfg["model_names"]},
                result_queues=self.result_queues,
                model_name=name,
                model_path=model_path,
            )
            # 开启（一个物理权重一个python子进程）
            worker.start()
            with self._lock:
                self._workers[name] = worker
                state = self._worker_states.setdefault(name, WorkerWatchdogState())
                state.ready_deadline = time.monotonic() + settings.runtime.model_worker_ready_timeout_seconds
            logger.info(f"[InferenceRuntimeManager] 推理 Worker 启动: {name}")
            return True
        except Exception as e:
            with self._lock:
                state = self._worker_states.setdefault(name, WorkerWatchdogState())
                state.last_failure = str(e)
                state.last_failure_at = time.time()
            logger.exception(f"[InferenceRuntimeManager] 启动 Worker {name} 失败: {e}")
            self._notify_runtime_alert(name, name, "模型 Worker 启动失败", str(e))
            return False

    def _wait_for_workers_ready(self, names: set[str] | None = None):
        """等待子进程完成模型加载,避免状态接口把加载失败的模型误判为在线。"""
        timeout = settings.runtime.model_worker_ready_timeout_seconds

        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            pending = set(self._workers.keys()) if names is None else names & self._workers.keys()

        while pending and time.monotonic() < deadline:
            for name in list(pending):
                with self._lock:
                    worker = self._workers.get(name)
                if worker is None:
                    pending.discard(name)
                    continue
                # 循环判断Worker是不是在运行，在的话从pending移除
                if worker.is_running():
                    pending.discard(name)
                    continue
                if worker.is_failed() or not worker.is_alive():
                    state = self._worker_states[name]
                    state.last_failure = worker.failure_message() or "worker 加载失败或进程已退出"
                    state.last_failure_at = time.time()
                    worker.stop()
                    logger.warning(f"[InferenceRuntimeManager] 模型 {name} 未就绪,worker 已失败或退出")
                    self._notify_runtime_alert(name, name, "模型 Worker 未就绪", "worker 已失败或退出")
                    pending.discard(name)
                    continue
            if pending:
                time.sleep(0.2)

        # 进程活着，但是模型30秒没加载成功，就stop
        for name in sorted(pending):
            self._worker_states[name].last_failure = "模型加载超时"
            self._worker_states[name].last_failure_at = time.time()
            logger.warning(
                f"[InferenceRuntimeManager] 模型 {name} 在 {timeout:.1f}s 内未完成加载,暂不计入运行模型"
            )
            self._notify_runtime_alert(name, name, "模型 Worker 加载超时", f"{timeout:.1f}s 内未完成加载")
            with self._lock:
                worker = self._workers.get(name)
            if worker is not None:
                try:
                    worker.stop()
                except Exception as e:
                    logger.warning(f"[InferenceRuntimeManager] 停止未就绪模型 {name} 失败: {e}")

    # ---------- Worker 看门狗 ----------
    def _start_watchdog(self) -> None:
        with self._lock:
            if not self._model_configs and self._runtime_monitor_handler is None:
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
        logger.info("[InferenceRuntimeManager] 模型 Worker 看门狗已启动")

    def _stop_watchdog(self) -> None:
        self._watchdog_stop.set()
        with self._lock:
            thread = self._watchdog_thread
            self._watchdog_thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, settings.runtime.model_worker_watchdog_interval_seconds * 2))

    def _watchdog_loop(self) -> None:
        interval = settings.runtime.model_worker_watchdog_interval_seconds
        while not self._watchdog_stop.wait(interval):
            try:
                self._watchdog_tick()
            except Exception:
                logger.exception("[InferenceRuntimeManager] 模型 Worker 看门狗异常")

    def _watchdog_tick(self, now: float | None = None) -> None:
        with self._lifecycle_lock:
            self._watchdog_tick_locked(now)
        self._run_runtime_monitor()

    def _watchdog_tick_locked(self, now: float | None = None) -> None:
        """
        执行一次存活检查；独立成方法便于确定性测试。
        整体思路：
            每隔N秒，检查所有启动时配置的Model。worker正常就什么都不做，Worker异常记录失败，等backoff，重启，如果又失败，在等更久，达到最大次数，exhausted + 报警
        """
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
                # Worker稳定运行超过model_worker_restart_reset_seconds会restart_attempts=0
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
                        # _restart_backoff_seconds():指数退避：假设基础间隔5秒钟，这里第一次5秒，第二次10秒，第三次20秒...
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
                    f"[InferenceRuntimeManager] 模型 {name} Worker 异常: {reason}; "
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
                    f"[InferenceRuntimeManager] 模型 {name} Worker 已耗尽 "
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

    def _run_runtime_monitor(self) -> None:
        with self._lock:
            handler = self._runtime_monitor_handler
        if handler is None:
            return
        try:
            handler()
        except Exception:
            logger.exception("[InferenceRuntimeManager] 附加运行状态检查异常")

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

    @staticmethod
    def _worker_failure_reason(
        worker: object | None,
        state: WorkerWatchdogState,
        now: float,
    ) -> str:
        if worker is None:
            return state.last_failure or "worker 不存在"
        if worker.is_failed():
            return worker.failure_message() or state.last_failure or "worker 报告失败"
        if not worker.is_alive():
            return "worker 进程已退出"
        if state.ready_deadline and now >= state.ready_deadline:
            return "worker 加载超时"
        return "worker 未就绪"

    @staticmethod
    def _restart_backoff_seconds(previous_attempts: int) -> float:
        base = settings.runtime.model_worker_restart_backoff_seconds
        maximum = settings.runtime.model_worker_restart_max_backoff_seconds
        return min(base * (2 ** previous_attempts), maximum)

    def _restart_worker(
        self,
        name: str,
        model_cfg: dict,
        attempt: int,
        now: float,
    ) -> None:
        """
        重启流程：
            old_worker.stop()
            从_workers移除旧worker
            丢弃关联逻辑模型队列中的待处理任务
            _start_one(model_cfg)
            创建新Worker
            等待ready
        """
        with self._lock:
            if self._shutting_down:
                return
            old_worker = self._workers.get(name)
        if old_worker is not None:
            try:
                old_worker.stop()
            except Exception as e:
                logger.warning(f"[InferenceRuntimeManager] 回收异常 Worker {name} 失败: {e}")
                return
            with self._lock:
                self._workers.pop(name, None)
        discarded = sum(self._discard_pending_tasks(key) for key in model_cfg["model_names"])
        if discarded:
            logger.warning(f"[InferenceRuntimeManager] 重启模型 {name} 前丢弃 {discarded} 个过期任务")

        logger.warning(f"[InferenceRuntimeManager] 正在第 {attempt} 次重启模型 Worker: {name}")
        started = self._start_one(model_cfg)
        with self._lock:
            state = self._worker_states.setdefault(name, WorkerWatchdogState())
            if started:
                state.ready_deadline = now + settings.runtime.model_worker_ready_timeout_seconds
                state.last_failure = ""
            else:
                state.ready_deadline = 0.0
                state.last_failure = state.last_failure or "worker 重启启动失败"
                state.last_failure_at = time.time()

        if not started:
            self._notify_runtime_alert(
                name,
                name,
                "模型 Worker 重启失败",
                f"第 {attempt} 次重启未能启动进程",
            )

    def _discard_pending_tasks(self, name: str) -> int:
        """丢弃未处理的任务"""
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
                logger.warning(f"[InferenceRuntimeManager] 清理模型 {name} 待处理队列失败: {exc}")
                return discarded

    @staticmethod
    def _required_model_names() -> set[str]:
        required = {name for spec in all_specs().values() for name in spec.required_models}
        unknown = required - MODEL_SPECS.keys()
        if unknown:
            raise ValueError(f"Feature 引用了未注册模型: {sorted(unknown)}")
        return required

    @staticmethod
    def _declared_model_names() -> set[str]:
        declared = {name for spec in all_specs().values() for name in spec.model_names}
        unknown = declared - MODEL_SPECS.keys()
        if unknown:
            raise ValueError(f"Feature 引用了未注册模型: {sorted(unknown)}")
        return declared

    def _build_model_groups(self) -> tuple[dict[str, dict], dict[str, str]]:
        required = self._required_model_names()
        declared = self._declared_model_names()
        paths = load_model_paths()
        groups, owners, identities = {}, {}, {}
        for name, spec in MODEL_SPECS.items():
            if name not in declared:
                continue
            path = paths.get(name, "")
            try:
                resolved = Path(validate_model_path(path, model_type=spec.type))
                info = resolved.stat()
                identity = (spec.worker_class, info.st_dev, info.st_ino)
            except (OSError, ValueError) as exc:
                # 可选模型没有合法本机路径时不创建 Worker，也不进入重试循环。
                if name not in required:
                    if path:
                        logger.warning(f"[InferenceRuntimeManager] 可选模型 {name} 路径不可用: {exc}")
                    continue
                identity = (name,)
            owner = identities.setdefault(identity, name)
            owners[name] = owner
            group = groups.setdefault(owner, {
                "name": owner, "path": path, "worker_class": spec.worker_class, "model_names": [],
            })
            group["model_names"].append(name)
        return groups, owners

    def list_models(self) -> list[dict]:
        paths = load_model_paths()
        statuses = {item["model_name"]: item for item in self.runtime_status()["models"]}
        with self._lock:
            return [{
                "name": name,
                "type": spec.type,
                "path": paths.get(name, ""),
                "runtime": statuses.get(name, {
                    "status": "not_started", "running": False, "alive": False,
                    "loaded_path": "", "last_failure": "", "shared_models": [name],
                }),
                "reload": dict(self._reload_results.get(name, {"status": "idle", "error": ""})),
            } for name, spec in MODEL_SPECS.items()]

    def update_model_path(self, name: str, path: str) -> dict:
        get_model_spec(name)
        with self._configuration_lock:
            if self._reload_thread is not None and self._reload_thread.is_alive():
                raise RuntimeError("已有模型正在重载，请等待加载完成后再保存")
            declared = name in self._declared_model_names()
            saved_path = save_model_path(name, path)
            with self._lock:
                active = self._active and not self._shutting_down and declared
                self._reload_results[name] = {
                    "status": "loading" if active else "not_started", "error": "",
                }
            if active:
                self._reload_thread = threading.Thread(
                    target=self._reload_affected, args=(name,),
                    name="inference-model-reload", daemon=True,
                )
                self._reload_thread.start()
            return {
                "configuration_saved": True,
                "name": name,
                "path": saved_path,
                "load_status": "loading" if active else "not_started",
            }

    def _reload_affected(self, name: str) -> None:
        affected = {name}
        with self._lifecycle_lock:
            try:
                if not self._active or self._shutting_down or name not in self._declared_model_names():
                    with self._lock:
                        self._reload_results[name] = {"status": "not_started", "error": ""}
                    return
                groups, owners = self._build_model_groups()
                with self._lock:
                    previous = dict(self._model_configs)
                while True:
                    expanded = set(affected)
                    for group in (*previous.values(), *groups.values()):
                        if affected.intersection(group["model_names"]):
                            expanded.update(group["model_names"])
                    if expanded == affected:
                        break
                    affected = expanded
                with self._lock:
                    for key in affected:
                        self._reload_results[key] = {"status": "loading", "error": ""}
                old_owners = [key for key, group in previous.items()
                              if affected.intersection(group["model_names"])]
                for owner in old_owners:
                    worker = self._workers.get(owner)
                    if worker is not None:
                        worker.stop()
                        with self._lock:
                            self._workers.pop(owner, None)
                new_groups = {key: group for key, group in groups.items()
                              if affected.intersection(group["model_names"])}
                with self._lock:
                    for owner in old_owners:
                        self._model_configs.pop(owner, None)
                        self._worker_states.pop(owner, None)
                    self._model_configs.update(new_groups)
                    for key in affected:
                        self._model_owners.pop(key, None)
                    self._model_owners.update({key: owners[key] for key in affected if key in owners})
                    for owner in new_groups:
                        self._worker_states[owner] = WorkerWatchdogState()
                for key in affected:
                    self._discard_pending_tasks(key)
                for group in new_groups.values():
                    self._start_one(group)
                self._wait_for_workers_ready(set(new_groups))
                with self._lock:
                    for key in affected:
                        if key not in owners:
                            self._reload_results[key] = {"status": "not_started", "error": ""}
                            continue
                        owner = owners[key]
                        worker = self._workers.get(owner)
                        running = worker is not None and worker.is_running()
                        self._reload_results[key] = {
                            "status": "succeeded" if running else "failed",
                            "error": "" if running else self._worker_states[owner].last_failure or "模型加载失败",
                        }
            except Exception as exc:
                logger.exception(f"[InferenceRuntimeManager] 重载模型 {name} 失败")
                with self._lock:
                    for key in affected:
                        self._reload_results[key] = {"status": "failed", "error": str(exc)}

    # ---------- 状态查询 ----------
    def is_model_running(self, name: str) -> bool:
        """按逻辑模型查询共享物理 Worker，不启动或加载模型。"""
        get_model_spec(name)
        with self._lock:
            owner = self._model_owners.get(name)
            worker = self._workers.get(owner)
            return worker is not None and worker.is_running()

    def list_running(self) -> list[str]:
        with self._lock:
            return [name for name, owner in self._model_owners.items()
                    if owner in self._workers and self._workers[owner].is_running()]

    def runtime_status(self) -> dict:
        """返回 Worker 与自动恢复状态，不改变任何运行状态。
        告诉前端：
            running
            starting
            backoff
            exhausted
            stopped
        返回：
            restart_attempts
            next_restart_in_seconds
            last_restart_at
            last_failure
        """
        now = time.monotonic()
        with self._lock:
            models = []
            for name, owner in sorted(self._model_owners.items()):
                worker = self._workers.get(owner)
                state = self._worker_states[owner]
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
                elif state.last_failure or (worker is not None and worker.is_failed()):
                    status = "failed"
                else:
                    status = "stopped"
                models.append({
                    "model_name": name,
                    "status": status,
                    "running": running,
                    "alive": alive,
                    "loaded_path": worker.model_path if running else "",
                    "shared_models": list(self._model_configs[owner]["model_names"]),
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

    def _notify_runtime_alert(self, target_name: str, target_key: str, event_type: str, detail: str):
        """
        异常报警
        为了不阻塞watchdog，会新开一个守护线程去发送异常通知
        类型：
            模型导入失败
            模型加载超时
            Worker退出
            Worker重启失败
            重启次数耗尽
        """
        handler = self._runtime_alert_handler
        if handler is None:
            return

        def _send():
            try:
                handler(target_name, target_key, event_type, detail)
            except Exception as e:
                logger.warning(f"[InferenceRuntimeManager] 异常企微推送失败 {target_key}: {e}")

        threading.Thread(
            target=_send,
            daemon=True,
            name=f"inference-runtime-alert-{target_key}",
        ).start()


inference_runtime_manager = InferenceRuntimeManager()
