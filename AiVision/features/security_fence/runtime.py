"""单摄像头人员身份状态机，不依赖数据库、HTTP 或模型加载。"""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4

import cv2

from AiVision.features._shared.roi import roi_to_pixels
from AiVision.features._shared.tracking import IouTracker, iou
from .schema import FencePerson, FenceValue


def current_mode(value: FenceValue, now: datetime) -> str:
    clock = now.astimezone(ZoneInfo(value.timezone)).strftime("%H:%M")
    start, end = value.forbidden_start, value.forbidden_end
    # 起止相同表示全天禁止；跨午夜区间采用左闭右开边界。
    forbidden = start == end or (start <= clock < end if start < end else clock >= start or clock < end)
    return "forbidden" if forbidden else "whitelist"


@dataclass
class Identity:
    candidate: int | None = None
    observations: int = 0
    confirmed: bool = False
    person_id: int | None = None
    name: str | None = None
    similarity: float | None = None

    def observe(self, face: dict, config: FenceValue):
        candidate = face["person_id"] if face["matched"] else 0
        if candidate == 0 and face["similarity"] > config.unknown_similarity_threshold:
            self.confirmed = False
            self.person_id, self.name = None, None
            self.observations = 0
            return
        if candidate != self.candidate:
            # 身份证据发生冲突时立即撤销旧身份，重新积累有效观测。
            self.candidate, self.observations, self.confirmed = candidate, 0, False
            self.person_id, self.name = None, None
        self.observations += 1
        self.similarity = face["similarity"]
        if self.observations >= config.confirmation_frames:
            self.confirmed = True
            self.person_id = candidate or None
            self.name = face["person_name"] if candidate else None


class FenceRuntime:
    def __init__(self, config: FenceValue):
        self.config = config
        # 身份不能跨丢失轨迹传播；共享跟踪器仅关联连续可见的人员。
        self.tracker = IouTracker(max_lost=0, smooth_alpha=1.0)
        self.identities: dict[int, Identity] = {}
        self.notified: dict[int, str] = {}
        self.last_seen: float | None = None
        self.shape: tuple[int, ...] | None = None
        self.generation = uuid4().hex

    def clear(self):
        self.generation = uuid4().hex
        self.tracker.reset()
        self.identities.clear()
        self.notified.clear()
        self.last_seen = None

    def update(self, detections: list[dict], faces: list[dict], shape: tuple[int, ...], *, now: datetime, monotonic: float) -> list[FencePerson]:
        if self.shape != shape or (self.last_seen is not None and monotonic - self.last_seen > self.config.tracking_gap_seconds):
            self.clear()
        self.shape, self.last_seen = shape, monotonic
        tracks = self.tracker.update(detections, now=monotonic)
        self.identities = {tid: self.identities.get(tid, Identity()) for tid in tracks}
        self.notified = {tid: reason for tid, reason in self.notified.items() if tid in tracks}
        polygon = roi_to_pixels(self.config.roi_pos, shape)
        mode = current_mode(self.config, now)
        allowed = set(self.config.allowed_person_ids)
        ambiguous = {
            tid for tid, track in tracks.items()
            if any(other != tid and iou(track.bbox, item.bbox) >= self.config.tracking_overlap_threshold
                   for other, item in tracks.items())
        }
        associations: dict[int, list[dict]] = {}
        for face in faces:
            x1, y1, x2, y2 = face["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            candidates = [tid for tid, track in tracks.items()
                          if track.bbox[0] <= cx <= track.bbox[2] and track.bbox[1] <= cy <= track.bbox[3]]
            if len(candidates) == 1:
                associations.setdefault(candidates[0], []).append(face)
            else:
                ambiguous.update(candidates)
        persons = []
        for tid, track in tracks.items():
            identity = self.identities[tid]
            if tid in ambiguous:
                identity = self.identities[tid] = Identity()
            else:
                observations = associations.get(tid, [])
                if len(observations) > 1:
                    # 单个人体框关联到多张脸时，不能沿用其中任一人的通行身份。
                    identity = self.identities[tid] = Identity()
                elif len(observations) == 1 and self._usable_face(observations[0]):
                    identity.observe(observations[0], self.config)
                elif not identity.confirmed:
                    identity.observations = 0
            x1, y1, x2, y2 = track.bbox
            # 地面区域以人体框底边中心判定，避免身体探入造成区域误判。
            in_roi = cv2.pointPolygonTest(polygon, ((x1 + x2) / 2, y2), False) >= 0
            state = "pending" if not identity.confirmed else "allowed" if identity.person_id in allowed else "unauthorized"
            reason = None
            if in_roi and mode == "forbidden":
                reason = "forbidden_time"
            elif in_roi and state == "unauthorized":
                reason = "unauthorized" if identity.person_id else "unknown_face"
            if reason != self.notified.get(tid):
                self.notified.pop(tid, None)
            persons.append(FencePerson(
                track_id=tid, bbox=track.bbox, in_roi=in_roi, identity=state,
                person_id=identity.person_id, person_name=identity.name, similarity=identity.similarity,
                alarm=reason is not None, reason=reason,
            ))
        return persons

    def _usable_face(self, face: dict) -> bool:
        quality = face.get("quality")
        return bool(quality and quality["size"] >= self.config.min_face_size
                    and quality["sharpness"] >= self.config.min_face_sharpness
                    and quality["asymmetry"] <= self.config.max_face_asymmetry)
