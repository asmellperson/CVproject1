"""在同一 Feature 内，把共享结果队列中的结果交给对应的推理请求。

同一功能的多台摄像头、多个模型共用一个结果队列。如果每个请求都直接 get()，
就可能取走其他请求的结果。本模块让一个后台线程统一读取，再按 request_id
查找等待者，并核对功能、摄像头、ROI 和模型身份，避免结果串用。

调用链：
    Consumer 先 register(task)，再把 task 投递到模型输入队列。
    Worker 把结果写入功能结果队列，_read_loop() 读取后由 _route() 分发。
    请求方 wait(pending, timeout) 等待 Event，在 finally 中 unregister(pending)。
    先注册再投递是必要顺序：模型结果可能在投递操作返回前就已经到达。

职责边界：
    路由器只保存请求身份，不保留输入图像，不投递任务，也不取消 Worker 推理。
    本模块校验结果归属；status、detections 等结果内容由 Consumer 继续校验。
    超时、停止及读取故障通过 contracts.py 的统一结果结构交给请求方。
    迟到、重复或无法关联的结果只计数后丢弃，不为未来请求缓存。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import queue
import threading
from typing import Callable

from AiVision.core.logger import logger
from .contracts import (
    INFERENCE_ERROR_INVALID_RESULT,
    INFERENCE_ERROR_ROUTER_FAILED,
    INFERENCE_ERROR_ROUTER_STOPPED,
    INFERENCE_ERROR_TIMEOUT,
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_TIMEOUT,
    INFERENCE_STATUS_UNAVAILABLE,
    build_inference_result,
)

# request_id 用于查找等待者，其余字段共同确认结果确实属于原任务。
_IDENTITY_FIELDS = ("request_id", "function_name", "camera_id", "roi_id", "model_name")
# 定期结束队列阻塞以检查停止信号；这不是单次模型推理的等待时限。
_READ_TIMEOUT_SECONDS = 0.1
_STOP_TIMEOUT_SECONDS = 2.0


@dataclass
class PendingInference:
    """一次已登记请求的线程间交接对象。

    Attributes:
        identity: 原任务五个身份字段的浅拷贝，不含 frame；登记后不应由调用方修改。
        event: 结果已确定时置位，供请求线程等待；超时或不可用结果也会置位。
        result: 尚未完成时为 None，完成后为统一结果字典。写入由路由器加锁保护，
            首次完成后不再替换；调用方不应修改此对象的交接状态。
    """

    identity: dict
    event: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None


class InferenceResultRouter:
    """管理一个功能的结果读取线程，以及该功能全部已登记的推理请求。

    一个结果队列应由一个路由器独占读取，调用方负责把 start()/stop() 接入
    Consumer 生命周期。构造对象不会启动线程；请求完成也不一定立即移除登记，
    调用方仍需在 finally 中 unregister()。
    """

    def __init__(self, result_queue, feature_name: str, *, on_failure: Callable[[str], None] | None = None):
        """准备队列引用、锁和状态，初始状态为 stopped。

        Args:
            result_queue: 支持 get(timeout=秒数) 的队列，读空时应抛出 queue.Empty。
                由推理运行管理器提供，路由器不负责创建或关闭队列。
            feature_name: 固定功能业务标识，例如 detect_human，必须与任务中的
                function_name 一致。
            on_failure: 可选的读取线程故障回调，接收错误说明；默认不回调。
                回调在读取线程中、锁外执行，应避免阻塞或等待该线程自身退出。
        """
        self.result_queue = result_queue
        self.feature_name = feature_name
        self._on_failure = on_failure
        self._lock = threading.Lock()  # 保护请求表、交付结果、状态及计数。
        self._lifecycle_lock = threading.Lock()  # 串行启停，覆盖等待旧线程退出的阶段。
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, PendingInference] = {}
        self._state = "stopped"
        self._last_error = ""
        self._orphan_count = 0
        self._invalid_count = 0

    def start(self) -> None:
        """启动唯一的结果读取线程，已处于正常运行状态时直接返回。

        清除停止信号和上次错误后进入 running；累计异常结果计数不在此重置。
        线程启动失败时记录 failed 状态，并将启动异常继续抛给调用方。

        Raises:
            RuntimeError: 旧线程仍存活但已非 running，或底层无法启动线程。
        """
        with self._lifecycle_lock:
            with self._lock:
                if self._thread is not None and self._thread.is_alive():
                    if self._state == "running":
                        return
                    # 停止超时或故障通知尚未返回时，不能创建第二个队列读取者。
                    raise RuntimeError("推理结果读取线程尚未退出，不能重复启动")
                self._stop_event.clear()
                self._last_error = ""
                self._state = "running"
                self._thread = threading.Thread(
                    target=self._read_loop, name=f"inference-results-{self.feature_name}", daemon=True,
                )
                try:
                    self._thread.start()
                except Exception as exc:
                    self._thread = None
                    self._state = "failed"
                    self._last_error = str(exc)
                    self._stop_event.set()
                    raise

    def stop(self) -> None:
        """停止读取，将未完成请求以 unavailable 结果唤醒，并清空登记表。

        已经交付的结果保持不变。等待后台线程退出期间不持有请求锁，
        使读取线程能够完成收尾；本方法不关闭队列，也不终止模型进程。

        Raises:
            RuntimeError: 读取线程在停止时限内未退出。此时保留线程引用，
                防止后续 start() 在旧线程仍存活时重复启动。
        """
        with self._lifecycle_lock:
            with self._lock:
                self._state = "stopped"
                self._stop_event.set()
                self._finish_pending_locked()
                thread = self._thread
            if thread is not None:
                thread.join(timeout=_STOP_TIMEOUT_SECONDS)
                if thread.is_alive():
                    raise RuntimeError("推理结果读取线程停止超时")
            self._thread = None

    def register(self, task: dict) -> PendingInference:
        """在投递模型任务之前，登记请求身份并返回等待对象。

        Args:
            task: 必须包含 request_id、function_name、camera_id、roi_id 和
                model_name。request_id 必须是非空字符串，例如
                detect_human:12:8f2c7a；调用方应为每次推理生成唯一标识。
                其他任务字段（包括 frame）不会保存在等待对象中。

        Returns:
            PendingInference: 正常运行时加入请求表；未启动、已停止或读取失败时，
            直接返回带有不可用/故障结果且 Event 已置位的对象，不加入请求表。
            调用方应检查该状态，避免继续投递无法接收结果的任务。

        Raises:
            KeyError: task 缺少任一必需身份字段。
            ValueError: request_id 无效、功能名不匹配，或运行时重复登记同一 ID。
        """
        identity = {key: task[key] for key in _IDENTITY_FIELDS}
        request_id = identity["request_id"]
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("推理请求必须提供非空 request_id")
        if identity["function_name"] != self.feature_name:
            raise ValueError("推理请求的 function_name 与结果路由器不一致")
        pending = PendingInference(identity)
        with self._lock:
            if self._state != "running":
                self._complete_locked(pending, self._unavailable_result(identity))
            elif request_id in self._pending:
                raise ValueError(f"重复注册推理请求: {request_id}")
            else:
                self._pending[request_id] = pending
        return pending

    def wait(self, pending: PendingInference, timeout: float) -> dict:
        """等待一个已登记请求，返回最终确定的结果字典。

        Args:
            pending: 由本路由器 register() 返回的对象。
            timeout: 本次 Event 等待的秒数，从调用 wait() 时开始；负数按零处理，
                不包含之前登记或投递任务花费的时间。

        Returns:
            dict: 已交付的模型结果、身份错误、路由不可用/故障结果，或本地生成的
            timeout 结果。本方法用结果状态表达超时，不抛出 TimeoutError。
            返回现有结果对象，不另行复制。

        未有结果时，在锁内生成超时结果并移除登记；正常收到结果的登记仍由
        调用方 unregister() 清理。超时不会取消模型任务，迟到结果会被丢弃。
        """
        pending.event.wait(timeout=max(0.0, timeout))
        # 超时与结果交付使用同一把锁，只有先完成的一方可以决定结果。
        # 不只看 Event.wait() 的返回值：等待结束到获得锁之间仍可能已有结果到达。
        with self._lock:
            if pending.result is None:
                self._complete_locked(pending, build_inference_result(
                    pending.identity, status=INFERENCE_STATUS_TIMEOUT,
                    error_code=INFERENCE_ERROR_TIMEOUT,
                    error_message=f"等待推理结果超时: {timeout:.3f}s",
                ))
                self._remove_locked(pending)
            return pending.result

    def unregister(self, pending: PendingInference) -> None:
        """移除指定等待对象的登记，供投递失败或等待结束后的 finally 清理。

        Args:
            pending: 本路由器返回的等待对象；已移除时再次调用没有副作用。

        此操作不设置结果、不唤醒 Event，也不取消 Worker 任务；不能当作取消请求。
        若移除后继续 wait() 且尚无结果，等待者仍会等到自己的超时时限。
        """
        with self._lock:
            self._remove_locked(pending)

    def snapshot(self) -> dict:
        """返回同一锁内取得的运行状态快照，不暴露等待对象或队列内容。

        Returns:
            dict: state 为 stopped、running 或 failed；last_error 是记录的读取/启动错误。
            pending_count 是尚未移除的登记数，可能包含已交付但未 unregister 的请求。
            orphan_count 累计无法关联或重复的结果，invalid_count 累计身份不匹配结果；
            两项计数都在对象生命周期内累积，不随 start()/stop() 清零。
        """
        with self._lock:
            return {
                "state": self._state,
                "pending_count": len(self._pending),
                "orphan_count": self._orphan_count,
                "invalid_count": self._invalid_count,
                "last_error": self._last_error,
            }

    def _remove_locked(self, pending: PendingInference) -> None:
        """在已持有请求锁时移除同一对象，避免旧请求误删同 ID 的后续登记。"""
        request_id = pending.identity["request_id"]
        if self._pending.get(request_id) is pending:
            del self._pending[request_id]

    @staticmethod
    def _complete_locked(pending: PendingInference, result: dict) -> None:
        """在请求锁内首次写入结果并唤醒等待者，后续完成尝试保持原结果。"""
        if pending.result is None:
            pending.result = result
            # 先写结果再发信号，使被唤醒的请求方看到完整的交付状态。
            pending.event.set()

    def _unavailable_result(self, identity: dict) -> dict:
        """在请求锁内按路由状态构造失败结果，保留原请求的身份字段。

        failed 对应 error/inference_router_failed，并附带已记录错误；其他状态
        对应 unavailable/inference_router_stopped。调用方仅在路由不可用时使用。
        """
        failed = self._state == "failed"
        return build_inference_result(
            identity, status=INFERENCE_STATUS_ERROR if failed else INFERENCE_STATUS_UNAVAILABLE,
            error_code=INFERENCE_ERROR_ROUTER_FAILED if failed else INFERENCE_ERROR_ROUTER_STOPPED,
            error_message=self._last_error if failed else "推理结果路由器尚未启动或已停止",
        )

    def _finish_pending_locked(self) -> None:
        """在请求锁内结束全部未完成等待并清表，供停止或读取故障收尾。

        通过 _complete_locked() 保留已经完成的结果；尚未完成的结果依据调用方
        预先设置的 stopped/failed 状态生成，所有等待者都会得到完成信号。
        """
        for pending in self._pending.values():
            self._complete_locked(pending, self._unavailable_result(pending.identity))
        self._pending.clear()

    def _route(self, outcome) -> None:
        """处理一条队列结果：关联请求、校验身份并交付，或计数后丢弃。

        Args:
            outcome: 队列读出的任意对象。非字典、缺少可用 request_id、找不到登记
                或对应请求已完成时记为 orphan；只有匹配到等待者后才逐项校验身份。

        身份不匹配时将该请求完成为 invalid_inference_result，不继续等待另一条结果。
        身份一致时浅拷贝整个字典交付，不在这里验证 status 或 detections 的结构。
        已完成登记暂时保留，等待请求方 finally 清理。
        """
        request_id = outcome.get("request_id") if isinstance(outcome, dict) else None
        with self._lock:
            pending = self._pending.get(request_id) if isinstance(request_id, str) else None
            if pending is None or pending.result is not None:
                # 不缓存迟到、重复或无法识别请求的结果。
                self._orphan_count += 1
                return
            # 必须同时比较类型和值，避免 Python 把 True 与 1 等不同身份视作相等。
            mismatches = [key for key, expected in pending.identity.items()
                          if type(outcome.get(key)) is not type(expected) or outcome.get(key) != expected]
            if mismatches:
                self._invalid_count += 1
                message = f"推理结果身份不匹配: {', '.join(mismatches)}"
                logger.warning(f"[{self.feature_name}] {message}, request_id={request_id}")
                result = build_inference_result(
                    pending.identity, status=INFERENCE_STATUS_ERROR,
                    error_code=INFERENCE_ERROR_INVALID_RESULT, error_message=message,
                )
            else:
                result = dict(outcome)
            self._complete_locked(pending, result)

    def _read_loop(self) -> None:
        """后台独占读取队列，退出时唤醒请求方并按需通知运行时。

        queue.Empty 只表示当前没有结果，继续检查停止信号；读取或分发的其他异常
        记录日志并进入收尾。只有退出时仍为 running 才视为意外失败，正常 stop()
        已先改为 stopped，因此不会重复报故障。
        """
        failure = "推理结果读取线程意外退出"
        try:
            while not self._stop_event.is_set():
                try:
                    outcome = self.result_queue.get(timeout=_READ_TIMEOUT_SECONDS)
                except queue.Empty:
                    continue
                self._route(outcome)
        except Exception as exc:
            failure = f"推理结果读取失败: {type(exc).__name__}: {exc}"
            logger.exception(f"[{self.feature_name}] {failure}")
        finally:
            with self._lock:
                failed = self._state == "running"
                if failed:
                    self._state = "failed"
                    self._last_error = failure
                    self._stop_event.set()
                    self._finish_pending_locked()
            # 先唤醒请求，再在锁外通知运行时，避免慢回调阻塞请求锁或失败时遗漏清理。
            if failed and self._on_failure is not None:
                try:
                    self._on_failure(failure)
                except Exception:
                    logger.exception(f"[{self.feature_name}] 推理结果路由异常通知失败")
