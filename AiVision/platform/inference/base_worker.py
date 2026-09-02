# 文件说明：实现后台任务相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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

from AiVision.core.logger import logger
from AiVision.platform.inference.contracts import (
    INFERENCE_ERROR_MODEL,
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_OK,
    build_inference_result,
)
from AiVision.platform.inference.model_paths import apply_model_path_override


# 功能：推理 Worker 基类；输入与输出详见下方说明
# 参数：
#   - `infer_queue`（mp.Queue）：`infer_queue` 对应的业务输入值
#   - `result_queues`（dict[str, mp.Queue]）：`result_queues` 对应的业务输入值
#   - `model_cfg`（dict）：`model_cfg` 对应的业务输入值
#   - `initial_configs`（dict[int, dict]）：`initial_configs` 对应的业务输入值
# 返回：BaseModelWorker；返回新建的 `BaseModelWorker` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class BaseModelWorker(ABC):
    """推理 Worker 基类
    
    每个 ModelWorker 跑在独立进程,从 infer_queue 收任务,推理后分发到 result_queues。
    """

    # 功能：初始化或配置 `__init__` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `infer_queue`（mp.Queue）：`infer_queue` 对应的业务输入值
    #   - `result_queues`（dict[str, mp.Queue]）：`result_queues` 对应的业务输入值
    #   - `model_cfg`（dict）：`model_cfg` 对应的业务输入值
    #   - `initial_configs`（dict[int, dict]）：`initial_configs` 对应的业务输入值
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`apply_model_path_override`、`self.model_cfg.get`、`mp.Event`。
    # 副作用/注意事项：会更新当前实例的运行状态。
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

    # 功能：加载并返回模型实例；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Any；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/base_worker.py` 的 `BaseModelWorker::_run` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @abstractmethod
    def load_model(self) -> Any:
        """加载并返回模型实例"""

    # 功能：对单帧推理；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model`（Any）：模型配置或实例
    #   - `frame`（未显式标注）：待处理的视频图像帧
    #   - `task_meta`（dict）：`task_meta` 对应的业务输入值
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/base_worker.py` 的 `BaseModelWorker::_execute_task` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @abstractmethod
    def infer(self, model: Any, frame, task_meta: dict) -> list[dict]:
        """对单帧推理。
        
        task_meta 包含: roi_id / camera_id / function_name 等(由 Consumer 投递时设置)
        返回检测结果列表,每项形如 {"bbox": [x1,y1,x2,y2], "confidence": 0.95, "type": "phone"}
        """

    # ---------- 生命周期 ----------

    # 功能：启动或执行 `start` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._proc.is_alive`、`self._stop_event.clear`、`self._ready_event.clear`、`self._failed_event.clear`、`mp.Process`、`self._proc.start`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
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

    # 功能：停止并释放 `stop` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._stop_event.set`、`self._proc.join`、`self._proc.is_alive`、`self._proc.terminate`、`logger.info`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def stop(self):
        self._stop_event.set()
        if self._proc is not None:
            self._proc.join(timeout=5)
            if self._proc.is_alive():
                self._proc.terminate()
            logger.info(f"[ModelWorker:{self.model_name}] 进程已停止")

    # 功能：检查或判断 `is_alive` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/base_worker.py` 的 `BaseModelWorker::is_running` 调用本符号
    #   - 内部调用：`self._proc.is_alive`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    # 功能：检查或判断 `is_ready` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/base_worker.py` 的 `BaseModelWorker::is_running` 调用本符号
    #   - 内部调用：`self._ready_event.is_set`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_ready(self) -> bool:
        return self._ready_event.is_set()

    # 功能：检查或判断 `is_failed` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/base_worker.py` 的 `BaseModelWorker::is_running` 调用本符号
    #   - 内部调用：`self._failed_event.is_set`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_failed(self) -> bool:
        return self._failed_event.is_set()

    # 功能：检查或判断 `is_running` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.is_alive`、`self.is_ready`、`self.is_failed`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def is_running(self) -> bool:
        return self.is_alive() and self.is_ready() and not self.is_failed()

    # ---------- 配置热更新(由 Orchestrator 调用) ----------

    # 功能：摄像头基础信息变更 — 子进程暂时不消费,留作扩展点；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_camera_info(self, camera_id: int):
        """摄像头基础信息变更 — 子进程暂时不消费,留作扩展点"""
        pass

    # 功能：摄像头-功能启停变更 — 同上；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `enabled`（bool）：是否启用相应能力
    #   - `config`（dict | None）：运行配置对象
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_status(self, camera_id: int, enabled: bool, config: dict | None):
        """摄像头-功能启停变更 — 同上"""
        pass

    # 功能：执行单个任务，并保留模型异常与正常空检测之间的语义差异；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model`（Any）：模型配置或实例
    #   - `task`（dict）：`task` 对应的业务输入值
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/base_worker.py` 的 `BaseModelWorker::_run`
    #         调用本符号；`AiVision/tests/test_inference_outcomes.py` 的 `test_worker_distinguishes_success_from_model_error` 调用本符号
    #   - 内部调用：`time.perf_counter`、`self.infer`、`build_inference_result`、`round`、`logger.exception`、`str`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _execute_task(self, model: Any, task: dict) -> dict:
        """执行单个任务，并保留模型异常与正常空检测之间的语义差异。"""
        started_at = time.perf_counter()
        try:
            detections = self.infer(model, task["frame"], task)
            return build_inference_result(
                task,
                status=INFERENCE_STATUS_OK,
                detections=detections,
                inference_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
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

    # 功能：启动或执行 `_run` 对应的后台任务逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`setproctitle`、`self.load_model`、`logger.info`、`self._ready_event.set`、`self._failed_event.set`、`logger.exception`、`self._stop_event.is_set`、`self.infer_queue.get`、`self._execute_task`、`result.get`
    #          等共 13 个调用。
    # 副作用/注意事项：可能读取或修改数据库事务；会向日志系统输出运行或异常信息。
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

            result = self._execute_task(model, task)

            # 把结果分发给请求方对应的 function_name 队列
            target_fname = result.get("function_name")
            target_queue = self.result_queues.get(target_fname)
            if target_queue is None:
                continue
            try:
                target_queue.put(result, timeout=0.5)
            except queue.Full:
                logger.warning(
                    f"[ModelWorker:{self.model_name}] 结果队列满 ({target_fname}),丢弃"
                )
