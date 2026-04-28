"""
platform/inference/workers/yolo_detector.py
通用 YOLO 检测 Worker — 一个类替代旧代码假设的
yolo_face_worker.py / yolo_phone_worker.py / yolo_human_worker.py。

通过 ai_model 表的 path 字段加载实际模型(代码不写死路径,以数据库为准)。

每个数据库 ai_model 行可以在 description 字段或新增 extra 字段配置 class_filter,
比如 person_phone.pt 同时检测人和手机时:
    yolo_human → class_filter=[0],   type_label="person"
    yolo_phone → class_filter=[1],   type_label="phone"

为简化首版,class_filter 通过 model_cfg 的 description 字段约定:
    description 为 JSON 字符串,如 '{"class_filter": [0], "type_label": "person"}'
若 description 不是合法 JSON,则不过滤。
"""
from __future__ import annotations
import json
from typing import Any

from core.logger import logger
from platform.inference.base_worker import BaseModelWorker


class YoloDetectorWorker(BaseModelWorker):
    """通用 YOLO 目标检测 Worker"""

    def load_model(self) -> Any:
        from ultralytics import YOLO

        model = YOLO(self.model_path)

        # 解析 description 里的可选过滤参数
        meta = self._parse_meta()
        self._class_filter: set[int] | None = (
            set(meta["class_filter"]) if "class_filter" in meta else None
        )
        self._type_label: str = meta.get("type_label", "object")
        self._default_conf: float = float(meta.get("conf", 0.3))
        self._default_iou: float = float(meta.get("iou", 0.5))

        logger.info(
            f"[YoloDetectorWorker:{self.model_name}] 已加载 "
            f"class_filter={self._class_filter} type_label={self._type_label}"
        )
        return model

    def _parse_meta(self) -> dict:
        desc = self.model_cfg.get("description") or ""
        try:
            return json.loads(desc)
        except (ValueError, TypeError):
            return {}

    def infer(self, model: Any, frame, task_meta: dict) -> list[dict]:
        # 让请求方在 task_meta 里覆盖默认 conf/iou
        conf = float(task_meta.get("conf", self._default_conf))
        iou = float(task_meta.get("iou", self._default_iou))

        results = model.predict(
            frame,
            conf=conf,
            iou=iou,
            verbose=False,
        )
        if not results:
            return []
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []

        out = []
        boxes_xyxy = r.boxes.xyxy.cpu().numpy().tolist()
        confs = r.boxes.conf.cpu().numpy().tolist()
        cls_ids = r.boxes.cls.cpu().numpy().astype(int).tolist()

        for bbox, score, cls_id in zip(boxes_xyxy, confs, cls_ids):
            if self._class_filter is not None and cls_id not in self._class_filter:
                continue
            out.append({
                "bbox": [float(x) for x in bbox],
                "confidence": float(score),
                "class_id": int(cls_id),
                "type": self._type_label,
            })
        return out
