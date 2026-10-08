"""人体姿态 Worker，将单帧 YOLO Pose 输出转换为统一检测结构。

输出框和 COCO 17 关键点使用输入图像像素坐标，包含每个关键点的置信度。
框与关键点数量必须一致，结构异常抛错，不能通过 zip 截断伪装为有效检测。
"""
from __future__ import annotations

from typing import Any

from AiVision.inference.base_worker import BaseModelWorker


class YoloPoseWorker(BaseModelWorker):
    """为保安行为规则提供人体框与关键点的模型执行器，不直接判断趴睡。"""
    def load_model(self) -> Any:
        """校验权重路径并按 pose 任务加载本地 YOLO。"""
        from AiVision.inference.model_paths import validate_model_path

        path = validate_model_path(self.model_path, model_type="yolo_pose")
        from ultralytics import YOLO

        return YOLO(path, task="pose")

    def infer(self, model: Any, frame, task_meta: dict) -> list[dict]:
        """合并任务与注册表阈值，验证单帧输出形状后返回框和 17×3 关键点；异常结构抛出 ValueError。"""
        from AiVision.inference.model_registry import get_model_spec

        spec = get_model_spec(task_meta["model_name"])
        predict_kwargs = {
            "conf": float(task_meta.get("conf", spec.conf)),
            "iou": float(task_meta.get("iou", spec.iou)),
            "verbose": False,
        }
        if "imgsz" in task_meta:
            predict_kwargs["imgsz"] = task_meta["imgsz"]
        results = model.predict(frame, **predict_kwargs)
        if not results:
            return []
        if len(results) != 1:
            raise ValueError("姿态模型单帧结果数量异常")
        result = results[0]
        boxes, keypoints = result.boxes, result.keypoints
        count = 0 if boxes is None else len(boxes)
        if keypoints is None:
            if count:
                raise ValueError("姿态模型结果缺少关键点")
            return []
        # data 是原图像素坐标；禁止用 zip 截断不匹配的框和关键点。
        points = keypoints.data.cpu().numpy()
        if points.shape != (count, 17, 3):
            raise ValueError(f"姿态模型关键点形状异常: {points.shape}，期望 {(count, 17, 3)}")
        if not count:
            return []
        bboxes = boxes.xyxy.cpu().numpy()
        scores = boxes.conf.cpu().numpy()
        classes = boxes.cls.cpu().numpy()
        if bboxes.shape != (count, 4) or scores.shape != (count,) or classes.shape != (count,):
            raise ValueError("姿态模型检测框形状异常")
        return [{
            "bbox": [float(value) for value in bboxes[index]],
            "confidence": float(scores[index]),
            "class_id": int(classes[index]),
            "type": spec.type_label,
            "keypoints": [[float(value) for value in point] for point in points[index]],
        } for index in range(count)]
