"""
features/_shared/consumer.py
功能基类 — 业务逻辑处理框架。

子类实现业务推理和可视化，并可按需扩展告警:
    _process(roi, camera_id) → (is_alarm, msg_dict)
    post_process(camera_id, result) → annotated_frame
    (可选) _should_alarm(...) — 仅 detect_door 需要(双阶段告警)
    (可选) _alarm_context(...) — 提供告警主体、冷却主体、原因和业务元数据

通用部分(帧读取、ROI 裁剪、相似帧跳过、告警分发)由本类提供:
    stop/start、配置热更新、Camera启停/删除状态
    图像预处理: 归一化单 ROI、polygon mask、ROI剪裁、帧差跳帧
    推理通信: 构造Task、infer_queue、result_queue、request_id匹配、timeout、queue full
    推理健康监控: 失败统计、连续失败、系统异常通知
    Feature业务模板: _process(),post_process()
    前端结果帧缓存: AlarmRequest构造与告警分发
"""
from __future__ import annotations
from AiVision.departments.department_registry import require_department
import threading
import time
from uuid import uuid4
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

from AiVision.core.cache import config_cache
from AiVision.core.logger import logger
from AiVision.alarms.dispatcher import alarm_dispatcher, AlarmRequest
from AiVision.core.settings import settings
from AiVision.features._shared.spec import FeatureSpec
from AiVision.features._shared.roi import annotate_roi, roi_to_pixels
from AiVision.features._shared.preview import AnnotatedPreviewFrame, DetectionPreviewFrame
from AiVision.features._shared.defaults import PREVIEW_FRAME_MAX_AGE_SECONDS
from AiVision.inference.contracts import (
    INFERENCE_ERROR_INVALID_RESULT,
    INFERENCE_ERROR_QUEUE_FULL,
    INFERENCE_ERROR_UNAVAILABLE,
    INFERENCE_FAILURE_STATUSES,
    INFERENCE_STATUS_DROPPED,
    INFERENCE_STATUS_ERROR,
    INFERENCE_STATUS_OK,
    INFERENCE_STATUS_UNAVAILABLE,
    build_inference_result,
)
from AiVision.inference.input_frames import prepare_inference_task
from AiVision.inference.result_router import InferenceResultRouter, PendingInference

# 帧差计算不是每个摄像头都比，是每隔4个像素采样一次，降低计算量
_FRAME_CHANGE_SAMPLE_STEP = 4
# 高斯模糊核。比较两帧之前先模糊，减少噪点导致的假变化
_FRAME_CHANGE_BLUR_KERNEL = (5, 5)
_CONSUMER_STOP_TIMEOUT_SECONDS = 5.0
_INFERENCE_TIMEOUT_SECONDS = 0.8


@dataclass
class SubmittedInference:
    """已投递请求的等待信息，不持有输入图像；共享同步和流水线的结果处理。"""

    camera_id: int
    model_name: str
    started_at: float
    deadline_at: float
    pending: PendingInference | None = None
    result: dict | None = None

    def ready(self, now: float) -> bool:
        """调用方可以领取已返回的结果，或结算已经到期的请求。"""
        return (self.result is not None
                or (self.pending is not None and self.pending.event.is_set())
                or now >= self.deadline_at)

class BaseFunctionConsumer(ABC):
    """
    所有功能消费者的基类，每个功能对应一个独立的 Consumer 线程。Consumer 是 Feature 级运行实例，Consumer 内部同时管理多台 Camera

    职责划分:
        本类负责  — 帧读取、ROI 裁剪、相似帧跳过、告警分发、推理调度。
        子类负责  — _process()（业务推理）、post_process()（可视化标注）。

    扩展点:
        _should_alarm()       : 默认判定 result 中有 True 即告警，
                                detect_door 等双阶段场景可重写此方法。
        _alarm_context()      : 默认使用摄像头主体；子类可提供业务主体、冷却主体及元数据。
        _reset_alarm_cooldown(): 清理本功能的摄像头冷却；使用其他冷却主体的子类须重写。
        _alarm_violation_type(): 单报警功能使用唯一类型；复合功能必须明确选择本次报警类型。
        _process_static_frames(): 默认返回 False（帧差类功能依赖画面变化），
                                  YOLO 逗留检测类功能重写为 True 以持续累积时间。

    生命周期:
        Orchestrator 调用 start() → 内部加载配置并启动守护线程 _run()。
        配置变更时 Orchestrator 调用 update_config() / update_status() 热更新。
        stop() 关闭推理投递、唤醒等待者，并等待结果路由与处理线程退出。
    """
    ROI_COLOR = (238, 211, 34)

    def __init__(
        self,
        spec: FeatureSpec,
        infer_dict: dict,                          # {model_name: Queue}，推理调度入口
        result_queue,                               # 本 feature 接收推理结果的队列
        latest_frames: dict[str, np.ndarray],      # 由 FrameReaderRegistry 维护的最新帧字典
        is_camera_active,                           # callable(shm_name) -> bool，查询摄像头是否在线
        runtime_alert_handler: Callable[[str, str, str, str], None] | None = None,
        latest_frame_times: dict[str, float] | None = None,
    ):
        """绑定功能、推理队列和帧来源，初始化路由器及各摄像头状态。

        构造过程不启动消费线程；start 才建立运行生命周期。摄像头状态、
        提交过程和生命周期使用不同锁，避免停止操作与推理注册相互干扰。
        """
        self.spec = spec
        self.feature_name = spec.name
        self.infer_dict = infer_dict                    # Consumer通往Worker的入口
        self.result_queue = result_queue
        self.latest_frames = latest_frames
        self.latest_frame_times = latest_frame_times if latest_frame_times is not None else {}
        self.is_camera_active = is_camera_active
        self.runtime_alert_handler = runtime_alert_handler                # Runtime监控监控（两种告警处理：业务告警核系统运行异常）
        self.result_router = InferenceResultRouter(
            result_queue, self.feature_name,
            on_failure=lambda detail: self._notify_runtime_alert("推理结果路由异常", detail),
        )
        self._lifecycle_lock = threading.Lock()
        # 只串行化注册和短时投递，等待结果不持锁；停止也通过此门控关闭投递。
        self._inference_submission_lock = threading.Lock()
        self.inference_outcome_counts: dict[str, int] = defaultdict(int)  # 整个功能各种推理结果累计多少次
        # key是(model_name, camera_id)，统计当前摄像头调用模型的结果
        self._inference_outcome_counts_by_target: dict[tuple[str, int], dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # 连续失败多少次
        self._inference_consecutive_failures: dict[tuple[str, int], int] = defaultdict(int)
        # 最近一次推理状态
        self._inference_last_status: dict[tuple[str, int], dict] = {}
        # 最近一次异常通知时间
        self._inference_last_alert_at: dict[tuple[str, int], float] = {}
        self._last_frame_timings: dict[int, dict] = {}
        self._last_frame_started_at: dict[int, float] = {}
        # 读或改inference status时加锁
        self._inference_status_lock = threading.Lock()
        # RLock允许同一个线程重复进入
        self._camera_state_lock = threading.RLock()

        # ---- 配置与帧缓存（以 camera_id 为索引）----
        self.config_cache: dict[int, dict] = {}        # 运行时功能配置快照
        self.frame_cache: dict[int, np.ndarray] = {}   # 最近一帧，供告警截图使用

        # ---- ROI 状态（按摄像头隔离）----
        self._roi_polygon_cache: dict[int, np.ndarray] = {}  # 每台摄像头的一个像素多边形
        self._masks: dict[int, tuple[np.ndarray, int, int, int, int]] = {}               # 预计算的裁剪掩码
        self._masks_roi_input: dict[int, list] = {}     # 上次生成掩码时的 roi_pos 输入，用于检测配置变更
        self._masks_frame_shape: dict[int, tuple[int, int]] = {}  # 掩码对应的帧高宽
        self.pre_roi: dict[int, np.ndarray] = {}              # 最近一次显著变化的原始 ROI
        self.blur_roi: dict[int, np.ndarray] = {}  # 高斯模糊缓存，加速帧差计算
        self.frame_change_samples: dict[int, np.ndarray] = {}  # 低分辨率帧差缓存

        # ---- 输出帧（Orchestrator 通过此字典向 API/前端提供预览帧）----
        self.result_dict: dict[str, np.ndarray] = {}       # {shm_name: 带标注帧}
        self.result_updated_at: dict[str, float] = {}      # {shm_name: 更新时间戳}
        self._preview_frames: dict[str, AnnotatedPreviewFrame] = {}
        self._frame_sampled_at: dict[int, float] = {}
        self._monitor_results: dict[str, dict] = {}

        self._last_process_at: dict[int, float] = {}        # 上次处理时间戳，配合 cap_interval 限频

        self.running = False
        self._thread: Optional[threading.Thread] = None

    #  生命周期
    def start(self):
        """
        启动 Consumer 守护线程。

        启动前先加载初始配置，确保主循环第一帧就能正常处理。
        """
        with self._lifecycle_lock:
            if self.running:
                return
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Consumer 上一处理线程尚未退出，不能重复启动")
            self._load_initial_configs()
            with self._inference_submission_lock:
                self.result_router.start()
                self.running = True
                self._thread = threading.Thread(target=self._run, name=f"consumer-{self.feature_name}", daemon=True)
                try:
                    self._thread.start()
                except Exception:
                    self.running = False
                    self._thread = None
                    self.result_router.stop()
                    raise
        logger.info(
            f"[{self.feature_name}] Consumer 已启动，监控 {len(self.config_cache)} 个摄像头"
        )

    def stop(self):
        """先关闭投递并唤醒推理等待者，再回收处理线程。"""
        with self._lifecycle_lock:
            with self._inference_submission_lock:
                self.running = False
                self.result_router.stop()
            if self._thread is not None:
                self._thread.join(timeout=_CONSUMER_STOP_TIMEOUT_SECONDS)
                if self._thread.is_alive():
                    raise RuntimeError("Consumer 处理线程停止超时")
                self._thread = None
            self._preview_frames.clear()
            self._monitor_results.clear()
        logger.info(f"[{self.feature_name}] Consumer 已停止")

    def _load_initial_configs(self):
        """
        从全局缓存加载本 feature 已启用的所有摄像头配置。

        仅加载 enable=True 的配置；未启用的摄像头不进入主循环。
        """
        with self._camera_state_lock:
            for (camera_id, fname), cfg in config_cache.get_all_function_configs().items():
                if fname == self.feature_name and cfg.get("enable"):
                    self.config_cache[camera_id] = cfg

    #  配置变更回调（由 Orchestrator 路由事件触发）

    def update_config(self, camera_id: int):
        """
        热更新指定摄像头的功能配置。

        同时清除 ROI 相关缓存，确保下一帧使用新配置重建掩码，
        避免旧 ROI 与新配置不匹配导致错误检测。
        """
        with self._camera_state_lock:
            previous = self.config_cache.get(camera_id)
            if previous:
                self._preview_frames.pop(previous["shm_name"], None)
                self._monitor_results.pop(previous["shm_name"], None)
            # 从全局缓存中取最新版
            cfg = config_cache.get_function_config(camera_id, self.feature_name)
            if cfg and cfg.get("enable"):
                # 在替换配置前清理旧主体，包含已删除或重命名的 ROI。
                self._reset_alarm_cooldown(camera_id)
                # 覆盖Consumer自己的旧快照（热更新，不重启Consumer)
                self.config_cache[camera_id] = cfg
            else:
                # 未绑定该功能的摄像头不能因参数热更新重新进入 Consumer 主循环。
                self.update_status(camera_id, False)
            # 清除 ROI 缓存，下轮迭代时按新配置重建
            self._masks.pop(camera_id, None)
            self._masks_roi_input.pop(camera_id, None)
            self._masks_frame_shape.pop(camera_id, None)
            self._roi_polygon_cache.pop(camera_id, None)

    def update_status(self, camera_id: int, enabled: bool):
        """
        响应摄像头功能启用/禁用事件。

        启用时：从缓存拉取最新配置加入监控列表。
        禁用时：从监控列表移除，并清理输出帧字典，避免 API 继续返回过期画面。
        """
        with self._camera_state_lock:
            previous = self.config_cache.get(camera_id)
            if previous:
                self._preview_frames.pop(previous["shm_name"], None)
                self._monitor_results.pop(previous["shm_name"], None)
            cfg = (
                config_cache.get_function_config(camera_id, self.feature_name)
                if enabled
                else None
            )
            if enabled and cfg and cfg.get("enable"):
                self.config_cache[camera_id] = cfg
            else:
                cached_cfg = self.config_cache.pop(camera_id, None)
                cam_name = (cached_cfg or cfg or {}).get("shm_name")
                if cam_name:
                    # 关闭了必须清掉过期预览帧
                    self.result_dict.pop(cam_name, None)
                    self.result_updated_at.pop(cam_name, None)

    def remove_camera(self, camera_id: int, shm_name: str | None = None):
        """等待当前帧处理结束，再清除该摄像头持有的全部状态。"""
        with self._camera_state_lock:
            cfg = self.config_cache.get(camera_id) or {}
            camera_key = cfg.get("shm_name") or shm_name
            self.update_status(camera_id, False)
            self._clear_camera_state(camera_id, camera_key)                   # 这台camera在这个Consumer内所有痕迹全部清掉
            self._reset_alarm_cooldown(camera_id)

    def _reset_alarm_cooldown(self, camera_id: int):
        """重置本功能在指定摄像头上的所有告警类型冷却状态。"""
        for violation_type in self.spec.alarm_types:
            alarm_dispatcher.reset_cooldown(camera_id, violation_type)

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        """
        把所有以camera_id为key的缓存全部pop,包括：
            frame_cache
            ROI cache
            mask
            frame difference cache
            last process time
            result_dict[shm_name]
            result_updated_at[shm_name]
        """
        for cache in (
            self.frame_cache, self._roi_polygon_cache, self._masks,
            self._masks_roi_input, self._masks_frame_shape, self.pre_roi,
            self.blur_roi, self.frame_change_samples, self._last_process_at,
            self._frame_sampled_at,
        ):
            cache.pop(camera_id, None)
        if shm_name:
            self.result_dict.pop(shm_name, None)
            self.result_updated_at.pop(shm_name, None)
            self._preview_frames.pop(shm_name, None)
            self._monitor_results.pop(shm_name, None)
        with self._inference_status_lock:
            self._last_frame_timings.pop(camera_id, None)
            self._last_frame_started_at.pop(camera_id, None)
            for cache in (
                self._inference_outcome_counts_by_target, self._inference_consecutive_failures,
                self._inference_last_status, self._inference_last_alert_at,
            ):
                for key in [key for key in cache if key[1] == camera_id]:
                    cache.pop(key, None)

    #  主循环
    def _run(self):
        """
        Consumer 主循环，每轮 sleep 50ms（约 20fps 上限），流程如下:
            1. 遍历所有已启用摄像头：读帧 → 裁 ROI → 跳帧判断 → 业务处理。
            2. 更新输出帧，触发告警分发。

        跳帧策略（满足任一条件才处理）：
            - 画面有显著变化（_frame_changed 返回 True）。
            - 子类声明需处理静止帧（_process_static_frames 返回 True）
              且距上次处理已超过 cap_interval。
        """
        while self.running:
            try:
                self._before_camera_round()
                # 遍历所有的摄像头
                for cam_id in list(self.config_cache.keys()):
                    if not self.running:
                        break
                    frame_started_at = time.monotonic()
                    with self._camera_state_lock:
                        state_locked_at = time.monotonic()
                        cfg = self.config_cache.get(cam_id, {})
                        cam_name = cfg.get("shm_name")
                        if not cam_name or not self.is_camera_active(cam_name):
                            continue

                        read_started_at = time.monotonic()
                        frame, sampled_at = self._processing_frame(cam_id, cam_name)
                        frame_ready_at = time.monotonic()
                        if frame is None:
                            continue

                        if not self._should_process_now(cam_id, cfg):
                            continue

                        self.frame_cache[cam_id] = frame  # 缓存供告警截图使用
                        self._frame_sampled_at[cam_id] = sampled_at

                        roi = self._get_roi(cam_id, frame)
                        frame_changed = self._frame_changed(cam_id, roi)
                        now = time.time()
                        cap_interval = self._processing_interval_seconds(cam_id, cfg)
                        if cap_interval is None:
                            continue
                        due_by_interval = now - self._last_process_at.get(cam_id, 0.0) >= cap_interval

                        # 跳帧：画面无变化 且 不需要处理静止帧（或未到采集间隔）
                        if not frame_changed and not (
                            # 子类是否要求静止画面也继续处理？如果_process_static_frames() == False就跳过
                            self._process_static_frames(camera_id=cam_id, cfg=cfg) and due_by_interval
                        ):
                            continue
                        # 真正进入子类业务
                        process_started_at = time.monotonic()
                        result = self._process(roi, cam_id)
                        processed_at = time.monotonic()
                        # 更新最后处理时间
                        self._last_process_at[cam_id] = now
                        # 子类负责画检测框、画ROI、写人数、写状态文字
                        annotated = self.post_process(cam_id, result)
                        annotated_at = time.monotonic()
                        # 保存前端预览
                        self.result_dict[cam_name] = annotated
                        # 保存更新时间
                        self.result_updated_at[cam_name] = time.time()
                        if annotated is not None:
                            self._preview_frames[cam_name] = AnnotatedPreviewFrame(
                                annotated, self._frame_sampled_at[cam_id], cfg,
                            )
                        else:
                            self._preview_frames.pop(cam_name, None)
                        # _process：得到业务结果，post_process:得到标注画面，_handle_alarm:决定是否发AlarmRequest
                        self._handle_alarm(cam_id, result, annotated)
                        monitor = self._build_monitor_snapshot(cam_id, result)
                        if monitor is not None:
                            self._monitor_results[cam_name] = {
                                **monitor,
                                "updated_at_s": self._frame_sampled_at[cam_id],
                            }
                        published_at = time.monotonic()
                    self._after_process(cam_id, result)
                    finished_at = time.monotonic()
                    self._record_frame_timing(cam_id, {
                        "start": frame_started_at,
                        "lock_wait": state_locked_at,
                        "state_check": read_started_at,
                        "frame_read": frame_ready_at,
                        "prepare": process_started_at,
                        "process": processed_at,
                        "post_process": annotated_at,
                        "publish_alarm": published_at,
                        "after_process": finished_at,
                    })

                time.sleep(0.05)
            except Exception:
                logger.exception(f"[{self.feature_name}] 主循环异常")
                self._notify_runtime_alert("功能主循环异常", "Consumer 主循环捕获异常,已继续运行")
                time.sleep(0.5)  # 异常后短暂等待，避免日志刷屏

    def _after_process(self, camera_id: int, result: tuple):
        """状态锁释放后执行；异步功能可在此提交任务，避免拒绝回调在锁内执行。"""

    def _build_monitor_snapshot(self, camera_id: int, result: tuple) -> dict | None:
        """子类按业务结果提供监控数据，不从历史报警或标注图片推断当前判定。"""
        return None

    def get_monitor_status(self, camera_key: str) -> dict | None:
        """只读取原子替换的结果快照，避免取状态时等待当前摄像头推理。"""
        snapshot = self._monitor_results.get(camera_key)
        return dict(snapshot) if snapshot else None

    def _before_camera_round(self) -> None:
        """轮询摄像头前的扩展点，允许需要连续跟踪的功能提前投递有界请求。"""

    def _processing_frame(self, camera_id: int, camera_key: str) -> tuple[np.ndarray | None, float]:
        """读取本次业务处理所用的画面及其采集时间。"""
        return self.latest_frames.get(camera_key), self.latest_frame_times.get(camera_key, time.time())

    def _record_frame_timing(self, camera_id: int, stages: dict[str, float]) -> None:
        """保存最近完整处理帧的分段耗时和实际间隔，不保留图像或历史样本。"""
        started_at = previous_at = stages["start"]
        timing = {"updated_at": time.time()}
        for name, completed_at in stages.items():
            if name != "start":
                timing[f"{name}_ms"] = round(max(0.0, completed_at - previous_at) * 1000, 3)
            previous_at = completed_at
        timing["total_ms"] = round(max(0.0, previous_at - started_at) * 1000, 3)
        with self._inference_status_lock:
            # 删除摄像头可能发生在锁外回调期间，不能重新建立已清理的统计。
            if camera_id not in self.config_cache:
                return
            last_started_at = self._last_frame_started_at.get(camera_id)
            timing["interval_ms"] = (
                round(max(0.0, started_at - last_started_at) * 1000, 3)
                if last_started_at is not None else None
            )
            self._last_frame_started_at[camera_id] = started_at
            self._last_frame_timings[camera_id] = timing

    #  抽象方法（子类必须实现）
    @abstractmethod
    def _process(self, roi: np.ndarray, camera_id: int) -> tuple[bool, object]:
        """
        核心业务处理，接收唯一的 ROI 裁剪图，返回当前摄像头的判定结果。

        Returns:
            (is_alarm, detail_dict)：
                is_alarm   — 该 ROI 是否触发告警。
                detail_dict— 可视化或日志所需的业务细节（由子类定义结构）。
        """
    @abstractmethod
    def post_process(self, camera_id: int, result: tuple) -> np.ndarray:
        """
        在原始帧上叠加检测结果的可视化标注（边框、标签、热区等）。

        Returns:
            带标注的 BGR 图像帧，写入 result_dict 后供前端预览。
        """
    def _notify_runtime_alert(
        self,
        event_type: str,
        detail: str,
        *,
        target_name: str | None = None,
        target_key: str | None = None,
    ):
        """通过后台线程发送运行状态通知，避免通知服务阻塞检测循环。"""
        handler = self.runtime_alert_handler
        if handler is None:
            return

        def _send():
            """调用运行状态处理器，并记录通知失败而不影响业务检测。"""
            try:
                handler(
                    target_name or self.feature_name,
                    target_key or self.feature_name,
                    event_type,
                    detail,
                )
            except Exception as e:
                logger.warning(f"[{self.feature_name}] 功能异常企微推送失败: {e}")

        threading.Thread(
            target=_send,
            daemon=True,
            name=f"feature-runtime-alert-{self.feature_name}",
        ).start()

    def _record_inference_outcomes(
        self,
        *,
        camera_id: int,
        model_name: str,
        outcomes: list[dict],
    ) -> None:
        """按模型和摄像头记录结果；连续异常达到阈值时发送一次限频告警。"""
        if not outcomes:
            return

        target = (model_name, camera_id)
        now = time.monotonic()
        failures = [
            outcome
            for outcome in outcomes
            if str(outcome.get("status") or INFERENCE_STATUS_OK) in INFERENCE_FAILURE_STATUSES
        ]
        alert_payload: tuple[int, dict[str, int]] | None = None

        with self._inference_status_lock:
            target_counts = self._inference_outcome_counts_by_target[target]
            for outcome in outcomes:
                status = str(outcome.get("status") or INFERENCE_STATUS_OK)
                self.inference_outcome_counts[status] += 1
                target_counts[status] += 1

            last_outcome = failures[-1] if failures else outcomes[-1]
            self._inference_last_status[target] = {
                "status": str(last_outcome.get("status") or "unknown") if failures else INFERENCE_STATUS_OK,
                "error_code": last_outcome.get("error_code") if failures else None,
                "updated_at": time.time(),
                "timing_ms": {
                    "input_wait": last_outcome.get("input_wait_ms"),
                    "worker": last_outcome.get("inference_ms"),
                    "result_return": last_outcome.get("result_return_ms"),
                    "round_trip": last_outcome.get("round_trip_ms"),
                },
            }
            if not failures:
                self._inference_consecutive_failures[target] = 0
                return

            consecutive = self._inference_consecutive_failures[target] + 1
            self._inference_consecutive_failures[target] = consecutive
            failure_counts: dict[str, int] = defaultdict(int)
            for outcome in failures:
                failure_counts[str(outcome.get("status") or "unknown")] += 1

            threshold = settings.runtime.inference_alert_consecutive_failures
            last_alert_at = self._inference_last_alert_at.get(target)
            cooldown = settings.runtime.inference_alert_cooldown_seconds
            if (
                consecutive >= threshold
                and (last_alert_at is None or now - last_alert_at >= cooldown)
            ):
                self._inference_last_alert_at[target] = now
                alert_payload = consecutive, dict(failure_counts)

        if alert_payload is None:
            return
        consecutive, failure_counts = alert_payload
        camera_name = str(self.config_cache.get(camera_id, {}).get("name") or camera_id)
        detail = (
            f"模型 {model_name} 在摄像头 {camera_name} 连续 {consecutive} 次推理未完整成功，"
            f"本次状态统计: {failure_counts}"
        )
        logger.warning(f"[{self.feature_name}] {detail}")
        self._notify_runtime_alert(
            "推理连续异常",
            detail,
            target_name=f"{self.feature_name}/{model_name}/{camera_name}",
            target_key=f"{self.feature_name}:{model_name}:{camera_id}",
        )

    def inference_status(self) -> dict:
        """返回可序列化的推理结果统计快照，供运行状态接口使用。"""
        with self._inference_status_lock:
            targets = []
            for (model_name, camera_id), counts in sorted(
                self._inference_outcome_counts_by_target.items(),
                key=lambda item: (item[0][0], item[0][1]),
            ):
                last_outcome = dict(self._inference_last_status.get((model_name, camera_id), {}))
                if "timing_ms" in last_outcome:
                    last_outcome["timing_ms"] = dict(last_outcome["timing_ms"])
                targets.append({
                    "model_name": model_name,
                    "camera_id": camera_id,
                    "counts": dict(counts),
                    "consecutive_failures": self._inference_consecutive_failures.get(
                        (model_name, camera_id),
                        0,
                    ),
                    "last_outcome": last_outcome,
                    "last_frame_timing": dict(self._last_frame_timings.get(camera_id, {})),
                })
            return {
                "totals": dict(self.inference_outcome_counts),
                "targets": targets,
            }

    #  告警处理
    def _handle_alarm(self, camera_id: int, result: tuple, frame: np.ndarray, *, config: dict | None = None,
                      channels: set[str] | None = None, on_horn_complete: Callable[[bool], None] | None = None):
        """
        判定是否触发告警，并通过 alarm_dispatcher 分发到各通道。

        将数据库扁平字段（sql_enable、horn_enable 等）重组为
        alarm_dispatcher 期望的嵌套 alarm_config 结构，
        避免在每个子类中重复此转换逻辑。
        异步结果通过 config 传入已校验的配置快照。
        """
        cfg = self.config_cache.get(camera_id, {}) if config is None else config
        if not self._should_alarm(camera_id, result, cfg):
            return

        cam_key = cfg.get("shm_name", "")
        cam_name = cfg.get("name") or cam_key
        department = cfg.get("department")
        try:
            require_department(department)
        except ValueError:
            logger.error(f"[{self.feature_name}] 摄像头所属事业部/公司无效，跳过业务告警 camera_id={camera_id} department={department!r}")
            return

        # 将 ORM 扁平字段重组为 AlarmDispatcher 期望的嵌套结构
        alarm_config = {
            "sql": {
                "enable": cfg.get("sql_enable", False),
                "parm": {},
            },
            "horn": {
                "enable": cfg.get("horn_enable", False),
                "interval": cfg.get("horn_interval"),
                "parm": {
                    "horn_id":       cfg.get("horn_id"),
                    "horn_event_id": cfg.get("horn_event_id"),
                },
            },
            "wechat": {
                "enable": cfg.get("wechat_enable", False),
                "interval": cfg.get("wechat_interval"),
                "parm": {"user": cfg.get("wechat_user", "")},
            },
        }

        alarm_context = {
            "cooldown_subject_type": "camera",
            "cooldown_subject_id": str(camera_id),
            **self._alarm_context(camera_id, result),
        }
        return alarm_dispatcher.maybe_dispatch(
            AlarmRequest(
                feature_name=self.feature_name,
                camera_id=camera_id,
                camera_name=cam_name,
                # frame 优先用带标注帧，fallback 到原始帧缓存
                frame=frame if frame is not None else self.frame_cache.get(camera_id),
                violation_type=self._alarm_violation_type(camera_id, result, cfg),
                alarm_config=alarm_config,
                camera_key=cam_key,
                department=department,
                on_horn_complete=on_horn_complete,
                **alarm_context,
            ),
            alarm_interval=cfg["alarm_interval"],
            **({"channels": channels} if channels is not None else {}),
        )

    def _alarm_violation_type(self, camera_id: int, result: tuple, cfg: dict) -> int:
        """单报警功能直接使用唯一类型，复合功能必须明确选择本次报警类型。"""
        if len(self.spec.alarm_types) != 1:
            raise RuntimeError(
                f"[{self.feature_name}] alarm_types 数量不是 1，复合 Feature 必须覆盖 "
                "_alarm_violation_type 明确选择报警类型"
            )
        (violation_type,) = self.spec.alarm_types
        return violation_type

    def _alarm_context(self, camera_id: int, result: tuple) -> dict:
        """报警后调用；子类可指定业务主体、cooldown_subject_type/id、原因和元数据。"""
        return {}

    def _should_alarm(self, camera_id: int, result: tuple, cfg: dict) -> bool:
        """当前摄像头唯一 ROI 的判定；冷却由 AlarmDispatcher 处理。"""
        return bool(result[0])

    def _processing_interval_seconds(self, camera_id: int, cfg: dict) -> float | None:
        """普通功能使用逐路间隔；通道功能可覆盖，返回 None 表示本轮不处理。"""
        return float(cfg["cap_interval"])

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """声明是否继续处理静止画面，默认关闭，由需要连续计时的子类覆盖。"""
        return False

    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        """控制当前摄像头本轮是否进入检测流程，默认不做时间限制。"""
        return True

    # ROI：一台摄像头只有一个归一化多边形。
    def _get_roi(self, camera_id: int, frame: np.ndarray) -> np.ndarray:
        """按当前实际帧尺寸恢复像素 ROI，返回唯一的 Mask 裁剪图。"""
        value = self.config_cache[camera_id]
        points = value.get("roi_pos", [])
        frame_shape = tuple(frame.shape[:2])
        if (
            camera_id not in self._masks
            or self._masks_roi_input.get(camera_id) != points
            or self._masks_frame_shape.get(camera_id) != frame_shape
        ):
            polygon = roi_to_pixels(points, frame.shape)
            x_min, y_min = polygon.min(axis=0)
            x_max, y_max = polygon.max(axis=0)
            if x_max <= x_min or y_max <= y_min:
                raise ValueError(f"摄像头 {camera_id} 的 ROI 在当前帧尺寸下没有有效面积")
            mask = np.zeros((y_max - y_min, x_max - x_min), dtype=np.uint8)
            cv2.fillPoly(mask, [polygon - [x_min, y_min]], 255)
            self._on_roi_changed(camera_id)
            self._masks[camera_id] = (mask, int(y_min), int(y_max), int(x_min), int(x_max))
            self._masks_roi_input[camera_id] = [list(point) for point in points]
            self._masks_frame_shape[camera_id] = frame_shape
            self._roi_polygon_cache[camera_id] = polygon
        mask, y_min, y_max, x_min, x_max = self._masks[camera_id]
        cropped = frame[y_min:y_max, x_min:x_max]
        return cv2.bitwise_and(cropped, cropped, mask=mask)

    def _on_roi_changed(self, camera_id: int) -> None:
        """坐标或帧尺寸变化时，清除依赖旧裁剪坐标的状态。"""
        self.pre_roi.pop(camera_id, None)
        self.blur_roi.pop(camera_id, None)
        self.frame_change_samples.pop(camera_id, None)

    def _get_roi_offset(self, camera_id: int) -> tuple[int, int]:
        """唯一 ROI 的左上角偏移，用于把检测框恢复到原始帧。"""
        bounds = self._masks.get(camera_id)
        return (bounds[3], bounds[1]) if bounds is not None else (0, 0)

    def _annotated_frame(self, camera_id: int) -> np.ndarray | None:
        """所有普通 Feature 统一先在原始帧副本绘制 ROI，再绘制业务标注。"""
        frame = self.frame_cache.get(camera_id)
        if frame is None:
            return None
        points = self.config_cache[camera_id].get("roi_pos", [])
        return annotate_roi(frame, points, self.ROI_COLOR)

    def _preview_source(self, camera_id: int) -> DetectionPreviewFrame:
        """预览沿用实际输入帧的时间，推理完成不会让旧画面重新变新。"""
        return DetectionPreviewFrame(
            self.frame_cache[camera_id],
            self._frame_sampled_at.get(camera_id, self._last_process_at.get(camera_id, 0.0)),
        )

    def _preview_background(self, frame: np.ndarray, cfg: dict) -> np.ndarray:
        """普通检测使用已保存的单 ROI；多工位等功能覆盖此绘图方法。"""
        return annotate_roi(frame, cfg.get("roi_pos", []), self.ROI_COLOR)

    def get_live_preview(self, camera_key: str, frame: np.ndarray, *, now: float):
        """取图不等待推理锁，旧检测超出显示延迟后只在最新视频绘制静态 ROI。"""
        if not self.running:
            return None
        # 配置以整份字典替换；浅复制映射并复核引用，无需等待正在推理的摄像头状态锁。
        match = next(((camera_id, cfg) for camera_id, cfg in self.config_cache.copy().items()
                      if cfg.get("shm_name") == camera_key), None)
        if match is None:
            return None
        camera_id, cfg = match
        if not cfg.get("enable") or not cfg.get("camera_enable", True):
            return None
        snapshot = self._preview_frames.get(camera_key)
        if (snapshot is not None and snapshot.config is cfg
                and snapshot.usable(frame, now=now, max_age=PREVIEW_FRAME_MAX_AGE_SECONDS)):
            rendered = snapshot.frame
        else:
            rendered = self._preview_background(frame, cfg)
        return rendered if self.running and self.config_cache.get(camera_id) is cfg else None

    def _frame_changed(self, camera_id: int, roi: np.ndarray, threshold: float = 0.005) -> bool:
        """单 ROI 下采样帧差；显著变化时更新供门检测使用的完整模糊帧。"""
        sample = self._frame_change_sample(roi)
        previous = self.frame_change_samples.get(camera_id)
        if previous is None or previous.shape != sample.shape:
            changed = True
        else:
            changed = float(cv2.absdiff(sample, previous).mean()) / 255.0 > threshold
        if changed:
            self.frame_change_samples[camera_id] = sample
            self.blur_roi[camera_id] = cv2.GaussianBlur(roi, _FRAME_CHANGE_BLUR_KERNEL, 0)
            self.pre_roi[camera_id] = roi
        return changed

    @staticmethod
    def _frame_change_sample(roi: np.ndarray) -> np.ndarray:
        """先 4 倍下采样再模糊，生成仅用于快速帧差判断的小图。"""
        sampled = np.ascontiguousarray(roi[::_FRAME_CHANGE_SAMPLE_STEP, ::_FRAME_CHANGE_SAMPLE_STEP])
        return cv2.GaussianBlur(sampled, _FRAME_CHANGE_BLUR_KERNEL, 0)

    # ------------------------------------------------------------------ #
    #  推理调度
    def dispatch_inference_sync(
        self,
        camera_id: int,
        model_name: str,
        roi: np.ndarray,
        task_meta: Optional[dict] = None,
        timeout: float = _INFERENCE_TIMEOUT_SECONDS,
    ) -> dict:
        """投递并等待匹配结果，沿用统一错误状态、计时和请求清理。"""
        request = self.submit_inference(camera_id, model_name, roi, task_meta, timeout)
        return self.resolve_inference(request)

    def submit_inference(
        self,
        camera_id: int,
        model_name: str,
        roi: np.ndarray,
        task_meta: Optional[dict] = None,
        timeout: float = _INFERENCE_TIMEOUT_SECONDS,
    ) -> SubmittedInference:
        """先登记再投递，不等待结果；YOLO 大图在进入进程队列前缩小。

        调用方必须 resolve 或 cancel；单次等待预算从投递准备开始计算，
        多路请求不能逐个重新累积完整超时。
        """
        import queue as _q

        started_at = time.monotonic()
        request = SubmittedInference(camera_id, model_name, started_at, started_at + timeout)
        request_id = f"{self.feature_name}:{camera_id}:{uuid4().hex}"
        task = {
            **(task_meta or {}),
            "roi_id": 0,
            "camera_id": camera_id,
            "frame": roi,
            "function_name": self.feature_name,
            "request_id": request_id,
            "model_name": model_name,
            "deadline_at_monotonic": request.deadline_at,
        }
        if model_name not in self.infer_dict:
            request.result = build_inference_result(
                task, status=INFERENCE_STATUS_UNAVAILABLE,
                error_code=INFERENCE_ERROR_UNAVAILABLE,
                error_message=f"模型未注册: {model_name}",
            )
        else:
            task = prepare_inference_task(task)
            try:
                with self._inference_submission_lock:
                    pending = request.pending = self.result_router.register(task)
                    if not pending.event.is_set():
                        try:
                            # 必须先注册再投递，结果可能在 put 返回前到达。
                            task["submitted_at_monotonic"] = time.monotonic()
                            self.infer_dict[model_name].put(task, timeout=0.02)
                        except _q.Full:
                            request.result = build_inference_result(
                                task, status=INFERENCE_STATUS_DROPPED,
                                error_code=INFERENCE_ERROR_QUEUE_FULL, error_message="模型推理队列已满",
                            )
            except Exception:
                if request.pending is not None:
                    self.result_router.unregister(request.pending)
                raise
        return request

    def resolve_inference(self, request: SubmittedInference) -> dict:
        """等待请求剩余时间，统一校验结果并注销登记、更新计时和健康统计。"""
        try:
            if request.result is not None:
                result = request.result
            elif request.pending is not None:
                result = self.result_router.wait(
                    request.pending, max(0.0, request.deadline_at - time.monotonic()),
                )
            else:
                raise RuntimeError("推理请求缺少结果与等待对象")
            if (
                result.get("status") not in (INFERENCE_STATUS_OK, *INFERENCE_FAILURE_STATUSES)
                or not isinstance(result.get("detections"), list)
            ):
                result = build_inference_result(
                    result, status=INFERENCE_STATUS_ERROR,
                    error_code=INFERENCE_ERROR_INVALID_RESULT,
                    error_message="推理结果必须包含明确的 status 和 detections 列表",
                )
        finally:
            if request.pending is not None:
                self.result_router.unregister(request.pending)
        returned_at = time.monotonic()
        result["round_trip_ms"] = round(max(0.0, returned_at - request.started_at) * 1000, 3)
        completed_at = result.get("completed_at_monotonic")
        result["result_return_ms"] = (
            round(max(0.0, returned_at - completed_at) * 1000, 3)
            if isinstance(completed_at, (int, float)) else None
        )
        self._record_inference_outcomes(
            camera_id=request.camera_id, model_name=request.model_name, outcomes=[result],
        )
        return result

    def cancel_inference(self, request: SubmittedInference) -> None:
        """撤销已失效请求的登记，迟到结果由路由器丢弃，不交给下一帧使用。"""
        identity = request.result or {}
        if request.pending is not None:
            identity = request.pending.identity
            self.result_router.unregister(request.pending)
        request.result = build_inference_result(
            identity, status=INFERENCE_STATUS_UNAVAILABLE,
            error_code=INFERENCE_ERROR_UNAVAILABLE, error_message="推理请求已取消",
        )
