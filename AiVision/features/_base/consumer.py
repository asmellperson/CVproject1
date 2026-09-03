# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/_base/consumer.py
功能消费者基类 — 业务逻辑处理框架。

继承本类的子类只需实现 3 个方法:
    _process(roi_list, camera_id) → list[(is_alarm, msg_dict)]
    post_process(camera_id, result) → annotated_frame
    (可选) _should_alarm(...) — 仅 detect_door 需要(双阶段告警)

通用部分(帧读取、ROI 裁剪、相似帧跳过、告警分发)由本类提供。
"""
from __future__ import annotations
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Callable, Optional

import cv2
import numpy as np

from AiVision.core.cache import config_cache
from AiVision.core.logger import logger
from AiVision.core.alarm.dispatcher import alarm_dispatcher, AlarmRequest
from AiVision.core.settings import settings
from AiVision.features._base.spec import FeatureSpec
from AiVision.platform.inference.contracts import (
    INFERENCE_ERROR_QUEUE_FULL,
    INFERENCE_ERROR_TIMEOUT,
    INFERENCE_ERROR_UNAVAILABLE,
    INFERENCE_FAILURE_STATUSES,
    INFERENCE_STATUS_DROPPED,
    INFERENCE_STATUS_OK,
    INFERENCE_STATUS_TIMEOUT,
    INFERENCE_STATUS_UNAVAILABLE,
    build_inference_result,
)


_FRAME_CHANGE_SAMPLE_STEP = 4
_FRAME_CHANGE_BLUR_KERNEL = (5, 5)


# 功能：所有功能消费者的基类，每个功能对应一个独立的 Consumer 线程；输入与输出详见下方说明
# 参数：
#   - `spec`（FeatureSpec）：`spec` 对应的业务输入值
#   - `infer_dict`（dict）：`infer_dict` 对应的业务输入值
#   - `result_queue`（未显式标注）：`result_queue` 对应的业务输入值
#   - `latest_frames`（dict[str, np.ndarray]）：`latest_frames` 对应的业务输入值
#   - `is_camera_active`（未显式标注）：`is_camera_active` 对应的业务输入值
#   - `runtime_alert_handler`（Callable[[str, str, str, str], None] | None）：`runtime_alert_handler` 对应的回调处理器；默认值为 `None`
# 返回：BaseFunctionConsumer；返回新建的 `BaseFunctionConsumer` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class BaseFunctionConsumer(ABC):
    """
    所有功能消费者的基类，每个功能对应一个独立的 Consumer 线程。

    职责划分:
        本类负责  — 帧读取、ROI 裁剪、相似帧跳过、告警分发、推理调度。
        子类负责  — _process()（业务推理）、post_process()（可视化标注）。

    扩展点:
        _should_alarm()       : 默认判定 result 中有 True 即告警，
                                detect_door 等双阶段场景可重写此方法。
        _process_static_frames(): 默认返回 False（帧差类功能依赖画面变化），
                                  YOLO 逗留检测类功能重写为 True 以持续累积时间。

    生命周期:
        Orchestrator 调用 start() → 内部加载配置并启动守护线程 _run()。
        配置变更时 Orchestrator 调用 update_config() / update_status() 热更新。
        进程退出时调用 stop()，守护线程随主进程自动回收。
    """

    # 功能：初始化或配置 `__init__` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `spec`（FeatureSpec）：`spec` 对应的业务输入值
    #   - `infer_dict`（dict）：`infer_dict` 对应的业务输入值
    #   - `result_queue`（未显式标注）：`result_queue` 对应的业务输入值
    #   - `latest_frames`（dict[str, np.ndarray]）：`latest_frames` 对应的业务输入值
    #   - `is_camera_active`（未显式标注）：`is_camera_active` 对应的业务输入值
    #   - `runtime_alert_handler`（Callable[[str, str, str, str], None] | None）：`runtime_alert_handler` 对应的回调处理器；默认值为 `None`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`defaultdict`、`threading.Lock`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源。
    def __init__(
        self,
        spec: FeatureSpec,
        infer_dict: dict,                          # {model_name: Queue}，推理调度入口
        result_queue,                               # 本 feature 接收推理结果的队列
        latest_frames: dict[str, np.ndarray],      # 由 CameraRuntimeManager 维护的最新帧字典
        is_camera_active,                           # callable(shm_name) -> bool，查询摄像头是否在线
        runtime_alert_handler: Callable[[str, str, str, str], None] | None = None,
    ):
        self.spec = spec
        self.feature_name = spec.name
        self.infer_dict = infer_dict
        self.result_queue = result_queue
        self.latest_frames = latest_frames
        self.is_camera_active = is_camera_active
        self.runtime_alert_handler = runtime_alert_handler
        self.inference_outcome_counts: dict[str, int] = defaultdict(int)
        self._inference_outcome_counts_by_target: dict[tuple[str, int], dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._inference_consecutive_failures: dict[tuple[str, int], int] = defaultdict(int)
        self._inference_last_status: dict[tuple[str, int], dict] = {}
        self._inference_last_alert_at: dict[tuple[str, int], float] = {}
        self._inference_status_lock = threading.Lock()

        # ---- 配置与帧缓存（以 camera_id 为索引）----
        self.config_cache: dict[int, dict] = {}        # 运行时功能配置快照
        self.frame_cache: dict[int, np.ndarray] = {}   # 最近一帧，供告警截图使用

        # ---- ROI 状态（按摄像头隔离）----
        self._roi_polygon_cache: dict[int, list] = {}   # 当前摄像头的多边形列表
        self._masks: dict[int, list] = {}               # 预计算的裁剪掩码
        self._masks_roi_input: dict[int, list] = {}     # 上次生成掩码时的 roi_pos 输入，用于检测配置变更
        self._masks_frame_shape: dict[int, tuple[int, int]] = {}  # 掩码对应的帧高宽
        self.pre_roi: dict[int, list] = {}              # 最近一次显著变化的原始 ROI
        self.blur_roi: dict[int, list[np.ndarray]] = defaultdict(list)  # 高斯模糊缓存，加速帧差计算
        self.frame_change_samples: dict[int, list[np.ndarray]] = {}  # 低分辨率帧差缓存

        # ---- 输出帧（Orchestrator 通过此字典向 API/前端提供预览帧）----
        self.result_dict: dict[str, np.ndarray] = {}       # {shm_name: 带标注帧}
        self.result_updated_at: dict[str, float] = {}      # {shm_name: 更新时间戳}

        # ---- 异步推理跟踪（detect_face 等异步 dispatch 场景使用）----
        self._pending_results: dict[int, list] = defaultdict(list)  # 已收到但未处理完的结果
        self._expected_roi_count: dict[int, int] = {}       # 每帧期望收到的结果数
        self._pending_timestamps: dict[int, float] = {}     # 异步任务投递时间，用于超时检测
        self._last_process_at: dict[int, float] = {}        # 上次处理时间戳，配合 cap_interval 限频

        self.running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    #  生命周期                                                             #
    # ------------------------------------------------------------------ #

    # 功能：启动 Consumer 守护线程；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._load_initial_configs`、`threading.Thread`、`self._thread.start`、`logger.info`、`len`。
    # 副作用/注意事项：会更新当前实例的运行状态；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def start(self):
        """
        启动 Consumer 守护线程。

        幂等：已运行时重复调用无副作用。
        启动前先加载初始配置，确保主循环第一帧就能正常处理。
        """
        if self.running:
            return
        self._load_initial_configs()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            f"[{self.feature_name}] Consumer 已启动，监控 {len(self.config_cache)} 个摄像头"
        )

    # 功能：通知主循环退出；守护线程会随主进程自动回收，无需 join；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
    def stop(self):
        """通知主循环退出；守护线程会随主进程自动回收，无需 join。"""
        self.running = False
        logger.info(f"[{self.feature_name}] Consumer 已停止")

    # 功能：从全局缓存加载本 feature 已启用的所有摄像头配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::start` 调用本符号
    #   - 内部调用：`config_cache.get_all_function_configs().items`、`config_cache.get_all_function_configs`、`cfg.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _load_initial_configs(self):
        """
        从全局缓存加载本 feature 已启用的所有摄像头配置。

        仅加载 enable=True 的配置；未启用的摄像头不进入主循环。
        """
        for (camera_id, fname), cfg in config_cache.get_all_function_configs().items():
            if fname == self.feature_name and cfg.get("enable"):
                self.config_cache[camera_id] = cfg

    # ------------------------------------------------------------------ #
    #  配置变更回调（由 Orchestrator 路由事件触发）                          #
    # ------------------------------------------------------------------ #

    # 功能：热更新指定摄像头的功能配置；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`config_cache.get_function_config`、`alarm_dispatcher.reset_cooldown`、`self._masks.pop`、`self._masks_roi_input.pop`、`self._masks_frame_shape.pop`、`self._roi_polygon_cache.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_config(self, camera_id: int):
        """
        热更新指定摄像头的功能配置。

        同时清除 ROI 相关缓存，确保下一帧使用新配置重建掩码，
        避免旧 ROI 与新配置不匹配导致错误检测。
        """
        cfg = config_cache.get_function_config(camera_id, self.feature_name)
        if cfg and cfg.get("enable"):
            self.config_cache[camera_id] = cfg
            alarm_dispatcher.reset_cooldown(camera_id, self.feature_name)
        else:
            # 未绑定该功能的摄像头不能因参数热更新重新进入 Consumer 主循环。
            self.update_status(camera_id, False)
        # 清除 ROI 缓存，下轮迭代时按新配置重建
        self._masks.pop(camera_id, None)
        self._masks_roi_input.pop(camera_id, None)
        self._masks_frame_shape.pop(camera_id, None)
        self._roi_polygon_cache.pop(camera_id, None)

    # 功能：响应摄像头功能启用/禁用事件；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `enabled`（bool）：是否启用相应能力
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`config_cache.get_function_config`、`self.config_cache.pop`、`(cfg or
    #          {}).get`、`self.result_dict.pop`、`self.result_updated_at.pop`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def update_status(self, camera_id: int, enabled: bool):
        """
        响应摄像头功能启用/禁用事件。

        启用时：从缓存拉取最新配置加入监控列表。
        禁用时：从监控列表移除，并清理输出帧字典，避免 API 继续返回过期画面。
        """
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
                self.result_dict.pop(cam_name, None)
                self.result_updated_at.pop(cam_name, None)

    # ------------------------------------------------------------------ #
    #  主循环                                                               #
    # ------------------------------------------------------------------ #

    # 功能：Consumer 主循环，每轮 sleep 50ms（约 20fps 上限），流程如下:；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._collect_async_results`、`list`、`self.config_cache.keys`、`self.config_cache[cam_id].get`、`self.is_camera_active`、`self.latest_frames.get`、`self.config_cache.get`、`self._should_process_now`、`self._get_roi`、`self._frame_changed`
    #          等共 22 个调用。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
    def _run(self):
        """
        Consumer 主循环，每轮 sleep 50ms（约 20fps 上限），流程如下:
            1. 收集已完成的异步推理结果。
            2. 遍历所有已启用摄像头：读帧 → 裁 ROI → 跳帧判断 → 业务处理。
            3. 更新输出帧，触发告警分发。

        跳帧策略（满足任一条件才处理）：
            - 画面有显著变化（_frame_changed 返回 True）。
            - 子类声明需处理静止帧（_process_static_frames 返回 True）
              且距上次处理已超过 cap_interval。
        """
        while self.running:
            try:
                self._collect_async_results()

                for cam_id in list(self.config_cache.keys()):
                    cam_name = self.config_cache[cam_id].get("shm_name")
                    if not cam_name or not self.is_camera_active(cam_name):
                        continue

                    frame = self.latest_frames.get(cam_name)
                    if frame is None:
                        continue

                    cfg = self.config_cache.get(cam_id, {})
                    if not self._should_process_now(cam_id, cfg):
                        continue

                    self.frame_cache[cam_id] = frame  # 缓存供告警截图使用

                    roi_list = self._get_roi(cam_id, frame)
                    frame_changed = self._frame_changed(cam_id, roi_list)
                    now = time.time()
                    cap_interval = float(self._value_config(cfg).get("cap_interval", 0.1) or 0.1)
                    due_by_interval = now - self._last_process_at.get(cam_id, 0.0) >= cap_interval

                    # 跳帧：画面无变化 且 不需要处理静止帧（或未到采集间隔）
                    if not frame_changed and not (
                        self._process_static_frames(camera_id=cam_id, cfg=cfg) and due_by_interval
                    ):
                        continue

                    result = self._process(roi_list, cam_id)
                    self._last_process_at[cam_id] = now
                    annotated = self.post_process(cam_id, result)
                    self.result_dict[cam_name] = annotated
                    self.result_updated_at[cam_name] = time.time()

                    self._handle_alarm(cam_id, result, annotated)

                time.sleep(0.05)
            except Exception:
                logger.exception(f"[{self.feature_name}] 主循环异常")
                self._notify_runtime_alert("功能主循环异常", "Consumer 主循环捕获异常,已继续运行")
                time.sleep(0.5)  # 异常后短暂等待，避免日志刷屏

    # ------------------------------------------------------------------ #
    #  抽象方法（子类必须实现）                                              #
    # ------------------------------------------------------------------ #

    # 功能：核心业务处理，接收裁剪后的 ROI 帧列表，返回每个 ROI 的判定结果；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `roi_list`（list[np.ndarray]）：`roi_list` 对应的业务输入值
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：list[tuple[bool, dict]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @abstractmethod
    def _process(self, roi_list: list[np.ndarray], camera_id: int) -> list[tuple[bool, dict]]:
        """
        核心业务处理，接收裁剪后的 ROI 帧列表，返回每个 ROI 的判定结果。

        Returns:
            list of (is_alarm, detail_dict)：
                is_alarm   — 该 ROI 是否触发告警。
                detail_dict— 可视化或日志所需的业务细节（由子类定义结构）。
        """

    # 功能：在原始帧上叠加检测结果的可视化标注（边框、标签、热区等）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `result`（list）：`result` 对应的业务输入值
    # 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @abstractmethod
    def post_process(self, camera_id: int, result: list) -> np.ndarray:
        """
        在原始帧上叠加检测结果的可视化标注（边框、标签、热区等）。

        Returns:
            带标注的 BGR 图像帧，写入 result_dict 后供前端预览。
        """

    # 功能：发送或分发 `_notify_runtime_alert` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `event_type`（str）：事件类型标识
    #   - `detail`（str）：`detail` 对应的业务输入值
    #   - `target_name`（str | None）：`target_name` 对应的业务输入值；默认值为 `None`
    #   - `target_key`（str | None）：`target_key` 对应的业务输入值；默认值为 `None`
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号；`AiVision/features/_base/consumer.py` 的
    #         `BaseFunctionConsumer::_record_inference_outcomes` 调用本符号
    #   - 内部调用：`threading.Thread(target=_send, daemon=True,
    #          name=f'feature-runtime-alert-{self.feature_name}').start`、`threading.Thread`。
    # 副作用/注意事项：可能发起网络请求或发送外部消息；可能启动、等待或停止线程/进程资源。
    def _notify_runtime_alert(
        self,
        event_type: str,
        detail: str,
        *,
        target_name: str | None = None,
        target_key: str | None = None,
    ):
        handler = self.runtime_alert_handler
        if handler is None:
            return

        # 功能：发送或分发 `_send` 对应的视频帧消费与检测逻辑；输入由参数提供，处理结果见返回值说明
        # 参数：无。
        # 返回：None；仅执行处理流程，不返回业务数据。
        # 调用关系：
        #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
        #   - 内部调用：`handler`、`logger.warning`。
        # 副作用/注意事项：会向日志系统输出运行或异常信息。
        def _send():
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

    # 功能：按模型和摄像头记录结果；连续异常达到阈值时发送一次限频告警；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `model_name`（str）：`model_name` 对应的业务输入值
    #   - `outcomes`（list[dict]）：`outcomes` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::dispatch_inference_sync`
    #         调用本符号；`AiVision/tests/test_inference_outcomes.py` 的 `test_consecutive_failures_emit_one_alert_and_are_exposed` 调用本符号
    #   - 内部调用：`time.monotonic`、`str`、`outcome.get`、`time.time`、`defaultdict`、`last_failure.get`、`self._inference_last_alert_at.get`、`dict`、`self.config_cache.get(camera_id,
    #          {}).get`、`self.config_cache.get` 等共 12 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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

            if not failures:
                self._inference_consecutive_failures[target] = 0
                self._inference_last_status[target] = {
                    "status": INFERENCE_STATUS_OK,
                    "error_code": None,
                    "updated_at": time.time(),
                }
                return

            consecutive = self._inference_consecutive_failures[target] + 1
            self._inference_consecutive_failures[target] = consecutive
            failure_counts: dict[str, int] = defaultdict(int)
            for outcome in failures:
                failure_counts[str(outcome.get("status") or "unknown")] += 1
            last_failure = failures[-1]
            self._inference_last_status[target] = {
                "status": str(last_failure.get("status") or "unknown"),
                "error_code": last_failure.get("error_code"),
                "updated_at": time.time(),
            }

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

    # 功能：返回可序列化的推理结果统计快照，供运行状态接口使用；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_inference_outcomes.py` 的 `test_consecutive_failures_emit_one_alert_and_are_exposed` 调用本符号
    #   - 内部调用：`sorted`、`self._inference_outcome_counts_by_target.items`、`targets.append`、`dict`、`self._inference_consecutive_failures.get`、`self._inference_last_status.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def inference_status(self) -> dict:
        """返回可序列化的推理结果统计快照，供运行状态接口使用。"""
        with self._inference_status_lock:
            targets = []
            for (model_name, camera_id), counts in sorted(
                self._inference_outcome_counts_by_target.items(),
                key=lambda item: (item[0][0], item[0][1]),
            ):
                targets.append({
                    "model_name": model_name,
                    "camera_id": camera_id,
                    "counts": dict(counts),
                    "consecutive_failures": self._inference_consecutive_failures.get(
                        (model_name, camera_id),
                        0,
                    ),
                    "last_outcome": dict(self._inference_last_status.get((model_name, camera_id), {})),
                })
            return {
                "totals": dict(self.inference_outcome_counts),
                "targets": targets,
            }

    # ------------------------------------------------------------------ #
    #  告警处理                                                             #
    # ------------------------------------------------------------------ #

    # 功能：判定是否触发告警，并通过 alarm_dispatcher 分发到各通道；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `result`（list）：`result` 对应的业务输入值
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：`self.config_cache.get`、`self._should_alarm`、`cfg.get`、`alarm_dispatcher.maybe_dispatch`、`AlarmRequest`、`self.frame_cache.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _handle_alarm(self, camera_id: int, result: list, frame: np.ndarray):
        """
        判定是否触发告警，并通过 alarm_dispatcher 分发到各通道。

        将数据库扁平字段（sql_enable、horn_enable 等）重组为
        alarm_dispatcher 期望的嵌套 alarm_config 结构，
        避免在每个子类中重复此转换逻辑。
        """
        cfg = self.config_cache.get(camera_id, {})
        if not self._should_alarm(camera_id, result, cfg):
            return

        cam_key = cfg.get("shm_name", "")
        cam_name = cfg.get("name") or cam_key

        # 将 ORM 扁平字段重组为 AlarmDispatcher 期望的嵌套结构
        alarm_config = {
            "sql": {
                "enable": cfg.get("sql_enable", False),
                "parm": {},
            },
            "horn": {
                "enable": cfg.get("horn_enable", False),
                "parm": {
                    "horn_id":       cfg.get("horn_id"),
                    "horn_event_id": cfg.get("horn_event_id"),
                },
            },
            "wechat": {
                "enable": cfg.get("wechat_enable", False),
                "parm": {"user": cfg.get("wechat_user", "")},
            },
        }

        alarm_dispatcher.maybe_dispatch(
            AlarmRequest(
                feature_name=self.feature_name,
                camera_id=camera_id,
                camera_name=cam_name,
                # frame 优先用带标注帧，fallback 到原始帧缓存
                frame=frame if frame is not None else self.frame_cache.get(camera_id),
                violation_type=self.spec.violation_type,
                alarm_config=alarm_config,
                camera_key=cam_key,
                department=cfg.get("department") or "",
            ),
            alarm_interval=cfg.get("alarm_interval", 5.0),
        )

    # 功能：默认告警判定：result 中任意一项 alarm_flag 为 True 即触发；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `result`（list）：`result` 对应的业务输入值
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_handle_alarm` 调用本符号
    #   - 内部调用：`bool`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _should_alarm(self, camera_id: int, result: list, cfg: dict) -> bool:
        """
        默认告警判定：result 中任意一项 alarm_flag 为 True 即触发。
        冷却控制由 alarm_dispatcher.maybe_dispatch() 负责，此处不重复判断。

        detect_door 等需要双阶段判定的功能可重写此方法。
        """
        for item in result or []:
            try:
                alarm_flag, _msg = item
            except (TypeError, ValueError):
                alarm_flag = bool(item)
            if alarm_flag:
                return True
        return False

    # 功能：控制在画面无显著变化时是否仍按 cap_interval 周期处理；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """
        控制在画面无显著变化时是否仍按 cap_interval 周期处理。

        默认 False：帧差类功能（blocks、detect_door）依赖画面变化驱动处理。
        YOLO 逗留/目标追踪类功能应重写为 True，否则静止目标的逗留时间无法持续累积。
        """
        return False

    # 功能：控制当前摄像头本轮是否进入检测流程，默认不做时间限制；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `cfg`（dict）：运行配置对象
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        """控制当前摄像头本轮是否进入检测流程，默认不做时间限制。"""
        return True

    # 功能：兼容两种配置结构：；输入与输出详见下方说明
    # 参数：
    #   - `cfg`（dict）：运行配置对象
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号；`AiVision/features/_base/consumer.py` 的
    #         `BaseFunctionConsumer::_get_roi` 调用本符号；`AiVision/features/detect_phone/consumer.py` 的 `PhoneConsumer::_process` 调用本符号
    #   - 内部调用：`isinstance`、`cfg.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _value_config(cfg: dict) -> dict:
        """
        兼容两种配置结构：
            API 层嵌套格式  — cfg = {"value": {...}, "alarm": {...}}
            运行时 ORM 扁平格式 — cfg = {"cap_interval": 0.1, "enable": 1, ...}

        优先取 cfg["value"]；不存在或非 dict 时直接使用 cfg 本身。
        """
        value = cfg.get("value") if isinstance(cfg, dict) else None
        return value if isinstance(value, dict) else (cfg or {})

    # ------------------------------------------------------------------ #
    #  ROI 工具                                                             #
    # ------------------------------------------------------------------ #

    # 功能：将多种格式的 roi_pos 统一归一化为 [[polygon], [polygon], ...] 格式；输入与输出详见下方说明
    # 参数：
    #   - `roi_pos`（未显式标注）：`roi_pos` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_rebuild_masks` 调用本符号
    #   - 内部调用：`isinstance`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _normalize_roi_pos(roi_pos):
        """
        将多种格式的 roi_pos 统一归一化为 [[polygon], [polygon], ...] 格式。

        支持三种输入格式：
            [x1, y1, x2, y2]          → 矩形框，转为单多边形列表
            [[x,y], [x,y], ...]        → 单个多边形点集，包装为列表
            [[[x,y],...], [[x,y],...]] → 已是多边形列表，原样返回
        """
        if not roi_pos:
            return []
        if not isinstance(roi_pos[0], list):
            # 四元素平铺矩形 [x1, y1, x2, y2]
            x1, y1, x2, y2 = roi_pos[0], roi_pos[1], roi_pos[2], roi_pos[3]
            return [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
        if not isinstance(roi_pos[0][0], list):
            # 单个多边形点集 [[x,y], ...]
            return [roi_pos]
        # 已是多边形列表 [[[x,y],...], ...]
        return roi_pos

    # 功能：返回当前摄像头缓存的多边形列表，供子类绘制 ROI 边框使用；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._roi_polygon_cache.get`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _get_roi_polygons(self, camera_id: int):
        """返回当前摄像头缓存的多边形列表，供子类绘制 ROI 边框使用。"""
        return self._roi_polygon_cache.get(camera_id, [])

    # 功能：按配置裁剪帧中的 ROI 区域，返回各多边形的掩码裁剪结果；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    # 返回：list[np.ndarray]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：`self.config_cache.get`、`self._value_config`、`value_cfg.get`、`isinstance`、`roi_pos_raw.tolist`、`tuple`、`self._masks_roi_input.get`、`self._masks_frame_shape.get`、`self._rebuild_masks`、`roi_list.append`
    #          等共 11 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _get_roi(self, camera_id: int, frame: np.ndarray) -> list[np.ndarray]:
        """
        按配置裁剪帧中的 ROI 区域，返回各多边形的掩码裁剪结果。

        未配置 ROI 时使用整帧；配置变更时自动重建掩码。
        多边形区域外的像素被掩码置零，子类接收到的是形状为矩形包围盒
        但区域外为黑色的图像块。
        """
        cfg = self.config_cache.get(camera_id, {})
        value_cfg = self._value_config(cfg)
        roi_pos_raw = value_cfg.get("roi_pos") or []
        if isinstance(roi_pos_raw, np.ndarray):
            roi_pos_raw = roi_pos_raw.tolist()

        # 未配置 ROI：使用整帧作为单一 ROI
        if not roi_pos_raw:
            h, w = frame.shape[:2]
            roi_pos_raw = [[0, 0], [w, 0], [w, h], [0, h]]

        # ROI 配置或当前摄像头的帧尺寸变更时重建掩码。
        # 不同摄像头、主子码流可能具有不同分辨率，不能复用旧尺寸掩码。
        frame_shape = tuple(frame.shape[:2])
        if (
            camera_id not in self._masks
            or self._masks_roi_input.get(camera_id) != roi_pos_raw
            or self._masks_frame_shape.get(camera_id) != frame_shape
        ):
            self._rebuild_masks(camera_id, frame, roi_pos_raw)

        roi_list = []
        for mask, y_min, y_max, x_min, x_max in self._masks[camera_id]:
            cropped = frame[y_min:y_max, x_min:x_max]
            roi_list.append(cv2.bitwise_and(cropped, cropped, mask=mask))
        return roi_list

    # 功能：根据多边形坐标预计算裁剪掩码，缓存至 _masks[camera_id]；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `frame`（np.ndarray）：待处理的视频图像帧
    #   - `roi_pos_raw`（未显式标注）：`roi_pos_raw` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_get_roi` 调用本符号
    #   - 内部调用：`self.pre_roi.pop`、`self.blur_roi.pop`、`self.frame_change_samples.pop`、`self._normalize_roi_pos`、`enumerate`、`np.array`、`logger.warning`、`arr[:,
    #          0].min`、`arr[:, 1].min`、`arr[:, 0].max` 等共 18 个调用。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def _rebuild_masks(self, camera_id: int, frame: np.ndarray, roi_pos_raw):
        """
        根据多边形坐标预计算裁剪掩码，缓存至 _masks[camera_id]。

        每个多边形生成一个 (mask, y_min, y_max, x_min, x_max) 五元组：
            mask        — 多边形内为 255、外为 0 的单通道掩码，尺寸为包围盒大小。
            y/x min/max — 包围盒坐标，用于从原始帧中裁剪对应区域。

        同时清除与旧 ROI 关联的帧差缓存，
        避免新旧 ROI 的帧差计算产生错误跳帧判断。
        """
        frame_height, frame_width = frame.shape[:2]
        self._masks_roi_input[camera_id] = roi_pos_raw
        self._masks_frame_shape[camera_id] = (frame_height, frame_width)
        self.pre_roi.pop(camera_id, None)   # 清除旧帧差缓存
        self.blur_roi.pop(camera_id, None)
        self.frame_change_samples.pop(camera_id, None)
        polygons = self._normalize_roi_pos(roi_pos_raw)
        self._roi_polygon_cache[camera_id] = polygons

        masks = []
        for roi_index, poly in enumerate(polygons):
            arr = np.array(poly, dtype=np.int32)
            if arr.ndim != 2 or arr.shape[0] < 3 or arr.shape[1] != 2:
                logger.warning(
                    f"[{self.feature_name}] 摄像头 {camera_id} 的 ROI {roi_index} "
                    "坐标无效，已跳过"
                )
                continue

            raw_x_min, raw_y_min = arr[:, 0].min(), arr[:, 1].min()
            raw_x_max, raw_y_max = arr[:, 0].max(), arr[:, 1].max()
            x_min = max(0, int(raw_x_min))
            y_min = max(0, int(raw_y_min))
            x_max = min(frame_width, int(raw_x_max))
            y_max = min(frame_height, int(raw_y_max))

            if x_max <= x_min or y_max <= y_min:
                logger.warning(
                    f"[{self.feature_name}] 摄像头 {camera_id} 的 ROI {roi_index} "
                    f"完全位于当前画面 {frame_width}x{frame_height} 外，已跳过"
                )
                continue

            if (
                x_min != raw_x_min
                or y_min != raw_y_min
                or x_max != raw_x_max
                or y_max != raw_y_max
            ):
                logger.warning(
                    f"[{self.feature_name}] 摄像头 {camera_id} 的 ROI {roi_index} "
                    f"超出当前画面 {frame_width}x{frame_height}，已按画面边界裁剪"
                )

            mask = np.zeros((y_max - y_min, x_max - x_min), dtype=np.uint8)
            adj = arr.copy()
            adj[:, 0] -= x_min  # 坐标平移到包围盒原点
            adj[:, 1] -= y_min
            cv2.fillPoly(mask, [adj], 255)
            masks.append((mask, y_min, y_max, x_min, x_max))
        self._masks[camera_id] = masks

    # 功能：相似帧快速跳过检测，避免对静止画面重复推理；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `roi_list`（list[np.ndarray]）：`roi_list` 对应的业务输入值
    #   - `threshold`（float）：`threshold` 对应的业务输入值；默认值为 `0.005`
    # 返回：bool；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：`len`、`self._initialize_frame_change_state`、`enumerate`、`self._frame_change_sample`、`cv2.absdiff`、`quick.mean`、`cv2.GaussianBlur`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _frame_changed(self, camera_id: int, roi_list: list[np.ndarray], threshold: float = 0.005) -> bool:
        """
        相似帧快速跳过检测，避免对静止画面重复推理。

        算法：4x 下采样 → 高斯模糊 → 灰度绝对差均值，与阈值比较。
        4x 下采样大幅降低计算量，对于判断"是否有显著变化"精度已足够。
        首次调用时初始化缓存并返回 True（强制处理第一帧）。

        Args:
            threshold: 差值比率阈值（0~1），默认 0.005（约 1.275/255），
                       低于此值视为画面无变化。
        """
        if (
            camera_id not in self.pre_roi
            or camera_id not in self.frame_change_samples
            or len(self.pre_roi[camera_id]) != len(roi_list)
            or len(self.frame_change_samples[camera_id]) != len(roi_list)
        ):
            self._initialize_frame_change_state(camera_id, roi_list)
            return True

        for i, roi in enumerate(roi_list):
            sample = self._frame_change_sample(roi)
            previous_sample = self.frame_change_samples[camera_id][i]
            if sample.shape != previous_sample.shape:
                self._initialize_frame_change_state(camera_id, roi_list)
                return True

            quick = cv2.absdiff(sample, previous_sample)
            ratio = quick.mean() / 255.0
            if ratio > threshold:
                # 仅显著变化时计算完整分辨率模糊帧，供门检测等业务使用。
                self.frame_change_samples[camera_id][i] = sample
                self.blur_roi[camera_id][i] = cv2.GaussianBlur(
                    roi,
                    _FRAME_CHANGE_BLUR_KERNEL,
                    0,
                )
                self.pre_roi[camera_id][i] = roi
                return True
        return False

    # 功能：先 4 倍下采样再模糊，生成仅用于快速帧差判断的小图；输入与输出详见下方说明
    # 参数：
    #   - `roi`（np.ndarray）：感兴趣区域的坐标集合
    # 返回：np.ndarray；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_frame_changed`
    #         调用本符号；`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_initialize_frame_change_state` 调用本符号
    #   - 内部调用：`np.ascontiguousarray`、`cv2.GaussianBlur`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @staticmethod
    def _frame_change_sample(roi: np.ndarray) -> np.ndarray:
        """先 4 倍下采样再模糊，生成仅用于快速帧差判断的小图。"""
        sampled = np.ascontiguousarray(
            roi[::_FRAME_CHANGE_SAMPLE_STEP, ::_FRAME_CHANGE_SAMPLE_STEP]
        )
        return cv2.GaussianBlur(sampled, _FRAME_CHANGE_BLUR_KERNEL, 0)

    # 功能：初始化帧差小图，同时保留业务处理依赖的完整模糊帧；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `roi_list`（list[np.ndarray]）：`roi_list` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_frame_changed` 调用本符号
    #   - 内部调用：`list`、`self._frame_change_sample`、`cv2.GaussianBlur`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _initialize_frame_change_state(self, camera_id: int, roi_list: list[np.ndarray]) -> None:
        """初始化帧差小图，同时保留业务处理依赖的完整模糊帧。"""
        self.pre_roi[camera_id] = list(roi_list)
        self.frame_change_samples[camera_id] = [
            self._frame_change_sample(roi)
            for roi in roi_list
        ]
        self.blur_roi[camera_id] = [
            cv2.GaussianBlur(roi, _FRAME_CHANGE_BLUR_KERNEL, 0)
            for roi in roi_list
        ]

    # ------------------------------------------------------------------ #
    #  推理调度                                                             #
    # ------------------------------------------------------------------ #

    # 功能：同步推理调度：将所有 ROI 投入推理队列，阻塞等待全部结果后返回；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `camera_id`（int）：摄像头唯一标识
    #   - `model_name`（str）：`model_name` 对应的业务输入值
    #   - `roi_list`（list[np.ndarray]）：`roi_list` 对应的业务输入值
    #   - `task_meta`（Optional[dict]）：`task_meta` 对应的业务输入值；默认值为 `None`
    #   - `timeout`（float）：允许操作等待的最长秒数；默认值为 `0.8`
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/tests/test_inference_outcomes.py` 的 `test_dispatch_reports_model_unavailable_for_every_roi`
    #         调用本符号；`AiVision/tests/test_inference_outcomes.py` 的 `test_dispatch_reports_queue_full_without_losing_roi_identity`
    #         调用本符号；`AiVision/tests/test_inference_outcomes.py` 的
    #         `test_dispatch_keeps_partial_result_roi_and_marks_other_roi_timeout` 调用本符号；`AiVision/tests/test_inference_outcomes.py`
    #         的 `test_consecutive_failures_emit_one_alert_and_are_exposed` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`time.monotonic_ns`、`enumerate`、`build_inference_result`、`self._record_inference_outcomes`、`set`、`int`、`self.infer_dict[model_name].put`、`pending.add`、`time.monotonic`、`self.result_queue.get`
    #          等共 18 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def dispatch_inference_sync(
        self,
        camera_id: int,
        model_name: str,
        roi_list: list[np.ndarray],
        task_meta: Optional[dict] = None,
        timeout: float = 0.8,
    ) -> list[dict]:
        """
        同步推理调度：将所有 ROI 投入推理队列，阻塞等待全部结果后返回。

        通过 request_id（feature:camera_id:单调时间戳）标识本次请求，
        过滤掉属于其他请求或其他功能的结果，避免并发干扰。

        每个 ROI 始终返回一项结果。队列满、等待超时或模型不可用时，
        detections 保持为空，并通过 status/error_code 明确失败原因。

        Args:
            model_name: 推理模型名称，须在 infer_dict 中已注册。
            roi_list  : 裁剪后的 ROI 图像列表，每个元素对应一个多边形区域。
            task_meta : 附加给推理任务的额外元数据（如置信度阈值）。
            timeout   : 等待所有结果的最长时间（秒），超时后返回已收到的结果。

        Returns:
            按 roi_id 升序排列的推理结果列表，长度与 roi_list 一致。
        """
        import queue as _q

        task_meta = task_meta or {}
        # request_id 以单调时间戳保证唯一性，避免同一摄像头连续帧的结果串台
        request_id = f"{self.feature_name}:{camera_id}:{time.monotonic_ns()}"
        tasks = [
            {
                **task_meta,
                "roi_id": roi_id,
                "camera_id": camera_id,
                "frame": roi,
                "function_name": self.feature_name,
                "request_id": request_id,
                "model_name": model_name,
            }
            for roi_id, roi in enumerate(roi_list)
        ]

        if model_name not in self.infer_dict:
            results = [
                build_inference_result(
                    task,
                    status=INFERENCE_STATUS_UNAVAILABLE,
                    error_code=INFERENCE_ERROR_UNAVAILABLE,
                    error_message=f"模型未注册: {model_name}",
                )
                for task in tasks
            ]
            self._record_inference_outcomes(
                camera_id=camera_id,
                model_name=model_name,
                outcomes=results,
            )
            return results

        pending: set[int] = set()
        results_by_roi: dict[int, dict] = {}

        for task in tasks:
            roi_id = int(task["roi_id"])
            try:
                self.infer_dict[model_name].put(
                    task,
                    timeout=0.02,
                )  # 0.02s 超时：队列满时快速失败，不阻塞主循环
                pending.add(roi_id)
            except _q.Full:
                results_by_roi[roi_id] = build_inference_result(
                    task,
                    status=INFERENCE_STATUS_DROPPED,
                    error_code=INFERENCE_ERROR_QUEUE_FULL,
                    error_message="模型推理队列已满",
                )

        deadline = time.monotonic() + timeout
        while pending and time.monotonic() < deadline:
            try:
                outcome = self.result_queue.get(
                    timeout=min(0.1, max(0.0, deadline - time.monotonic()))
                )
                # 过滤：仅接受属于本次请求的结果
                if (
                    outcome.get("camera_id") == camera_id
                    and outcome.get("function_name") == self.feature_name
                    and outcome.get("request_id") == request_id
                    and outcome.get("roi_id") in pending
                ):
                    roi_id = int(outcome["roi_id"])
                    normalized = dict(outcome)
                    normalized.setdefault("model_name", model_name)
                    normalized.setdefault("status", INFERENCE_STATUS_OK)
                    normalized.setdefault("error_code", None)
                    normalized.setdefault("error_message", None)
                    normalized.setdefault("inference_ms", None)
                    normalized.setdefault("detections", [])
                    results_by_roi[roi_id] = normalized
                    pending.discard(roi_id)
            except _q.Empty:
                continue

        for roi_id in pending:
            results_by_roi[roi_id] = build_inference_result(
                tasks[roi_id],
                status=INFERENCE_STATUS_TIMEOUT,
                error_code=INFERENCE_ERROR_TIMEOUT,
                error_message=f"等待推理结果超时: {timeout:.3f}s",
            )

        results = [results_by_roi[roi_id] for roi_id in range(len(tasks))]
        self._record_inference_outcomes(
            camera_id=camera_id,
            model_name=model_name,
            outcomes=results,
        )
        return results

    # 功能：收集已完成的异步推理结果（扩展点，当前暂未使用）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/consumer.py` 的 `BaseFunctionConsumer::_run` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _collect_async_results(self):
        """
        收集已完成的异步推理结果（扩展点，当前暂未使用）。

        同步 dispatch_inference_sync() 已能满足现有功能的需求。
        若未来引入真正异步推理（投递后不阻塞、结果由回调写入），
        子类可重写此方法在主循环开头批量消费结果队列。
        """
        pass
