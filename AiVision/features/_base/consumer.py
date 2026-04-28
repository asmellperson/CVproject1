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
from typing import Optional

import cv2
import numpy as np

from core.cache import config_cache
from core.logger import logger
from core.alarm.dispatcher import alarm_dispatcher, AlarmRequest
from features._base.spec import FeatureSpec


class BaseFunctionConsumer(ABC):
    """所有功能消费者的基类 — 一个功能一个 Consumer 线程"""

    def __init__(
        self,
        spec: FeatureSpec,
        infer_dict: dict,             # {model_name: Queue} 推理调度入口
        result_queue,                  # 本 feature 接收推理结果的队列
        latest_frames: dict[str, np.ndarray],  # 由 CameraManager 维护的最新帧
        is_camera_active,              # callable(shm_name) -> bool
    ):
        self.spec = spec
        self.feature_name = spec.name
        self.infer_dict = infer_dict
        self.result_queue = result_queue
        self.latest_frames = latest_frames
        self.is_camera_active = is_camera_active

        # 配置 & 状态缓存(一份 camera_id 索引)
        self.config_cache: dict[int, dict] = {}
        self.frame_cache: dict[int, np.ndarray] = {}

        # ROI / 相似帧
        self._roi_polygon_cache: dict[int, list] = {}
        self._masks: dict[int, list] = {}
        self._masks_roi_input: dict[int, list] = {}
        self.pre_roi: dict[int, list] = {}
        self.blur_roi: dict[int, list[np.ndarray]] = defaultdict(list)

        # 输出帧 — Orchestrator 透过此字典提供给 API/前端
        self.result_dict: dict[str, np.ndarray] = {}
        self.result_updated_at: dict[str, float] = {}

        # 异步推理跟踪(detect_face 等异步 dispatch 使用)
        self._pending_results: dict[int, list] = defaultdict(list)
        self._expected_roi_count: dict[int, int] = {}
        self._pending_timestamps: dict[int, float] = {}
        self._last_process_at: dict[int, float] = {}

        self.running = False
        self._thread: Optional[threading.Thread] = None

    # ---------- 生命周期 ----------

    def start(self):
        if self.running:
            return
        self._load_initial_configs()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            f"[{self.feature_name}] Consumer 已启动,监控 {len(self.config_cache)} 个摄像头"
        )

    def stop(self):
        self.running = False
        logger.info(f"[{self.feature_name}] Consumer 已停止")

    def _load_initial_configs(self):
        """从全局缓存加载本 feature 的所有摄像头配置"""
        for (camera_id, fname), cfg in config_cache.get_all_function_configs().items():
            if fname == self.feature_name and cfg.get("enable"):
                self.config_cache[camera_id] = cfg

    # ---------- 配置变更回调(由 Orchestrator 路由事件来触发) ----------

    def update_config(self, camera_id: int):
        cfg = config_cache.get_function_config(camera_id, self.feature_name)
        if cfg:
            self.config_cache[camera_id] = cfg
            # 清除 ROI 缓存,下轮重建
            self._masks.pop(camera_id, None)
            self._masks_roi_input.pop(camera_id, None)
            self._roi_polygon_cache.pop(camera_id, None)

    def update_status(self, camera_id: int, enabled: bool):
        if enabled:
            cfg = config_cache.get_function_config(camera_id, self.feature_name)
            if cfg:
                self.config_cache[camera_id] = cfg
        else:
            cfg = self.config_cache.pop(camera_id, None)
            cam_name = (cfg or {}).get("shm_name")
            if cam_name:
                self.result_dict.pop(cam_name, None)
                self.result_updated_at.pop(cam_name, None)

    # ---------- 主循环 ----------

    def _run(self):
        while self.running:
            try:
                # 收集已完成的异步推理结果(face/phone/human 用)
                self._collect_async_results()

                for cam_id in list(self.config_cache.keys()):
                    cam_name = self.config_cache[cam_id].get("shm_name")
                    if not cam_name or not self.is_camera_active(cam_name):
                        continue

                    frame = self.latest_frames.get(cam_name)
                    if frame is None:
                        continue
                    self.frame_cache[cam_id] = frame

                    roi_list = self._get_roi(cam_id, frame)
                    cfg = self.config_cache.get(cam_id, {})
                    frame_changed = self._frame_changed(cam_id, roi_list)
                    now = time.time()
                    cap_interval = float(self._value_config(cfg).get("cap_interval", 0.1) or 0.1)
                    due_by_interval = now - self._last_process_at.get(cam_id, 0.0) >= cap_interval
                    if not frame_changed and not (self._process_static_frames(camera_id=cam_id, cfg=cfg) and due_by_interval):
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
                time.sleep(0.5)

    # ---------- 抽象方法(子类必须实现) ----------

    @abstractmethod
    def _process(self, roi_list: list[np.ndarray], camera_id: int) -> list[tuple[bool, dict]]:
        """业务处理 — 接收 ROI 帧列表,返回 (是否告警, 详情字典) 元组列表"""

    @abstractmethod
    def post_process(self, camera_id: int, result: list) -> np.ndarray:
        """在原始帧上叠加可视化标注,返回带标注的帧"""

    # ---------- 告警 ----------

    def _handle_alarm(self, camera_id: int, result: list, frame: np.ndarray):
        """判定是否触发告警,通过 alarm_dispatcher 分发"""
        cfg = self.config_cache.get(camera_id, {})
        # 子类可重写 _should_alarm 来实现自定义判定(如 door 的双阶段)
        if not self._should_alarm(camera_id, result, cfg):
            return

        cam_key = cfg.get("shm_name", "")
        cam_name = cfg.get("name") or cam_key
        # 把扁平的告警字段重组成 alarm_config 嵌套结构
        alarm_config = {
            "sql": {"enable": cfg.get("sql_enable", False), "parm": {}},
            "horn": {
                "enable": cfg.get("horn_enable", False),
                "parm": {
                    "horn_id": cfg.get("horn_id"),
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
                frame=frame if frame is not None else self.frame_cache.get(camera_id),
                violation_type=self.spec.violation_type,
                alarm_config=alarm_config,
                camera_key=cam_key,
            ),
            alarm_interval=cfg.get("alarm_interval", 5.0),
        )

    def _should_alarm(self, camera_id: int, result: list, cfg: dict) -> bool:
        """默认:只要 result 中存在 alarm_flag=True 就触发,冷却由 dispatcher 控制"""
        for item in result or []:
            try:
                alarm_flag, _msg = item
            except (TypeError, ValueError):
                alarm_flag = bool(item)
            if alarm_flag:
                return True
        return False

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """是否在画面差异很小时仍按 cap_interval 处理。

        帧差类功能默认依赖画面变化;YOLO 逗留/目标检测类功能会重写为 True,
        否则静止人员的逗留时间无法持续累积。
        """
        return False

    @staticmethod
    def _value_config(cfg: dict) -> dict:
        """兼容 API 层嵌套配置和运行时缓存的 ORM 扁平配置。"""
        value = cfg.get("value") if isinstance(cfg, dict) else None
        return value if isinstance(value, dict) else (cfg or {})

    # ---------- ROI 工具(子类共享) ----------

    @staticmethod
    def _normalize_roi_pos(roi_pos):
        """归一化 ROI 为 [[polygon], [polygon], ...] 格式"""
        if not roi_pos:
            return []
        if not isinstance(roi_pos[0], list):
            x1, y1, x2, y2 = roi_pos[0], roi_pos[1], roi_pos[2], roi_pos[3]
            return [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
        if not isinstance(roi_pos[0][0], list):
            return [roi_pos]
        return roi_pos

    def _get_roi_polygons(self, camera_id: int):
        return self._roi_polygon_cache.get(camera_id, [])

    def _get_roi(self, camera_id: int, frame: np.ndarray) -> list[np.ndarray]:
        """根据配置裁剪 ROI 区域"""
        cfg = self.config_cache.get(camera_id, {})
        value_cfg = self._value_config(cfg)
        roi_pos_raw = value_cfg.get("roi_pos") or []
        if isinstance(roi_pos_raw, np.ndarray):
            roi_pos_raw = roi_pos_raw.tolist()

        # 未配置 ROI: 整帧
        if not roi_pos_raw:
            h, w = frame.shape[:2]
            roi_pos_raw = [[0, 0], [w, 0], [w, h], [0, h]]

        # 配置变更则重建掩码
        if camera_id not in self._masks or self._masks_roi_input.get(camera_id) != roi_pos_raw:
            self._rebuild_masks(camera_id, frame, roi_pos_raw)

        roi_list = []
        for mask, y_min, y_max, x_min, x_max in self._masks[camera_id]:
            cropped = frame[y_min:y_max, x_min:x_max]
            roi_list.append(cv2.bitwise_and(cropped, cropped, mask=mask))
        return roi_list

    def _rebuild_masks(self, camera_id: int, frame: np.ndarray, roi_pos_raw):
        self._masks_roi_input[camera_id] = roi_pos_raw
        self.pre_roi.pop(camera_id, None)
        self.blur_roi.pop(camera_id, None)
        polygons = self._normalize_roi_pos(roi_pos_raw)
        self._roi_polygon_cache[camera_id] = polygons

        masks = []
        for poly in polygons:
            arr = np.array(poly, dtype=np.int32)
            x_min, y_min = arr[:, 0].min(), arr[:, 1].min()
            x_max, y_max = arr[:, 0].max(), arr[:, 1].max()
            mask = np.zeros((y_max - y_min, x_max - x_min), dtype=np.uint8)
            adj = arr.copy()
            adj[:, 0] -= x_min
            adj[:, 1] -= y_min
            cv2.fillPoly(mask, [adj], 255)
            masks.append((mask, y_min, y_max, x_min, x_max))
        self._masks[camera_id] = masks

    def _frame_changed(self, camera_id: int, roi_list: list[np.ndarray], threshold: float = 0.005) -> bool:
        """相似帧快速跳过 — 4x 下采样灰度差分,变化太小则不处理"""
        if camera_id not in self.pre_roi:
            self.pre_roi[camera_id] = list(roi_list)
            self.blur_roi[camera_id] = [cv2.GaussianBlur(r, (5, 5), 0) for r in roi_list]
            return True
        for i, roi in enumerate(roi_list):
            if i >= len(self.pre_roi[camera_id]):
                self.blur_roi[camera_id].append(cv2.GaussianBlur(roi, (5, 5), 0))
                continue
            blur = cv2.GaussianBlur(roi, (5, 5), 0)
            quick = cv2.absdiff(blur[::4, ::4], self.pre_roi[camera_id][i][::4, ::4])
            ratio = quick.mean() / 255.0
            if ratio > threshold:
                self.blur_roi[camera_id][i] = blur
                self.pre_roi[camera_id][i] = roi
                return True
        return False

    # ---------- 推理调度(同步 + 异步两种) ----------

    def dispatch_inference_sync(
        self,
        camera_id: int,
        model_name: str,
        roi_list: list[np.ndarray],
        task_meta: Optional[dict] = None,
        timeout: float = 0.8,
    ) -> list[dict]:
        """同步分发推理 — 投递所有 ROI 后阻塞等待结果。"""
        if model_name not in self.infer_dict:
            return []
        import queue as _q

        pending = set()
        task_meta = task_meta or {}
        request_id = f"{self.feature_name}:{camera_id}:{time.monotonic_ns()}"
        for roi_id, roi in enumerate(roi_list):
            try:
                self.infer_dict[model_name].put({
                    "roi_id": roi_id,
                    "camera_id": camera_id,
                    "frame": roi,
                    "function_name": self.feature_name,
                    "request_id": request_id,
                    **task_meta,
                }, timeout=0.02)
                pending.add(roi_id)
            except _q.Full:
                pass

        results = []
        deadline = time.time() + timeout
        while pending and time.time() < deadline:
            try:
                detections = self.result_queue.get(timeout=min(0.1, max(0.0, deadline - time.time())))
                if (
                    detections.get("camera_id") == camera_id
                    and detections.get("function_name") == self.feature_name
                    and detections.get("request_id") == request_id
                    and detections.get("roi_id") in pending
                ):
                    results.append(detections)
                    pending.discard(detections["roi_id"])
            except _q.Empty:
                continue

        results.sort(key=lambda x: x.get("roi_id", 0))
        return results

    def _collect_async_results(self):
        """收集已完成的异步推理结果 — 子类如使用异步 dispatch 时由主循环调用。
        
        当前同步 dispatch 已能满足需求,此方法保留为扩展点。
        """
        pass
