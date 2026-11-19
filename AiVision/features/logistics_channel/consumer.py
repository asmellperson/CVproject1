"""
负责摄像头中有几个人。然后将结果交给LogisticsChannelRuntime做多摄像头融合
流程：
    单个归一化 ROI 按实际帧尺寸还原后做 YOLO 人体检测
    过滤检测框
    统计摄像头 ROI 内人数
    把ROI局部坐标还原成全图坐标
    检测框去重
    生成CameraSnapshot
    LogisticsChannelRuntime
    多摄像头融合
    最终判断empty/normal/multiple/unknow
"""
from __future__ import annotations

import time
from typing import Protocol

import cv2
import numpy as np

from .state import (
    CameraSnapshot,
    LogisticsDetectionConfig,
    PersonDetection,
    deduplicate_person_detections,
    translate_person_detection,
)
from AiVision.features._shared.pipelined_consumer import PipelinedConsumer

from .constants import PERSON_DEDUP_IOU_THRESHOLD

class LogisticsConsumerRuntime(Protocol):
    """单路检测向通道运行时读取配置、发布快照和请求汇总的注入接口。"""
    def camera_should_run(self, feature_name: str, camera_id: int) -> bool:
        """声明摄像头当前是否属于需要运行的有效通道成员。"""
        ...

    def detection_config_for_camera(self, feature_name: str, camera_id: int) -> LogisticsDetectionConfig | None:
        """返回摄像头所属通道共享的检测策略，无有效归属时返回 None。"""
        ...

    def update_camera_snapshot(
        self,
        feature_name: str,
        snapshot: CameraSnapshot,
        annotated_frame: np.ndarray | None,
    ) -> None:
        """接收单摄计数事实及可选标注帧，供通道聚合和预览使用。"""
        ...

    def evaluate_after_camera_update(self, feature_name: str, camera_id: int) -> None:
        """要求运行时在新单摄结果发布后重新汇总所属通道。"""
        ...

def build_monitor_snapshot(result: tuple, updated_at: float | None = None) -> dict:
    """当前摄像头唯一 ROI 的监控状态。"""
    alarm, detail = result
    return {
        "count": detail["person_count"],
        "alarm": bool(alarm),
        "reason": detail["reason"],
        "updated_at_s": time.time() if updated_at is None else float(updated_at),
    }


class LogisticsSinglePersonConsumer(PipelinedConsumer):
    """逐路推理、坐标还原和快照发布；人数告警统一交给通道运行时。"""

    BBOX_COLOR_NORMAL = (0, 180, 0)
    BBOX_COLOR_ABNORMAL = (0, 0, 255)
    ROI_COLOR_NORMAL = (0, 180, 0)
    ROI_COLOR_ABNORMAL = (0, 0, 255)
    ROI_COLOR_UNKNOWN = (0, 165, 255)

    def __init__(self, *args, logistics_runtime: LogisticsConsumerRuntime | None = None, **kwargs):
        """要求注入通道运行时，防止脱离多摄聚合直接进行单路告警。"""
        if logistics_runtime is None:
            raise RuntimeError(
                f"{type(self).__name__} 缺少 LogisticsChannelRuntime 注入；"
                "物流单人检测不能在无通道聚合运行时的情况下启动"
            )
        super().__init__(*args, **kwargs)
        self.logistics_runtime = logistics_runtime
        self.monitor_status: dict[str, dict] = {}
        self._sample_policies: dict[int, LogisticsDetectionConfig] = {}

    @property
    def inference_model(self) -> str:
        return self.spec.required_models[0]

    def _clear_camera_state(self, camera_id: int, shm_name: str | None):
        """随基础状态清理当前共享帧标识的监控结果。"""
        super()._clear_camera_state(camera_id, shm_name)
        if shm_name:
            self.monitor_status.pop(shm_name, None)

    def _processing_interval_seconds(self, camera_id: int, cfg: dict) -> float | None:
        """使用通道统一采样周期，无有效通道配置时不提供周期。"""
        detection = self.logistics_runtime.detection_config_for_camera(self.feature_name, camera_id)
        return None if detection is None else detection.cap_interval

    def _can_sample(self, camera_id: int, cfg: dict) -> bool:
        if not self.logistics_runtime.camera_should_run(self.feature_name, camera_id):
            return False
        previous = self._sample_policies.get(camera_id)
        return previous is None or previous is self.logistics_runtime.detection_config_for_camera(
            self.feature_name, camera_id,
        )

    def _inference_parameters(self, camera_id: int, cfg: dict) -> dict | None:
        detection = self.logistics_runtime.detection_config_for_camera(self.feature_name, camera_id)
        if detection is None or not self.spec.required_models:
            return None
        # 过滤检测框时沿用投递该帧时的通道策略，配置替换后撤销在途请求。
        self._sample_policies[camera_id] = detection
        return {"conf": detection.confidence_threshold, "iou": detection.model_iou_threshold}

    def _invalidate_sample(self, camera_id: int) -> None:
        self._sample_policies.pop(camera_id, None)
        super()._invalidate_sample(camera_id)

    def _process(self, roi, camera_id):
        """
        对当前摄像头唯一 ROI 做人体检测，过滤无效框，计算当前人数和状态
        """
        sample = self._samples.pop(camera_id)
        detection = self._sample_policies.pop(camera_id, None)
        if sample.request is None or detection is None:
            return self._unknown_roi_result()
        det_result = self.resolve_inference(sample.request)
        # 某条结果缺失或推理失败时，直接 unknown，不能误报为无人。
        if det_result.get("status") != "ok" or not isinstance(det_result.get("detections"), list):
            return self._unknown_roi_result()
        detections = self._filter_person_detections(
            det_result["detections"],
            min_box_area=detection.min_box_area,
            min_aspect=detection.min_aspect_ratio,
            max_aspect=detection.max_aspect_ratio,
        )
        # 单个ROI：0人empty，1人normal，2人及以上mutiple
        count = len(detections)
        reason = "empty" if count == 0 else "normal" if count == 1 else "multiple"
        # 不让BaseConsumer自己触发告警（与逗留检测不同。逗留检测自己可以判断告警，物流这边只描述当前摄像头看到什么）
        return False, {"reason": reason, "person_count": count, "elapsed": 0.0, "detections": detections}

    @staticmethod
    def _unknown_roi_result() -> tuple[bool, dict]:
        """构造人数未知结果，避免推理或配置不可用被误计为零人。"""
        return False, {
            "reason": "unknown",
            "person_count": None,
            "elapsed": 0.0,
            "detections": [],
        }

    @staticmethod
    def _filter_person_detections(detections, min_box_area: float, min_aspect, max_aspect):
        """从Worker返回的detections里只留下可信的人体框,做了三层过滤"""
        persons = []
        for detection in detections:
            detection_type = detection.get("type")
            # 第一层：类型
            if detection_type and detection_type not in {"person", "human"}:
                continue
            # 第二层：bbox合法性
            bbox = detection.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            # 第三层：几何过滤，丢弃面积太小，宽高比异常的框
            width = max(0.0, float(bbox[2]) - float(bbox[0]))
            height = max(0.0, float(bbox[3]) - float(bbox[1]))
            if width * height < min_box_area:
                continue
            if height > 0 and min_aspect is not None and max_aspect is not None:
                aspect = width / height
                if aspect < min_aspect or aspect > max_aspect:
                    continue
            persons.append(detection)
        return persons

    def post_process(self, camera_id, result):
        """
        负责：
            ROI检测结果
            局部坐标转全图坐标
            检测框去重
            生成CameraSnapshot
            发给LogisticsChannelRuntime
        """
        annotated = self._annotated_frame(camera_id)
        _alarm, detail = result
        reason = detail["reason"]
        x_offset, y_offset = self._get_roi_offset(camera_id)
        translated_detections: list[PersonDetection] = []
        for detection in detail["detections"]:
            bbox = detection["bbox"]
            translated_detections.append(translate_person_detection(
                PersonDetection(
                    bbox=tuple(float(value) for value in bbox[:4]),
                    confidence=float(detection.get("confidence", 0)),
                ),
                x_offset, y_offset,
            ))
        if annotated is not None:
            cv2.putText(
                annotated, self._label_for(reason, detail["person_count"]),
                (x_offset, max(20, y_offset - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, self._color_for_reason(reason), 2,
            )

        unique_detections = deduplicate_person_detections(
            translated_detections,
            iou_threshold=PERSON_DEDUP_IOU_THRESHOLD,
        )
        # 明确看到多个人，snapshot_count的值就为多个人的值
        count = len(unique_detections)
        snapshot_count = count if count >= 2 or reason != "unknown" else None
        updated_at = self._frame_sampled_at.get(camera_id, time.time())
        camera_cfg = self.config_cache.get(camera_id, {})
        camera_key = str(camera_cfg.get("shm_name") or "").strip()
        camera_name = str(camera_cfg.get("name") or camera_key)
        # CameraSnapshot：当前Camera给物流Channel Runtime的标准化结果
        snapshot = CameraSnapshot(
            camera_id=camera_id,
            camera_name=camera_name,
            count=snapshot_count,
            updated_at=updated_at,
            online=self._camera_online(camera_key),
        )

        if annotated is not None:
            self._draw_unique_detections(annotated, unique_detections, snapshot_count)
        if camera_key:
            self.monitor_status[camera_key] = build_monitor_snapshot(
                (False, {"person_count": snapshot_count, "reason": self._snapshot_reason(snapshot_count)}),
                updated_at=updated_at,
            )
        self.logistics_runtime.update_camera_snapshot(self.feature_name, snapshot, annotated)
        return annotated

    def _camera_online(self, camera_key: str) -> bool:
        """查询注入的采集状态；缺少检查器或帧标识时沿用可用假定。"""
        checker = getattr(self, "is_camera_active", None)
        if not camera_key or not callable(checker):
            return True
        return bool(checker(camera_key))

    def _draw_unique_detections(
        self,
        frame: np.ndarray,
        detections: tuple[PersonDetection, ...],
        count: int | None,
    ) -> None:
        """绘制去重后的原帧人体框，多人时使用异常颜色。"""
        color = self.BBOX_COLOR_ABNORMAL if count is not None and count >= 2 else self.BBOX_COLOR_NORMAL
        for detection in detections:
            x1, y1, x2, y2 = (int(value) for value in detection.bbox)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"person {detection.confidence:.2f}",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2,
            )

    @classmethod
    def _color_for_reason(cls, reason: str) -> tuple[int, int, int]:
        """用颜色区分明确人数异常、未知和正常状态。"""
        if reason in {"empty", "multiple"}:
            return cls.ROI_COLOR_ABNORMAL
        if reason == "unknown":
            return cls.ROI_COLOR_UNKNOWN
        return cls.ROI_COLOR_NORMAL

    @staticmethod
    def _label_for(reason: str, count) -> str:
        """生成人数状态标签，未知人数不显示为零。"""
        if reason == "empty":
            return "EMPTY count=0"
        if reason == "multiple":
            return f"MULTI count={count}"
        if reason == "normal":
            return "OK count=1"
        return "UNKNOWN"

    @staticmethod
    def _snapshot_reason(count: int | None) -> str:
        """把可选人数映射为未知、无人、单人或多人局部状态。"""
        if count is None:
            return "unknown"
        if count == 0:
            return "empty"
        if count == 1:
            return "normal"
        return "multiple"

    def get_monitor_status(self, camera_key: str) -> dict | None:
        """返回监控字典的浅拷贝，未产生结果时返回 None。"""
        value = self.monitor_status.get(camera_key)
        return dict(value) if value else None

    def _should_process_now(self, camera_id: int, cfg: dict) -> bool:
        if not super()._should_process_now(camera_id, cfg):
            return False
        if not self._can_sample(camera_id, cfg):
            self._invalidate_sample(camera_id)
            return False
        return True

    def _handle_alarm(self, camera_id: int, result: tuple, frame: np.ndarray | None):
        """即时更新通道判定，取证和分发由运行时后台执行。"""
        self.logistics_runtime.evaluate_after_camera_update(self.feature_name, camera_id)
