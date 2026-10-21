"""
inference/workers/yolo_detector.py

模型文件路径来自本机配置文件。同一物理权重由多个逻辑模型共享，例如:
    yolo_human → class_filter=[0],   type_label="person"
    yolo_phone → class_filter=[1],   type_label="phone"

两个函数：
    load_model():YOLO(path)
    infer():model.predict()、class_filter、转标准detections
"""
from __future__ import annotations
from typing import Any

from AiVision.core.logger import logger
from AiVision.inference.base_worker import BaseModelWorker

class YoloDetectorWorker(BaseModelWorker):
    """通用 YOLO 目标检测 Worker"""
    def load_model(self) -> Any:
        """校验本机权重并在子进程构造 YOLO；多个逻辑模型可共用该实例，任务参数仍分别读取。"""
        from AiVision.inference.model_paths import validate_model_path
        path = validate_model_path(self.model_path)
        from ultralytics import YOLO

        # 这里的路径是模型本机路径
        model = YOLO(path)

        logger.info(
            f"[YoloDetectorWorker:{self.model_name}] 已加载，服务逻辑模型 {self._queue_names}"
        )
        return model

    def infer(self, model: Any, frame, task_meta: dict) -> list[dict]:
        """按任务所属逻辑模型执行目标检测并过滤类别。

        Args:
            model: 已加载的 YOLO 实例。
            frame: 全帧或 ROI 的 BGR 图像。
            task_meta: 必须包含 model_name；conf/iou/imgsz 可覆盖注册表默认值。

        Returns:
            list[dict]: 输入图像坐标中的 bbox、confidence、class_id、type；无框返回空列表。
                class_labels 优先于统一 type_label，业务告警不在此判断。
        """
        # 让请求方在 task_meta 里覆盖默认 conf/iou（所以任务可以覆盖默认参数）
        from AiVision.inference.model_registry import get_model_spec
        # 同一个Worker收到不同任务时会动态选择不同配置
        spec = get_model_spec(task_meta["model_name"])
        conf = float(task_meta.get("conf", spec.conf))
        iou = float(task_meta.get("iou", spec.iou))
        predict_kwargs = {"conf": conf, "iou": iou, "verbose": False,
                          "imgsz": task_meta.get("imgsz", spec.imgsz)}
        results = model.predict(frame, **predict_kwargs)
        if not results:
            return []
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []

        out = []
        # 把GPUTensor转成普通Python数据
        boxes_xyxy = r.boxes.xyxy.cpu().numpy().tolist()
        confs = r.boxes.conf.cpu().numpy().tolist()
        cls_ids = r.boxes.cls.cpu().numpy().astype(int).tolist()
        class_labels = dict(spec.class_labels)
        # 把同一目标的框、置信度、类别ID绑在一起处理
        for bbox, score, cls_id in zip(boxes_xyxy, confs, cls_ids):
            if spec.class_filter is not None and cls_id not in spec.class_filter:
                continue
            # 统一输出
            out.append({
                "bbox": [float(x) for x in bbox],
                "confidence": float(score),
                "class_id": int(cls_id),
                "type": class_labels.get(cls_id, spec.type_label),
            })
        return out
