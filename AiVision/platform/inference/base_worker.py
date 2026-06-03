"""
platform/inference/base_worker.py
推理 Worker 抽象基类 — 定义 ModelWorker 的通用骨架。

每个推理模型对应一个独立子进程,从 infer_queue 取任务、跑推理、
按 function_name 把结果分发到对应 result_queue。

子类只需实现:
    load_model() - 加载模型
    infer(frame) - 跑一次推理,返回 list[dict] 检测结果
"""
from __future__ import annotations
import multiprocessing as mp
import queue
import time
from abc import ABC, abstractmethod
from typing import Any

from core.logger import logger
from platform.inference.model_paths import apply_model_path_override


class BaseModelWorker(ABC):
    """推理 Worker 基类
    
    每个 ModelWorker 跑在独立进程,从 infer_queue 收任务,推理后分发到 result_queues。
    """

    def __init__(
        self,
        infer_queue: mp.Queue,
        result_queues: dict[str, mp.Queue],   # {function_name: Queue}
        model_cfg: dict,                       # 来自 ai_model 表的一行，模型文件路径会被本机配置覆盖
        initial_configs: dict[int, dict],      # {camera_id: function_config_dict}
    ):
        self.infer_queue = infer_queue
        self.result_queues = result_queues
        self.model_cfg = apply_model_path_override(model_cfg)
        self.model_name = self.model_cfg.get("name", "<unknown>")
        self.model_path = self.model_cfg.get("path", "")
        self.model_path_source = self.model_cfg.get("path_source", "database")
        self.initial_configs = initial_configs

        self._proc: mp.Process | None = None
        self._stop_event = mp.Event()
        self._ready_event = mp.Event()
        self._failed_event = mp.Event()

    # ---------- 子类必须实现 ----------

    @abstractmethod
    def load_model(self) -> Any:
        """加载并返回模型实例"""

    @abstractmethod
    def infer(self, model: Any, frame, task_meta: dict) -> list[dict]:
        """对单帧推理。
        
        task_meta 包含: roi_id / camera_id / function_name 等(由 Consumer 投递时设置)
        返回检测结果列表,每项形如 {"bbox": [x1,y1,x2,y2], "confidence": 0.95, "type": "phone"}
        """

    # ---------- 生命周期 ----------

    def start(self):
        if self._proc is not None and self._proc.is_alive():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._failed_event.clear()
        self._proc = mp.Process(
            target=self._run,
            name=f"ModelWorker[{self.model_name}]",
            daemon=True,
        )
        self._proc.start()
        logger.info(f"[ModelWorker:{self.model_name}] 进程已启动 (pid={self._proc.pid})")

    def stop(self):
        self._stop_event.set()
        if self._proc is not None:
            self._proc.join(timeout=5)
            if self._proc.is_alive():
                self._proc.terminate()
            logger.info(f"[ModelWorker:{self.model_name}] 进程已停止")

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def is_ready(self) -> bool:
        return self._ready_event.is_set()

    def is_failed(self) -> bool:
        return self._failed_event.is_set()

    def is_running(self) -> bool:
        return self.is_alive() and self.is_ready() and not self.is_failed()

    # ---------- 配置热更新(由 Orchestrator 调用) ----------

    def update_camera_info(self, camera_id: int):
        """摄像头基础信息变更 — 子进程暂时不消费,留作扩展点"""
        pass

    def update_status(self, camera_id: int, enabled: bool, config: dict | None):
        """摄像头-功能启停变更 — 同上"""
        pass

    # ---------- 主循环(子进程内) ----------

    def _run(self):
        from setproctitle import setproctitle
        setproctitle(f"ModelWorker[{self.model_name}]")

        try:
            model = self.load_model()
            logger.info(
                f"[ModelWorker:{self.model_name}] 模型加载成功 "
                f"path={self.model_path} source={self.model_path_source}"
            )
            self._ready_event.set()
        except Exception:
            self._failed_event.set()
            logger.exception(f"[ModelWorker:{self.model_name}] 模型加载失败,worker 退出")
            return

        while not self._stop_event.is_set():
            try:
                task = self.infer_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                detections = self.infer(model, task["frame"], task)
            except Exception:
                logger.exception(f"[ModelWorker:{self.model_name}] 推理异常")
                detections = []

            # 把结果分发给请求方对应的 function_name 队列
            target_fname = task.get("function_name")
            target_queue = self.result_queues.get(target_fname)
            if target_queue is None:
                continue
            try:
                target_queue.put({
                    "roi_id": task.get("roi_id"),
                    "camera_id": task.get("camera_id"),
                    "function_name": target_fname,
                    "request_id": task.get("request_id"),
                    "detections": detections,
                }, timeout=0.5)
            except queue.Full:
                logger.warning(
                    f"[ModelWorker:{self.model_name}] 结果队列满 ({target_fname}),丢弃"
                )
