# pose.py
"""
姿态估计模块。

使用 YOLO-Pose 模型对整帧做一次推理，提取所有人体的关键点，
并将结果匹配到 YOLO 检测器输出的 track_id，供 BehaviorEngine 使用。

设计决策：
  - 全图单次推理而非逐人裁图推理：避免多次 GPU 调用开销，N 人时复杂度 O(1) 而非 O(N)。
  - 输出格式与原 MediaPipe 接口对齐（人体框内归一化坐标），BehaviorEngine 无需修改。
  - model_path 不存在时自动降级（enabled=False），跳过姿态估计不影响其他功能。

关键点索引遵循 COCO 17 关键点定义：
    0=鼻子, 5=左肩, 6=右肩, 9=左腕, 10=右腕
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
from ultralytics import YOLO

from .geometry import bbox_height
from .types import Detection


class PoseEstimator:
    """基于 YOLO-Pose 的姿态估计器。

    工作流程：
        1. infer_frame()：对整帧做一次姿态推理，获取全图所有人的关键点；
        2. _match_pose_to_person()：用 IoU 将姿态结果与检测器的 track_id 对齐；
        3. _extract_features()：从关键点计算 BehaviorEngine 所需的姿态特征。
    """

    # COCO 17 关键点索引常量，集中定义避免代码中散落魔法数字
    KP_NOSE = 0
    KP_LEFT_SHOULDER = 5
    KP_RIGHT_SHOULDER = 6
    KP_LEFT_WRIST = 9
    KP_RIGHT_WRIST = 10

    def __init__(
        self,
        model_path: str,
        device: str = "",
        imgsz: int = 640,
        half: bool = True,
    ):
        """
        Args:
            model_path: YOLO-Pose 权重文件路径（.pt）。
                        文件不存在时 enabled=False，infer_frame() 返回空字典。
            device:     推理设备，传给 Ultralytics。
            imgsz:      姿态模型输入尺寸。
            half:       CUDA 下是否使用 FP16。
        """
        self.model_path = model_path
        self.device = device
        self.imgsz = imgsz
        self.half = half
        self.enabled = Path(model_path).exists()    # 文件不存在时静默降级，不抛异常
        self.model = YOLO(model_path) if self.enabled else None

    def infer_frame(
        self,
        frame_bgr: np.ndarray,
        persons: List[Detection],
        conf: float = 0.3,
    ) -> Dict[int, Dict[str, float]]:
        """对整帧做一次姿态推理，返回按 track_id 索引的姿态特征字典。

        整帧单次推理后通过 IoU 匹配将姿态结果分配给各 track_id，
        比逐人裁图推理节省 N-1 次 GPU 调用。

        Args:
            frame_bgr: BGR 格式的原始视频帧。
            persons:   YOLO 检测器输出的人体检测列表，提供 bbox 与 track_id 用于匹配。
            conf:      姿态模型的关键点置信度阈值，低于此值的关键点不参与特征计算。

        Returns:
            {track_id: 特征字典} 的映射；未启用、无检测结果或匹配失败时返回空字典。
        """
        if not self.enabled or self.model is None or not persons:
            return {}

        # 全图单次推理：获取所有人的关键点与检测框
        results = self.model.predict(
            source=frame_bgr,
            conf=conf,
            iou=0.45,
            imgsz=self.imgsz,
            half=self.half,
            device=(self.device or None),
            verbose=False,
        )

        if not results or results[0].keypoints is None:
            return {}

        # kpts_data shape: (num_persons, 17, 3)，最后一维为 [x_px, y_px, conf]
        kpts_data = results[0].keypoints.data
        if kpts_data is None or len(kpts_data) == 0:
            return {}

        kpts_array = kpts_data.cpu().numpy()    # 转为 numpy 便于后续索引
        boxes_xyxy = (
            results[0].boxes.xyxy.cpu().numpy()
            if results[0].boxes is not None
            else None
        )

        if boxes_xyxy is None or len(boxes_xyxy) == 0:
            return {}

        h, w = frame_bgr.shape[:2]
        features: Dict[int, Dict[str, float]] = {}

        # 为每个带 track_id 的人体检测结果匹配最近的姿态估计输出
        for person in persons:
            if person.track_id is None:
                continue    # 无跟踪 ID 的目标无法跨帧关联，跳过

            pose_idx = self._match_pose_to_person(person.bbox, boxes_xyxy)
            if pose_idx is None:
                continue    # 未找到满足 IoU 阈值的匹配，跳过

            kpts = kpts_array[pose_idx]     # 取匹配的关键点数组 (17, 3)
            features[person.track_id] = self._extract_features(kpts, person, w, h)

        return features

    def _match_pose_to_person(
        self,
        person_bbox: tuple[int, int, int, int],
        pose_bboxes: np.ndarray,
    ) -> int | None:
        """用 IoU 将检测器的人体框与姿态模型的检测框对齐，返回最佳匹配的索引。

        姿态模型与检测器各自独立推理，同一人的输出框不完全重合，
        故用 IoU 而非中心点距离进行匹配，对遮挡和框偏移更鲁棒。
        IoU 低于 0.3 时视为无有效匹配，返回 None 避免错误关联。

        Args:
            person_bbox: 检测器输出的人体框 (x1, y1, x2, y2)。
            pose_bboxes: 姿态模型输出的所有人体框，形状 (N, 4)。

        Returns:
            匹配度最高且 IoU > 0.3 的框索引；无满足条件的匹配时返回 None。
        """
        if len(pose_bboxes) == 0:
            return None

        px1, py1, px2, py2 = person_bbox
        best_iou = 0.0
        best_idx = None

        for idx, pbox in enumerate(pose_bboxes):
            qx1, qy1, qx2, qy2 = pbox

            # 计算交集区域
            inter_x1 = max(px1, qx1)
            inter_y1 = max(py1, qy1)
            inter_x2 = min(px2, qx2)
            inter_y2 = min(py2, qy2)

            if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
                continue    # 无交集

            inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
            area_a = max(1, (px2 - px1) * (py2 - py1))     # max(1, ...) 防止零面积框导致除零
            area_b = max(1, (qx2 - qx1) * (qy2 - qy1))
            iou = inter / (area_a + area_b - inter)

            if iou > best_iou:
                best_iou = iou
                best_idx = idx

        return best_idx if best_iou > 0.3 else None    # IoU 阈值 0.3：低于此值视为错误匹配

    def _extract_features(
        self,
        kpts: np.ndarray,
        person: Detection,
        frame_w: int,
        frame_h: int,
    ) -> Dict[str, float]:
        """从 17 个关键点计算 BehaviorEngine 所需的姿态特征。

        输出格式与原 MediaPipe 接口对齐（人体框内归一化坐标），
        使 BehaviorEngine 无需感知底层姿态模型的替换。

        坐标归一化：YOLO-Pose 输出全图像素坐标，需转换为相对人体框的 [0, 1] 归一化坐标：
            norm_x = (x_px - bbox_x1) / bbox_w
            norm_y = (y_px - bbox_y1) / bbox_h

        任意核心关键点（鼻子、左肩、右肩）置信度低于 0.3 时返回空字典，
        宁可缺失特征也不使用低质量估计，避免误触发行为规则。

        Args:
            kpts:     单人关键点数组，形状 (17, 3)，最后一维为 [x_px, y_px, conf]。
            person:   对应的人体检测结果，提供 bbox 用于坐标归一化。
            frame_w:  帧宽度（像素），当前未使用，保留供后续扩展。
            frame_h:  帧高度（像素），当前未使用，保留供后续扩展。

        Returns:
            包含以下键的特征字典（均为 float）：
                nose_x          —— 鼻子横坐标（人体框内归一化）
                nose_y          —— 鼻子纵坐标（人体框内归一化）
                shoulder_y      —— 双肩中点纵坐标（人体框内归一化）
                head_down_ratio —— 鼻子与肩部的纵向差值，正值表示低头（范围 ≥ 0）
                shoulder_span   —— 双肩横向跨度（人体框宽度归一化），反映正面/侧面朝向
                person_h        —— 人体框高度（像素），供外部做尺度参考
            任意核心关键点置信度不足时返回空字典 {}。
        """
        x1, y1, x2, y2 = person.bbox
        person_w = max(1, x2 - x1)
        person_h = max(1, y2 - y1)

        nose = kpts[self.KP_NOSE]           # [x_px, y_px, conf]
        ls = kpts[self.KP_LEFT_SHOULDER]
        rs = kpts[self.KP_RIGHT_SHOULDER]

        # 核心关键点置信度过滤：任一不足 0.3 则整个特征字典作废
        if nose[2] < 0.3 or ls[2] < 0.3 or rs[2] < 0.3:
            return {}

        # 全图像素坐标 → 人体框内归一化坐标（对齐 MediaPipe 接口）
        nose_x_norm = (nose[0] - x1) / person_w
        nose_y_norm = (nose[1] - y1) / person_h
        shoulder_y_norm = ((ls[1] + rs[1]) / 2.0 - y1) / person_h  # 双肩中点
        shoulder_span = abs(ls[0] - rs[0]) / person_w

        # 低头程度：鼻子纵坐标 - 肩部纵坐标，正值表示鼻子低于肩部（即低头）
        head_down_ratio = max(0.0, nose_y_norm - shoulder_y_norm)

        return {
            "nose_x": float(nose_x_norm),
            "nose_y": float(nose_y_norm),
            "shoulder_y": float(shoulder_y_norm),
            "head_down_ratio": float(head_down_ratio),
            "shoulder_span": float(shoulder_span),
            "person_h": bbox_height(person.bbox),
        }

    def close(self) -> None:
        """释放模型占用的 GPU/CPU 内存，程序退出前调用。"""
        self.model = None
