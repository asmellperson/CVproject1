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


class InferenceManager:
    """所有推理 Worker 进程的管理器"""

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

    def configure_runtime_alerts(self, handler: Callable[[str, str, str, str], None] | None):
        self._runtime_alert_handler = handler

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
                logger.exception("[InferenceManager] 模型 Worker 看门狗异常")

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
            return "worker 不存在"
        if worker.is_failed():
            return "worker 报告失败"
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

    def list_running(self) -> list[str]:
        with self._lock:
            workers = list(self._workers.items())
        return [name for name, worker in workers if worker.is_running()]

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

    def _notify_runtime_alert(self, target_name: str, target_key: str, event_type: str, detail: str):
        handler = self._runtime_alert_handler
        if handler is None:
            return

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
