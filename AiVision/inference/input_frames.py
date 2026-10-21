"""在投递 YOLO 检测任务前缩小传输图像，并恢复原始输入坐标。"""

import cv2


def prepare_inference_task(task: dict) -> dict:
    """只提前完成 YOLO 检测原本就需要的等比例缩小，不放大小图。"""
    from .model_registry import MODEL_SPECS

    spec = MODEL_SPECS.get(task["model_name"])
    if spec is None or spec.type != "yolo":
        return task
    frame = task["frame"]
    height, width = frame.shape[:2]
    size = int(task.get("imgsz", spec.imgsz))
    if min(height, width, size) <= 0 or max(height, width) <= size:
        return task
    ratio = size / max(height, width)
    resized = cv2.resize(frame, (max(1, round(width * ratio)), max(1, round(height * ratio))))
    # 完整画面仍由 Consumer 持有；队列只传小图和恢复坐标所需的尺寸。
    return {**task, "frame": resized, "source_frame_shape": (height, width)}


def restore_detection_coordinates(detections: list[dict], task: dict) -> list[dict]:
    """把缩小图上的检测框还原到原 ROI，保证跟踪、区域判断和画框使用原坐标。"""
    source_shape = task.get("source_frame_shape")
    if source_shape is None:
        return detections
    source_height, source_width = source_shape
    height, width = task["frame"].shape[:2]
    scale_x, scale_y = source_width / width, source_height / height
    restored = []
    for detection in detections:
        x1, y1, x2, y2 = detection["bbox"]
        restored.append({
            **detection,
            "bbox": [
                max(0.0, min(float(source_width), x1 * scale_x)),
                max(0.0, min(float(source_height), y1 * scale_y)),
                max(0.0, min(float(source_width), x2 * scale_x)),
                max(0.0, min(float(source_height), y2 * scale_y)),
            ],
        })
    return restored
