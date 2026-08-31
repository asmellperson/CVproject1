# 文件说明：实现`yolo_detector` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
platform/inference/workers/yolo_detector.py
通用 YOLO 检测 Worker — 一个类替代旧代码假设的
yolo_face_worker.py / yolo_phone_worker.py / yolo_human_worker.py。

模型文件路径来自本机配置文件，不再使用 ai_model.path 作为加载依据。

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


# 功能：通用 YOLO 目标检测 Worker；输入与输出详见下方说明
# 参数：无。
# 返回：YoloDetectorWorker；返回新建的 `YoloDetectorWorker` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class YoloDetectorWorker(BaseModelWorker):
    """通用 YOLO 目标检测 Worker"""

    # 功能：读取或查询 `load_model` 对应的`yolo_detector` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Any；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`YOLO`、`self._parse_meta`、`set`、`meta.get`、`float`、`logger.info`。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
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

    # 功能：转换或规范化 `_parse_meta` 对应的`yolo_detector` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/platform/inference/workers/yolo_detector.py` 的 `YoloDetectorWorker::load_model` 调用本符号
    #   - 内部调用：`self.model_cfg.get`、`json.loads`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _parse_meta(self) -> dict:
        desc = self.model_cfg.get("description") or ""
        try:
            return json.loads(desc)
        except (ValueError, TypeError):
            return {}

    # 功能：实现 `infer` 对应的`yolo_detector` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `model`（Any）：模型配置或实例
    #   - `frame`（未显式标注）：待处理的视频图像帧
    #   - `task_meta`（dict）：`task_meta` 对应的业务输入值
    # 返回：list[dict]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`float`、`task_meta.get`、`model.predict`、`len`、`r.boxes.xyxy.cpu().numpy().tolist`、`r.boxes.xyxy.cpu().numpy`、`r.boxes.xyxy.cpu`、`r.boxes.conf.cpu().numpy().tolist`、`r.boxes.conf.cpu().numpy`、`r.boxes.conf.cpu`
    #          等共 17 个调用。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
