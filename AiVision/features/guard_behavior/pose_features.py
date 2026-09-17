"""将原图 COCO 关键点与保安框匹配，提取局部行为所需的几何事实。"""
from __future__ import annotations

import math

from .state import BBox, TrackedPerson


KP_NOSE = 0
KP_LEFT_SHOULDER = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_WRIST = 9
KP_RIGHT_WRIST = 10
KEYPOINT_CONFIDENCE = 0.3
POSE_MATCH_IOU = 0.3


def bbox_iou(a: BBox, b: BBox) -> float:
    width = max(0., min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = max(0., a[2] - a[0]) * max(0., a[3] - a[1]) + max(0., b[2] - b[0]) * max(0., b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.


def extract_pose_features(person: TrackedPerson, keypoints: list) -> dict[str, float] | None:
    if len(keypoints) != 17 or any(len(point) != 3 for point in keypoints):
        raise ValueError("Pose 必须包含 17 个三维关键点")
    if any(not math.isfinite(float(value)) for point in keypoints for value in point):
        raise ValueError("Pose 关键点必须为有限数值")
    nose, left, right = (keypoints[index] for index in (KP_NOSE, KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER))
    if min(nose[2], left[2], right[2]) < KEYPOINT_CONFIDENCE:
        return None
    x1, y1, x2, y2 = person.bbox
    width, height = max(1., x2 - x1), max(1., y2 - y1)
    nose_y = (nose[1] - y1) / height
    shoulder_y = ((left[1] + right[1]) / 2 - y1) / height
    return {
        "nose_x": float((nose[0] - x1) / width),
        "nose_y": float(nose_y),
        "shoulder_y": float(shoulder_y),
        "head_down_ratio": float(max(0., nose_y - shoulder_y)),
        "shoulder_span": float(abs(left[0] - right[0]) / width),
        "person_h": float(height),
    }


def match_pose_features(persons: list[TrackedPerson], detections: list[dict]) -> dict[int, dict[str, float]]:
    features = {}
    for person in persons:
        if person.track_id is None or not detections:
            continue
        best = max(detections, key=lambda pose: bbox_iou(person.bbox, pose["bbox"]))
        if bbox_iou(person.bbox, best["bbox"]) <= POSE_MATCH_IOU:
            continue
        values = extract_pose_features(person, best["keypoints"])
        if values is not None:
            features[person.track_id] = values
    return features
