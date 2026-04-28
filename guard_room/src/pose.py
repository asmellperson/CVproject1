# pose.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
from ultralytics import YOLO

from .geometry import bbox_height
from .types import Detection


class PoseEstimator:
    """
    基于 YOLO-Pose 的姿态估计器。
    一次推理拿全图所有人的关键点,按 person bbox 匹配。
    """
    
    # COCO 17 keypoint 索引
    KP_NOSE = 0
    KP_LEFT_SHOULDER = 5
    KP_RIGHT_SHOULDER = 6
    KP_LEFT_WRIST = 9
    KP_RIGHT_WRIST = 10
    
    def __init__(self, model_path: str):
        self.enabled = Path(model_path).exists()
        self.model_path = model_path
        self.model = None
        
        if self.enabled:
            self.model = YOLO(model_path)
    
    def infer_frame(
        self,
        frame_bgr: np.ndarray,
        persons: List[Detection],
        conf: float = 0.3,
    ) -> Dict[int, Dict[str, float]]:
        """
        对整帧做一次姿态推理,返回按 track_id 索引的特征字典。
        persons: 来自 YOLO detect 的人体检测结果,用于匹配 pose 结果和 track_id
        """
        if not self.enabled or self.model is None or not persons:
            return {}
        
        # YOLO-Pose 全图推理
        results = self.model.predict(
            source=frame_bgr,
            conf=conf,
            iou=0.45,
            imgsz=640,
            verbose=False,
        )
        
        if not results or results[0].keypoints is None:
            return {}
        
        # kpts shape: (num_persons, 17, 2 or 3) -- (num, 17, xy) 或 (num, 17, xyc)
        kpts_data = results[0].keypoints.data  # tensor
        if kpts_data is None or len(kpts_data) == 0:
            return {}
        
        kpts_array = kpts_data.cpu().numpy()   # (N, 17, 3) = [x, y, conf]
        boxes_xyxy = results[0].boxes.xyxy.cpu().numpy() if results[0].boxes is not None else None
        
        if boxes_xyxy is None or len(boxes_xyxy) == 0:
            return {}
        
        h, w = frame_bgr.shape[:2]
        features: Dict[int, Dict[str, float]] = {}
        
        # 对每个 person 检测结果,找最匹配的 pose 结果
        for person in persons:
            if person.track_id is None:
                continue
            
            pose_idx = self._match_pose_to_person(person.bbox, boxes_xyxy)
            if pose_idx is None:
                continue
            
            kpts = kpts_array[pose_idx]  # (17, 3)
            features[person.track_id] = self._extract_features(kpts, person, w, h)
        
        return features
    
    def _match_pose_to_person(
        self,
        person_bbox: tuple[int, int, int, int],
        pose_bboxes: np.ndarray,
    ) -> int | None:
        """用 IoU 找匹配度最高的 pose 检测结果"""
        if len(pose_bboxes) == 0:
            return None
        
        px1, py1, px2, py2 = person_bbox
        best_iou = 0.0
        best_idx = None
        
        for idx, pbox in enumerate(pose_bboxes):
            qx1, qy1, qx2, qy2 = pbox
            
            inter_x1 = max(px1, qx1)
            inter_y1 = max(py1, qy1)
            inter_x2 = min(px2, qx2)
            inter_y2 = min(py2, qy2)
            
            if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
                continue
            
            inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
            area_a = max(1, (px2 - px1) * (py2 - py1))
            area_b = max(1, (qx2 - qx1) * (qy2 - qy1))
            iou = inter / (area_a + area_b - inter)
            
            if iou > best_iou:
                best_iou = iou
                best_idx = idx
        
        return best_idx if best_iou > 0.3 else None
    
    def _extract_features(
        self,
        kpts: np.ndarray,
        person: Detection,
        frame_w: int,
        frame_h: int,
    ) -> Dict[str, float]:
        """
        从 17 个关键点提取本项目需要的特征。
        返回的格式要和原 MediaPipe 版本兼容,让 behavior.py 不用改。
        """
        x1, y1, x2, y2 = person.bbox
        person_w = max(1, x2 - x1)
        person_h = max(1, y2 - y1)
        
        nose = kpts[self.KP_NOSE]          # [x_px, y_px, conf]
        ls = kpts[self.KP_LEFT_SHOULDER]
        rs = kpts[self.KP_RIGHT_SHOULDER]
        
        # 关键点置信度不够就返回空
        if nose[2] < 0.3 or ls[2] < 0.3 or rs[2] < 0.3:
            return {}
        
        # 归一化到 person bbox 内 (对齐原 MediaPipe 接口)
        # MediaPipe 返回的是 person crop 内的 [0,1] 归一化坐标
        # YOLO-Pose 返回的是全图像素坐标,要转回 person 内的归一化坐标
        nose_x_norm = (nose[0] - x1) / person_w
        nose_y_norm = (nose[1] - y1) / person_h
        shoulder_y_norm = ((ls[1] + rs[1]) / 2.0 - y1) / person_h
        shoulder_span = abs(ls[0] - rs[0]) / person_w
        
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
        self.model = None