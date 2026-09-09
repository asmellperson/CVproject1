"""
platform/inference/base_worker.py
推理 Worker 抽象基类 — 定义 ModelWorker 的通用骨架。

每个物理权重对应一个独立子进程,从逻辑模型队列取任务、跑推理、
按 function_name 把结果分发到对应 result_queue。

子类只需实现:
    load_model() - 加载模型
    infer(frame) - 跑一次推理,返回 list[dict] 检测结果
"""
from __future__ import annotations
import multiprocessing as mp
import queue
import time
from abc import ABC, abstractmethod    # ABC 抽象基类
from typing import Any

from AiVision.core.logger import logger
from AiVision.platform.inference.contracts import (
    INFERENCE_ERROR_MODEL,
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_OK,
    build_inference_result,
)

_QUEUE_POLL_SECONDS = 0.01

class BaseModelWorker(ABC):
    """
    推理 Worker 基类
    每个 ModelWorker 跑在独立进程,从 infer_queue 收任务,推理后分发到 result_queues。
    """
    def __init__(
        self,
        infer_queues: dict[str, mp.Queue],     # 逻辑模型任务入口
        result_queues: dict[str, mp.Queue],   # {function_name: Queue}（推理结果出口）
        model_name: str,
        model_path: str,
    ):
        self.infer_queues = infer_queues
        self._queue_names = tuple(infer_queues)
        self._queue_cursor = 0
        self.result_queues = result_queues
        self.model_name = model_name
        self.model_path = model_path

        self._proc: mp.Process | None = None
        # 通知Worker该退出了
        self._stop_event = mp.Event()
        # 模型已经成功加载，可以推理
        self._ready_event = mp.Event()
        # 模型加载失败
        self._failed_event = mp.Event()
        self._failure_message = mp.Array("c", 4096)

    def failure_message(self) -> str:
        return self._failure_message.value.decode("utf-8", errors="replace")

    # ---------- 子类必须实现 ----------
    # 两个抽象方法
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
        # 如果Worker已经活着，就不创建
        if self._proc is not None and self._proc.is_alive():
            return
        # 否则，清理上一轮，然后开始子进程
        self._stop_event.clear()
        self._ready_event.clear()
        self._failed_event.clear()
        self._failure_message.value = b""
        self._proc = mp.Process(
            target=self._run,
            name=f"ModelWorker[{self.model_name}]",
            daemon=True,
        )
        self._proc.start()
        logger.info(f"[ModelWorker:{self.model_name}] 进程已启动 (pid={self._proc.pid})")

    def stop(self):
        # 告诉Worker不要再取任务
        self._stop_event.set()
        if self._proc is not None:
            self._proc.join(timeout=5)         # 等5秒
            # 还活着就强制结束
            if self._proc.is_alive(): 
                self._proc.terminate()
                self._proc.join(timeout=5)
            if self._proc.is_alive():
                self._proc.kill()
                self._proc.join(timeout=5)
            if self._proc.is_alive():
                raise RuntimeError(f"模型进程无法停止: {self.model_name}")
            self._ready_event.clear()
            logger.info(f"[ModelWorker:{self.model_name}] 进程已停止")

    def is_alive(self) -> bool:
        """Python子进程还活着吗"""
        return self._proc is not None and self._proc.is_alive()

    def is_ready(self) -> bool:
        """模型加载成功了吗"""
        return self._ready_event.is_set()

    def is_failed(self) -> bool:
        """模型加载失败了吗"""
        return self._failed_event.is_set()

    def is_running(self) -> bool:
        """模型进程活着并且模型加载成功并且模型加载不是失败的，才说明模型可用"""
        return self.is_alive() and self.is_ready() and not self.is_failed()

    def _next_task(self) -> dict | None:
        for _ in self._queue_names:
            name = self._queue_names[self._queue_cursor]
            self._queue_cursor = (self._queue_cursor + 1) % len(self._queue_names)
            try:
                task = self.infer_queues[name].get_nowait()
            except queue.Empty:
                continue
            return {**task, "model_name": name}
        return None

    def _execute_task(self, model: Any, task: dict) -> dict:
        """执行单个任务，并保留模型异常与正常空检测之间的语义差异。"""
        # 开始计时
        started_at = time.perf_counter()
        try:
            detections = self.infer(model, task["frame"], task)
            # 推理成功，返回camera_id、roi_id、function_name、request_id.....
            return build_inference_result(
                task,
                status=INFERENCE_STATUS_OK,
                detections=detections,
                inference_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
        # 推理异常不退出，继续处理下一张
        except Exception as exc:
            logger.exception(f"[ModelWorker:{self.model_name}] 推理异常")
            return build_inference_result(
                task,
                status=INFERENCE_STATUS_ERROR,
                error_code=INFERENCE_ERROR_MODEL,
                error_message=str(exc),
                inference_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )

    # ---------- 主循环(子进程内) ----------
    def _run(self):
        # 设置进程名，如ModelWorker[yolo_human]
        from setproctitle import setproctitle
        setproctitle(f"ModelWorker[{self.model_name}]")

        try:
            # 加载模型（子类实现load_model方法，真正做加载pt、加载到GPU、初始化YOLO）
            model = self.load_model()
            logger.info(
                f"[ModelWorker:{self.model_name}] 模型加载成功 "
                f"path={self.model_path} source=local_config"
            )
            # 模型加载完成，接任务
            self._ready_event.set()
        except Exception as exc:
            self._failure_message.value = str(exc).encode("utf-8")[:4095]
            self._failed_event.set()
            logger.exception(f"[ModelWorker:{self.model_name}] 模型加载失败,worker 退出")
            return
        # 不断取任务
        while not self._stop_event.is_set():
            task = self._next_task()
            if task is None:
                self._stop_event.wait(_QUEUE_POLL_SECONDS)
                continue
            # 推理，得到统一结果
            result = self._execute_task(model, task)

            # 把结果分发给请求方对应的 function_name 队列
            target_fname = result.get("function_name")
            target_queue = self.result_queues.get(target_fname)
            # 如果找不到目标队列直接丢掉结果
            if target_queue is None:
                continue
            try:
                target_queue.put(result, timeout=0.5)
            except queue.Full:
                logger.warning(
                    f"[ModelWorker:{self.model_name}] 结果队列满 ({target_fname}),丢弃"
                )
