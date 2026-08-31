# 文件说明：实现`__init__` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""platform/inference/workers/ — 推理 Worker 实现"""
from .yolo_detector import YoloDetectorWorker

__all__ = ["YoloDetectorWorker"]
