# 文件说明：实现视频帧消费与检测的帧消费、判定与告警衔接逻辑。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
features/phone_detection/consumer.py
手机检测 — 手机框需经过人体关联、连续命中与持续时间确认后告警。
"""
from __future__ import annotations
import time
import cv2

from AiVision.features._shared.consumer import BaseFunctionConsumer

class PhoneConsumer(BaseFunctionConsumer):
    """手机检测 — 过滤孤立手机框，降低桌面手机、反光、背景误报。"""

    PERSON_MODEL_NAME = "yolo_human"

    def __init__(self, *args, **kwargs):
        """初始化摄像头独立的手机轨迹与编号，隔离多路视频的确认状态。"""
        super().__init__(*args, **kwargs)
        self._tracks: dict[int, dict[int, dict]] = {}
        self._next_track_id: dict[int, int] = {}

    def _process(self, roi, camera_id):
        """检测手机并按可用的人体结果进行关联，再用时间和命中数确认。

        人体关联仅在配置要求且人体模型队列存在时执行；返回是否有已确认
        候选及候选详情，详情中的检测框仍使用 ROI 坐标。
        """
        if not self.spec.required_models:
            return False, None
        cfg = self.config_cache[camera_id]
        conf_thr = cfg["CONF_THRESHOLD"]
        iou_thr = cfg["IOU_THR"]
        require_person = cfg["REQUIRE_PERSON_ASSOCIATION"]
        person_available = self.PERSON_MODEL_NAME in self.infer_dict
        model_name = self.spec.required_models[0]
        phone_result = self.dispatch_inference_sync(
            camera_id,
            model_name,
            roi,
            task_meta={"conf": conf_thr, "iou": iou_thr},
        )
        person_result = {}
        if require_person and person_available:
            person_result = self.dispatch_inference_sync(
                camera_id,
                self.PERSON_MODEL_NAME,
                roi,
                task_meta={
                    "conf": cfg["PERSON_CONF_THRESHOLD"],
                    "iou": cfg["PERSON_IOU_THR"],
                },
                timeout=0.6,
            )

        if phone_result.get("status") != "ok" or (
            require_person and person_available and person_result.get("status") != "ok"
        ):
            return False, None
        now = time.time()
        phones = phone_result.get("detections", []) or []
        persons = person_result.get("detections", []) or []
        ox, oy = self._get_roi_offset(camera_id)
        candidates = self._qualified_phone_detections(
            camera_id=camera_id,
            detections=phones,
            persons=persons,
            offset=(ox, oy),
            cfg=cfg,
            now=now,
            enforce_person=require_person and person_available,
        )
        self._prune_tracks(camera_id, now, cfg["TRACK_TTL_SECONDS"])
        return any(item.get("confirmed") for item in candidates), candidates

    def _build_monitor_snapshot(self, camera_id, result):
        alarm, candidates = result
        if candidates is None:
            return {"count": None, "alarm": False, "reason": "inference_error", "details": []}
        return {"count": len(candidates), "alarm": bool(alarm),
                "reason": "phone_confirmed" if alarm else "confirming" if candidates else "normal",
                "threshold_seconds": self.config_cache[camera_id]["MIN_CONFIRM_SECONDS"],
                "duration_seconds": max((item["duration"] for item in candidates), default=0),
                "details": [{"label": f"手机轨迹 {item['track_id']}", "confidence": item.get("confidence"),
                             "state": "phone_confirmed" if item["confirmed"] else "confirming",
                             "duration_seconds": item["duration"], "hits": item["hits"]} for item in candidates]}

    def post_process(self, camera_id, result):
        """将 ROI 检测框还原到原帧，区分候选手机与已经确认的手机。"""
        frame_copy = self._annotated_frame(camera_id)
        if frame_copy is None:
            return None
        ox, oy = self._get_roi_offset(camera_id)
        _alarm, detections = result
        for det in detections or []:
            bbox = det.get("bbox", [])
            if len(bbox) < 4:
                continue
            x1, y1, x2, y2 = (
                int(bbox[0]) + ox, int(bbox[1]) + oy,
                int(bbox[2]) + ox, int(bbox[3]) + oy,
            )
            conf = det.get("confidence", 0)
            confirmed = bool(det.get("confirmed"))
            color = (0, 255, 0) if confirmed else (0, 191, 255)
            label = "phone" if confirmed else "phone?"
            cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame_copy,
                f"{label} {conf:.2f} {int(det.get('hits', 1))}x",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
        return frame_copy

    def _process_static_frames(self, camera_id: int, cfg: dict) -> bool:
        """继续检查静止画面，使持续拿手机的行为能够累计确认时间。"""
        return True

    def _on_roi_changed(self, camera_id: int) -> None:
        """区域变更后清空手机轨迹，避免不同坐标空间之间继续匹配。"""
        super()._on_roi_changed(camera_id)
        self._tracks.pop(camera_id, None)
        self._next_track_id.pop(camera_id, None)

    def _qualified_phone_detections(
        self,
        *,
        camera_id: int,
        detections: list[dict],
        persons: list[dict],
        offset: tuple[int, int],
        cfg: dict,
        now: float,
        enforce_person: bool,
    ) -> list[dict]:
        """过滤不符合人体关联要求的框，并附加轨迹、命中次数与确认状态。"""
        out = []
        for det in detections:
            bbox = det.get("bbox", [])
            if len(bbox) < 4:
                continue
            global_bbox = self._offset_bbox(bbox, offset)
            if enforce_person and not self._is_near_person_hand_region(global_bbox, persons, offset, cfg):
                continue
            track = self._update_track(camera_id, global_bbox, now, cfg)
            duration = now - float(track["first_seen"])
            confirmed = (
                int(track["hits"]) >= cfg["MIN_CONSECUTIVE_HITS"]
                and duration >= cfg["MIN_CONFIRM_SECONDS"]
            )
            out.append({
                **det,
                "track_id": track["id"],
                "hits": track["hits"],
                "duration": round(duration, 2),
                "confirmed": confirmed,
                "person_associated": enforce_person,
            })
        return out

    @staticmethod
    def _offset_bbox(bbox, offset: tuple[int, int]) -> tuple[float, float, float, float]:
        """把 ROI 内坐标转换为原帧坐标，供人体关联和跨帧跟踪使用。"""
        ox, oy = offset
        return (
            float(bbox[0]) + ox,
            float(bbox[1]) + oy,
            float(bbox[2]) + ox,
            float(bbox[3]) + oy,
        )

    def _is_near_person_hand_region(self, phone_bbox, persons: list[dict], offset: tuple[int, int], cfg: dict) -> bool:
        """用扩展人体区域判断手机中心或覆盖比例，不依赖真实手部关键点。"""
        expand = cfg["PERSON_EXPAND_RATIO"]
        max_y_ratio = cfg["HAND_REGION_MAX_Y_RATIO"]
        pcx = (phone_bbox[0] + phone_bbox[2]) / 2.0
        pcy = (phone_bbox[1] + phone_bbox[3]) / 2.0

        for person in persons:
            bbox = person.get("bbox", [])
            if len(bbox) < 4:
                continue
            x1, y1, x2, y2 = self._offset_bbox(bbox, offset)
            width = max(1.0, x2 - x1)
            height = max(1.0, y2 - y1)
            ex1 = x1 - width * expand
            ex2 = x2 + width * expand
            ey1 = y1 - height * expand
            ey2 = y1 + height * max_y_ratio
            if ex1 <= pcx <= ex2 and ey1 <= pcy <= ey2:
                return True
            if self._intersection_ratio(phone_bbox, (ex1, ey1, ex2, ey2)) >= cfg["MIN_PERSON_PHONE_OVERLAP"]:
                return True
        return False

    def _update_track(self, camera_id: int, bbox, now: float, cfg: dict) -> dict:
        """匹配首个重叠或邻近轨迹；超过容忍间隔时重新累计持续时间和次数。"""
        tracks = self._tracks.setdefault(camera_id, {})
        match = None
        min_iou = cfg["TRACK_IOU_THRESHOLD"]
        for track in tracks.values():
            if self._iou(bbox, track["bbox"]) >= min_iou or self._center_distance_ratio(bbox, track["bbox"]) <= 0.6:
                match = track
                break

        if match is None:
            track_id = self._next_track_id.get(camera_id, 1)
            self._next_track_id[camera_id] = track_id + 1
            match = {"id": track_id, "bbox": bbox, "first_seen": now, "last_seen": now, "hits": 0}
            tracks[track_id] = match
        elif now - float(match.get("last_seen", 0.0)) > cfg["MAX_MISSED_SECONDS"]:
            match["first_seen"] = now
            match["hits"] = 0

        match["bbox"] = bbox
        match["last_seen"] = now
        match["hits"] = int(match.get("hits", 0)) + 1
        return match

    def _prune_tracks(self, camera_id: int, now: float, ttl: float):
        """按最近观测时间清除过期轨迹，限制历史状态占用。"""
        tracks = self._tracks.get(camera_id)
        if not tracks:
            return
        stale = [track_id for track_id, track in tracks.items() if now - float(track.get("last_seen", 0.0)) > ttl]
        for track_id in stale:
            tracks.pop(track_id, None)

    @staticmethod
    def _area(bbox) -> float:
        """计算非负框面积，退化或倒置框按零面积处理。"""
        return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))

    def _intersection_ratio(self, a, b) -> float:
        """计算交集占第一个框的比例，衡量手机是否落入人体关联区域。"""
        ix1 = max(float(a[0]), float(b[0]))
        iy1 = max(float(a[1]), float(b[1]))
        ix2 = min(float(a[2]), float(b[2]))
        iy2 = min(float(a[3]), float(b[3]))
        inter = self._area((ix1, iy1, ix2, iy2))
        return inter / max(1.0, self._area(a))

    def _iou(self, a, b) -> float:
        """计算框的交并比，以至少一个像素的分母避免除零。"""
        ix1 = max(float(a[0]), float(b[0]))
        iy1 = max(float(a[1]), float(b[1]))
        ix2 = min(float(a[2]), float(b[2]))
        iy2 = min(float(a[3]), float(b[3]))
        inter = self._area((ix1, iy1, ix2, iy2))
        union = self._area(a) + self._area(b) - inter
        return inter / max(1.0, union)

    @staticmethod
    def _center_distance_ratio(a, b) -> float:
        """按当前框尺寸归一化中心距离，为低重叠的小目标提供匹配依据。"""
        acx = (float(a[0]) + float(a[2])) / 2.0
        acy = (float(a[1]) + float(a[3])) / 2.0
        bcx = (float(b[0]) + float(b[2])) / 2.0
        bcy = (float(b[1]) + float(b[3])) / 2.0
        scale = max(float(a[2]) - float(a[0]), float(a[3]) - float(a[1]), 1.0)
        return (((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5) / scale
