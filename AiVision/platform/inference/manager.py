"""
platform/inference/manager.py
推理 Worker 进程生命周期管理 — 替代旧 CapManager.start_inferworker。

启动时按数据库 ai_model 表逐个尝试加载模型元数据，模型文件路径来自本机配置文件。
导入失败 / 模型缺失 / 本机路径未配置时会跳过,
不影响其他模型。Consumer 那边通过 _dispatch_frame 找不到对应模型时也会优雅降级。
"""
from __future__ import annotations
import importlib
import os
import threading
import time
from multiprocessing import Queue
from typing import Callable

from core.logger import logger
from core.cache import config_cache
from features import all_specs
from .service import model_service


class InferenceManager:
    """所有推理 Worker 进程的管理器"""

    def __init__(self):
        # model_name → infer_queue (Consumer 投递任务给 Worker)
        self.infer_queues: dict[str, Queue] = {}
        # function_name → result_queue (Worker 把结果推给对应 Consumer)
        self.result_queues: dict[str, Queue] = {}
        # model_name → BaseModelWorker 实例
        self._workers: dict[str, object] = {}
        self._runtime_alert_handler: Callable[[str, str, str, str], None] | None = None

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
        for model in model_service.list_models(enabled_only=True):
            self._start_one(model)
        total_workers = len(self._workers)
        self._wait_for_workers_ready()
        logger.info(
            f"[InferenceManager] 模型就绪 {len(self.list_running())}/{total_workers}: "
            f"{self.list_running()}"
        )

    def stop_all(self):
        for name, worker in list(self._workers.items()):
            try:
                worker.stop()
            except Exception as e:
                logger.warning(f"[InferenceManager] 停止 {name} 失败: {e}")
        self._workers.clear()

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
        try:
            timeout = float(os.getenv("MODEL_WORKER_READY_TIMEOUT", "60"))
        except ValueError:
            timeout = 60.0

        deadline = time.monotonic() + max(0.0, timeout)
        pending = set(self._workers.keys())

        while pending and time.monotonic() < deadline:
            for name in list(pending):
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
            worker = self._workers.get(name)
            if worker is not None:
                try:
                    worker.stop()
                except Exception as e:
                    logger.warning(f"[InferenceManager] 停止未就绪模型 {name} 失败: {e}")

        self._workers = {
            name: worker
            for name, worker in self._workers.items()
            if worker.is_running()
        }

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
        for name, worker in list(self._workers.items()):
            if not worker.is_running():
                self._notify_runtime_alert(name, name, "模型 Worker 退出", "worker 已不在运行状态")
        self._workers = {
            name: worker
            for name, worker in self._workers.items()
            if worker.is_running()
        }
        return list(self._workers.keys())

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
