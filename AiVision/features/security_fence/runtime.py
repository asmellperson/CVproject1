"""单摄像头人员身份状态机，不依赖数据库、HTTP 或模型加载。"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from math import ceil
from uuid import uuid4
from zoneinfo import ZoneInfo

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
    job_no: str | None = None
    org_index_code: str | None = None
    similarity: float | None = None

    def revoke(self):
        """保留同一候选的观测证据，但恢复身份必须有新的有效人脸，不能沿用通行结论。"""
        self.confirmed = False
        self.person_id, self.name, self.job_no, self.org_index_code = None, None, None, None

    def observe(self, face: dict, config: FenceValue):
        candidate = face["person_id"] if face["matched"] else 0
        if candidate == 0 and face["similarity"] > config.unknown_similarity_threshold:
            self.revoke()
            self.observations = 0
            return
        if candidate != self.candidate:
            # 身份证据发生冲突时立即撤销旧身份，重新积累有效观测。
            self.candidate, self.observations = candidate, 0
            self.revoke()
        self.observations += 1
        self.similarity = face["similarity"]
        if self.observations >= config.confirmation_frames:
            self.confirmed = True
            self.person_id = candidate or None
            self.name = face["person_name"] if candidate else "未知人员"
            self.job_no = face.get("job_no") if candidate else None
            self.org_index_code = face.get("org_index_code") if candidate else None


@dataclass
class FenceEvent:
    """连续违规只生成一个事件，首次报警待核验时允许补全身份。"""

    person: FencePerson
    last_seen: float
    candidate: int | None = None
    key: str = field(default_factory=lambda: uuid4().hex)
    dispatched: bool = False


class FenceRuntime:
    def __init__(self, config: FenceValue):
        self.config = config
        # 报警关联保留一个冷却窗口；未检出目标不参与判定，也不能保留通行身份。
        self.retention_seconds = max(config.alarm_interval, config.tracking_gap_seconds)
        self.tracker = IouTracker(max_lost=ceil(self.retention_seconds / config.cap_interval), smooth_alpha=1.0)
        self.identities: dict[int, Identity] = {}
        self.events: dict[int, FenceEvent] = {}
        self.last_seen: float | None = None
        self.shape: tuple[int, ...] | None = None

    def clear(self):
        self.tracker.reset()
        self.identities.clear()
        self.events.clear()
        self.last_seen = None

    def update(self, detections: list[dict], faces: list[dict], shape: tuple[int, ...], *, now: datetime, monotonic: float) -> list[FencePerson]:
        gap = monotonic - self.last_seen if self.last_seen is not None else 0.0
        if self.shape != shape or gap > self.retention_seconds:
            self.clear()
        elif gap > self.config.tracking_gap_seconds:
            for identity in self.identities.values():
                identity.revoke()
        self.shape, self.last_seen = shape, monotonic
        for tid, track in list(self.tracker.tracks.items()):
            if monotonic - track.last_seen > self.retention_seconds:
                del self.tracker.tracks[tid]
        tracks = self.tracker.update(detections, now=monotonic)
        self.identities = {tid: self.identities.get(tid, Identity()) for tid in tracks}
        self.events = {tid: event for tid, event in self.events.items()
                       if tid in tracks and monotonic - event.last_seen <= self.retention_seconds}
        visible = {tid: track for tid, track in tracks.items() if track.lost == 0}
        for tid in tracks.keys() - visible.keys():
            self.identities[tid].revoke()
            # 未观测期间不持续外推位置，避免抖动速度把待恢复目标推离原位置。
            tracks[tid].velocity = (0.0, 0.0)
        polygon = roi_to_pixels(self.config.roi_pos, shape)
        mode = current_mode(self.config, now)
        allowed = set(self.config.allowed_person_ids)
        overlapping = {
            tid for tid, track in visible.items()
            if any(other != tid and iou(track.bbox, item.bbox) >= self.config.tracking_overlap_threshold
                   for other, item in visible.items())
        }
        ambiguous: set[int] = set()
        associations: dict[int, list[dict]] = {}
        for face in faces:
            x1, y1, x2, y2 = face["bbox"]
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            candidates = [tid for tid, track in visible.items()
                          if track.bbox[0] <= cx <= track.bbox[2] and track.bbox[1] <= cy <= track.bbox[3]]
            if len(candidates) == 1:
                associations.setdefault(candidates[0], []).append(face)
            else:
                ambiguous.update(candidates)
        self._recover_known_people(associations, ambiguous)
        persons = []
        for tid, track in visible.items():
            identity = self.identities[tid]
            observations = associations.get(tid, [])
            if tid in ambiguous or len(observations) > 1:
                # 一张脸对应多个人体或一个人体关联多张脸时，不能传播通行身份。
                identity = self.identities[tid] = Identity()
            elif len(observations) == 1 and self._usable_face(observations[0]):
                identity.observe(observations[0], self.config)
            elif tid in overlapping:
                # 人体重叠且没有可靠的当帧人脸时，撤销可能被跟踪交换的旧身份。
                identity = self.identities[tid] = Identity()
            # 连续可靠的独立轨迹允许累计有效观测，单次无人脸不抹掉已有证据。
            x1, y1, x2, y2 = track.bbox
            # 地面区域以人体框底边中心判定，避免身体探入造成区域误判。
            in_roi = cv2.pointPolygonTest(polygon, ((x1 + x2) / 2, y2), False) >= 0
            state = "pending" if not identity.confirmed else "allowed" if identity.person_id in allowed else "unauthorized"
            reason = None
            if in_roi and mode == "forbidden":
                reason = "forbidden_time"
            elif in_roi and state == "unauthorized":
                reason = "unauthorized" if identity.person_id else "unknown_face"
            person = FencePerson(
                track_id=tid, bbox=track.bbox, in_roi=in_roi, identity=state,
                person_id=identity.person_id, person_name=identity.name, job_no=identity.job_no,
                org_index_code=identity.org_index_code, similarity=identity.similarity,
                alarm=reason is not None, reason=reason,
            )
            event = self.events.get(tid)
            if reason is None:
                # 待核验表示缺少当帧身份依据，不能据此结束已有的违规事件。
                if in_roi and state == "allowed":
                    self.events.pop(tid, None)
            elif (event is None or event.person.reason != reason
                  or (event.candidate and identity.candidate and event.candidate != identity.candidate)
                  or (event.candidate and identity.confirmed and identity.person_id is None)):
                self.events[tid] = FenceEvent(person=person.model_copy(deep=True), last_seen=monotonic,
                                              candidate=identity.candidate)
            else:
                event.last_seen = monotonic
                if identity.candidate:
                    event.candidate = identity.candidate
            persons.append(person)
        return persons

    def _recover_known_people(self, associations: dict[int, list[dict]], ambiguous: set[int]) -> None:
        """仅用当帧唯一的库内人脸恢复人员与事件关联，轨迹交换不重新记录同一个人。"""
        observed = {tid: rows[0]["person_id"] for tid, rows in associations.items()
                    if tid not in ambiguous and len(rows) == 1 and rows[0]["matched"]}
        counts = Counter(observed.values())
        previous = self.identities
        sources: dict[int, int | None] = {tid: tid for tid in previous}
        for tid, person_id in observed.items():
            candidates = [key for key, identity in previous.items() if identity.candidate == person_id]
            if counts[person_id] == 1 and len(candidates) == 1:
                sources[tid] = candidates[0]
        moved = {source for tid, source in sources.items() if source != tid}
        for tid, source in list(sources.items()):
            if tid == source and tid in moved:
                sources[tid] = None
        remaining = set(previous) - {source for source in sources.values() if source is not None}
        unassigned = [tid for tid, source in sources.items() if source is None]
        if len(remaining) == len(unassigned) == 1:
            # 只保留唯一剩余的事件关联；没有当帧人脸时仍为待核验，不传播通行身份。
            sources[unassigned[0]] = remaining.pop()
        events = self.events
        self.identities = {tid: previous[source] if source is not None else Identity()
                           for tid, source in sources.items()}
        self.events = {tid: events[source] for tid, source in sources.items() if source in events}
        for tid, source in sources.items():
            if source is not None and source != tid:
                self.identities[tid].revoke()

    def _usable_face(self, face: dict) -> bool:
        """库内匹配沿用共享识别结论，库外未知身份需要额外质量依据。"""
        if face["matched"]:
            return True
        quality = face.get("quality")
        return bool(quality and quality["size"] >= self.config.min_face_size
                    and quality["sharpness"] >= self.config.min_face_sharpness
                    and quality["asymmetry"] <= self.config.max_face_asymmetry)
