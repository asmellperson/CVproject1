# 文件说明：实现目标跟踪相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/_base/tracking.py
通用 IOU 多目标跟踪器 — 消除 detect_face / detect_human 里完全相同的 Track / Tracker 重复实现。
一份 IouTracker 通用实现,两个 feature 直接复用。
"""
from __future__ import annotations
import time
from dataclasses import dataclass


# 功能：计算两个 bbox 的 IoU,bbox 格式 [x1, y1, x2, y2]；输入与输出详见下方说明
# 参数：
#   - `box_a`（list[float]）：`box_a` 对应的业务输入值
#   - `box_b`（list[float]）：`box_b` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/tracking.py` 的 `IouTracker::_match_score` 调用本符号
#   - 内部调用：`max`、`min`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def iou(box_a: list[float], box_b: list[float]) -> float:
    """计算两个 bbox 的 IoU,bbox 格式 [x1, y1, x2, y2]"""
    x1, y1, x2, y2 = box_a
    x1p, y1p, x2p, y2p = box_b
    xi1, yi1 = max(x1, x1p), max(y1, y1p)
    xi2, yi2 = min(x2, x2p), min(y2, y2p)
    inter = max(0.0, xi2 - xi1) * max(0.0, yi2 - yi1)
    area_a = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_b = max(0.0, x2p - x1p) * max(0.0, y2p - y1p)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


# 功能：单个跟踪轨迹；输入与输出详见下方说明
# 参数：
#   - `bbox`（list[float]）：`bbox` 对应的业务输入值
#   - `first_seen`（float）：`first_seen` 对应的业务输入值
#   - `last_seen`（float）：`last_seen` 对应的业务输入值
#   - `velocity`（tuple[float, float]）：`velocity` 对应的业务输入值
#   - `lost`（int）：`lost` 对应的业务输入值
#   - `alarmed`（bool）：`alarmed` 对应的业务输入值
# 返回：Track；返回新建的 `Track` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class Track:
    """单个跟踪轨迹"""
    bbox: list[float]
    first_seen: float
    last_seen: float
    velocity: tuple[float, float] = (0.0, 0.0)
    lost: int = 0
    alarmed: bool = False

    # 功能：创建或构建 `new` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `bbox`（list[float]）：`bbox` 对应的业务输入值
    # 返回：'Track'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/tracking.py` 的 `IouTracker::update` 调用本符号
    #   - 内部调用：`time.time`、`cls`、`list`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @classmethod
    def new(cls, bbox: list[float]) -> "Track":
        now = time.time()
        return cls(bbox=list(bbox), first_seen=now, last_seen=now)

    # 功能：更新或保存 `update` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `bbox`（list[float]）：`bbox` 对应的业务输入值
    #   - `smooth_alpha`（float）：`smooth_alpha` 对应的业务输入值；默认值为 `0.7`
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`box_center`、`smooth_box`、`list`、`time.time`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def update(self, bbox: list[float], smooth_alpha: float = 0.7):
        old_cx, old_cy = box_center(self.bbox)
        new_cx, new_cy = box_center(bbox)
        self.velocity = (new_cx - old_cx, new_cy - old_cy)
        self.bbox = smooth_box(self.bbox, list(bbox), smooth_alpha)
        self.last_seen = time.time()
        self.lost = 0

    # 功能：实现 `step_lost` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/tracking.py` 的 `IouTracker::update` 调用本符号
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def step_lost(self):
        self.lost += 1
        if self.lost > 0:
            vx, vy = self.velocity
            self.bbox = [self.bbox[0] + vx, self.bbox[1] + vy, self.bbox[2] + vx, self.bbox[3] + vy]

    # 功能：实现 `dwell_time` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def dwell_time(self) -> float:
        return self.last_seen - self.first_seen


# 功能：基于 IoU + 中心点距离 + 面积变化的轻量多目标跟踪器；输入与输出详见下方说明
# 参数：
#   - `iou_thr`（float）：`iou_thr` 对应的业务输入值；默认值为 `0.3`
#   - `max_lost`（int）：`max_lost` 对应的业务输入值；默认值为 `5`
#   - `center_dist_thr`（float）：`center_dist_thr` 对应的业务输入值；默认值为 `0.65`
#   - `area_ratio_thr`（float）：`area_ratio_thr` 对应的业务输入值；默认值为 `0.55`
#   - `match_score_thr`（float）：`match_score_thr` 对应的业务输入值；默认值为 `0.35`
#   - `smooth_alpha`（float）：`smooth_alpha` 对应的业务输入值；默认值为 `0.7`
# 返回：IouTracker；返回新建的 `IouTracker` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class IouTracker:
    """基于 IoU + 中心点距离 + 面积变化的轻量多目标跟踪器
    
    用法:
        tracker = IouTracker(iou_thr=0.3, max_lost=5)
        for frame in stream:
            detections = [{"bbox": [...]}, ...]
            tracks = tracker.update(detections)
            for tid, track in tracks.items():
                if track.dwell_time > 10 and not track.alarmed:
                    ...告警...
                    track.alarmed = True
    """

    # 功能：初始化或配置 `__init__` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `iou_thr`（float）：`iou_thr` 对应的业务输入值；默认值为 `0.3`
    #   - `max_lost`（int）：`max_lost` 对应的业务输入值；默认值为 `5`
    #   - `center_dist_thr`（float）：`center_dist_thr` 对应的业务输入值；默认值为 `0.65`
    #   - `area_ratio_thr`（float）：`area_ratio_thr` 对应的业务输入值；默认值为 `0.55`
    #   - `match_score_thr`（float）：`match_score_thr` 对应的业务输入值；默认值为 `0.35`
    #   - `smooth_alpha`（float）：`smooth_alpha` 对应的业务输入值；默认值为 `0.7`
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(
        self,
        iou_thr: float = 0.3,
        max_lost: int = 5,
        center_dist_thr: float = 0.65,
        area_ratio_thr: float = 0.55,
        match_score_thr: float = 0.35,
        smooth_alpha: float = 0.7,
    ):
        self.iou_thr = iou_thr
        self.max_lost = max_lost
        self.center_dist_thr = center_dist_thr
        self.area_ratio_thr = area_ratio_thr
        self.match_score_thr = match_score_thr
        self.smooth_alpha = smooth_alpha
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    # 功能：用当前帧检测结果刷新所有轨迹；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `detections`（list[dict]）：`detections` 对应的业务输入值
    # 返回：dict[int, Track]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`set`、`self._tracks.items`、`enumerate`、`self._match_score`、`candidates.append`、`sorted`、`self._tracks[tid].update`、`used_tracks.add`、`used_detections.add`、`list`
    #          等共 12 个调用。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def update(self, detections: list[dict]) -> dict[int, Track]:
        """用当前帧检测结果刷新所有轨迹。
        
        detections: [{"bbox": [x1,y1,x2,y2], ...}, ...]
        返回更新后的 {track_id: Track}
        """
        used_tracks: set[int] = set()
        used_detections: set[int] = set()
        candidates = []

        for tid, trk in self._tracks.items():
            for det_idx, det in enumerate(detections):
                score = self._match_score(trk.bbox, det["bbox"])
                if score >= self.match_score_thr:
                    candidates.append((score, tid, det_idx))

        for _score, tid, det_idx in sorted(candidates, key=lambda item: item[0], reverse=True):
            if tid in used_tracks or det_idx in used_detections or tid not in self._tracks:
                continue
            self._tracks[tid].update(detections[det_idx]["bbox"], smooth_alpha=self.smooth_alpha)
            used_tracks.add(tid)
            used_detections.add(det_idx)

        for tid, trk in list(self._tracks.items()):
            if tid in used_tracks:
                continue
            trk.step_lost()
            if trk.lost > self.max_lost:
                del self._tracks[tid]

        # 2) 未匹配的检测开新轨迹
        for i, det in enumerate(detections):
            if i not in used_detections:
                self._tracks[self._next_id] = Track.new(det["bbox"])
                self._next_id += 1

        return self._tracks

    # 功能：实现 `_match_score` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `track_box`（list[float]）：`track_box` 对应的业务输入值
    #   - `det_box`（list[float]）：`det_box` 对应的业务输入值
    # 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/features/_base/tracking.py` 的 `IouTracker::update` 调用本符号
    #   - 内部调用：`iou`、`min`、`center_distance_ratio`、`max`、`area_similarity`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def _match_score(self, track_box: list[float], det_box: list[float]) -> float:
        iou_score = iou(track_box, det_box)
        center_score = 1.0 - min(1.0, center_distance_ratio(track_box, det_box) / max(self.center_dist_thr, 1e-6))
        area_score = area_similarity(track_box, det_box)
        if iou_score < self.iou_thr and (center_score <= 0 or area_score < self.area_ratio_thr):
            return 0.0
        return 0.55 * iou_score + 0.30 * center_score + 0.15 * area_score

    # 功能：实现 `tracks` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[int, Track]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def tracks(self) -> dict[int, Track]:
        return self._tracks

    # 功能：实现 `reset` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._tracks.clear`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def reset(self):
        self._tracks.clear()
        self._next_id = 1


# 功能：实现 `box_center` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `box`（list[float]）：`box` 对应的业务输入值
# 返回：tuple[float, float]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/tracking.py` 的 `Track::update` 调用本符号；`AiVision/features/_base/tracking.py` 的
#         `center_distance_ratio` 调用本符号
#   - 内部调用：`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def box_center(box: list[float]) -> tuple[float, float]:
    return ((float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0)


# 功能：实现 `box_area` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `box`（list[float]）：`box` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/tracking.py` 的 `area_similarity` 调用本符号
#   - 内部调用：`max`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def box_area(box: list[float]) -> float:
    return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))


# 功能：实现 `center_distance_ratio` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `box_a`（list[float]）：`box_a` 对应的业务输入值
#   - `box_b`（list[float]）：`box_b` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/tracking.py` 的 `IouTracker::_match_score` 调用本符号
#   - 内部调用：`box_center`、`max`、`float`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def center_distance_ratio(box_a: list[float], box_b: list[float]) -> float:
    ax, ay = box_center(box_a)
    bx, by = box_center(box_b)
    aw = max(1.0, float(box_a[2]) - float(box_a[0]))
    ah = max(1.0, float(box_a[3]) - float(box_a[1]))
    scale = max(aw, ah, 1.0)
    return (((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5) / scale


# 功能：实现 `area_similarity` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `box_a`（list[float]）：`box_a` 对应的业务输入值
#   - `box_b`（list[float]）：`box_b` 对应的业务输入值
# 返回：float；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/tracking.py` 的 `IouTracker::_match_score` 调用本符号
#   - 内部调用：`box_area`、`min`、`max`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def area_similarity(box_a: list[float], box_b: list[float]) -> float:
    area_a = box_area(box_a)
    area_b = box_area(box_b)
    if area_a <= 0 or area_b <= 0:
        return 0.0
    return min(area_a, area_b) / max(area_a, area_b)


# 功能：实现 `smooth_box` 对应的目标跟踪逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `old_box`（list[float]）：`old_box` 对应的业务输入值
#   - `new_box`（list[float]）：`new_box` 对应的业务输入值
#   - `alpha`（float）：`alpha` 对应的业务输入值
# 返回：list[float]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/features/_base/tracking.py` 的 `Track::update` 调用本符号
#   - 内部调用：`max`、`min`、`float`、`zip`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def smooth_box(old_box: list[float], new_box: list[float], alpha: float) -> list[float]:
    alpha = max(0.0, min(1.0, float(alpha)))
    return [
        float(old_value) * (1.0 - alpha) + float(new_value) * alpha
        for old_value, new_value in zip(old_box, new_box)
    ]
