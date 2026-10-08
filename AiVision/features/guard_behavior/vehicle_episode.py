"""单摄车辆事件状态机；仅消费框与时间，不持有图像或执行推理。"""
from dataclasses import dataclass, field
from math import hypot
from uuid import uuid4

from .pose_features import bbox_iou
from .schema import GuardBehaviorRuntimePolicy
from .state import BBox, GuardCameraSnapshot, VehicleDetection


REASSOCIATE_MIN_IOU = .3


def bbox_distance(first: BBox, second: BBox) -> float:
    """使用两矩形边界的最短距离，重叠视为已经靠近，不推断跨摄身份。"""
    dx = max(first[0] - second[2], second[0] - first[2], 0.)
    dy = max(first[1] - second[3], second[1] - first[3], 0.)
    return hypot(dx, dy)


@dataclass
class _Episode:
    """车辆从首次出现到离场的局部事件，保留检查和观测不确定性。"""
    episode_id: str
    class_id: int
    first_bbox: BBox
    last_bbox: BBox
    frame_size: tuple[int, int]
    started_at: float
    last_seen_at: float
    confidence: float
    inspected: bool = False
    occluded: bool = False
    uncertain: bool = False


@dataclass(frozen=True)
class _RecentChecked:
    """短期保留已检查车辆的位置，支持遮挡后一次性的事实转移。"""
    class_id: int
    bbox: BBox
    last_seen_at: float


@dataclass(frozen=True)
class VehicleEpisodeOutcome:
    """已闭合车辆事件的检查、方向和证据完整性结果。"""
    episode_id: str
    class_id: int
    first_bbox: BBox
    last_bbox: BBox
    started_at: float
    ended_at: float
    confidence: float
    inspected: bool
    direction_matches: bool
    uncertain: bool

    @property
    def should_alarm(self) -> bool:
        """仅对未检查、方向符合且观测完整的事件触发告警。"""
        return not self.inspected and self.direction_matches and not self.uncertain


@dataclass(frozen=True)
class VehicleEpisodeUpdate:
    """一次状态推进中新开始的事件 ID 与已经结束的事件结果。"""
    started: tuple[str, ...] = ()
    completed: tuple[VehicleEpisodeOutcome, ...] = ()


@dataclass
class VehicleEpisodeTracker:
    """按单摄像头车辆框维护事件，不推断跨摄像头身份。"""
    _episodes: dict[str, _Episode] = field(default_factory=dict)
    _recent_checked: list[_RecentChecked] = field(default_factory=list)
    _last_snapshot_at: float | None = None
    uncertain: bool = False

    @property
    def monitoring(self) -> bool:
        """表明当前是否仍有尚未闭合的车辆事件。"""
        return bool(self._episodes)

    def mark_unknown(self) -> None:
        # 不完整的观察区间不能证明整段事件都无人检查，直到场景清空才重新采信负证据。
        """标记观测缺口并废弃可转移检查事实，直到场景清空才恢复负证据可信度。"""
        self.uncertain = True
        self._recent_checked.clear()
        for episode in self._episodes.values():
            episode.uncertain = True

    def update(self, snapshot: GuardCameraSnapshot, now: float,
               policy: GuardBehaviorRuntimePolicy) -> VehicleEpisodeUpdate:
        """只用新快照更新车辆位置，结合缺席超时关闭事件并记录保安靠近事实。"""
        started = []
        fresh = self._last_snapshot_at is None or snapshot.updated_at > self._last_snapshot_at
        observed_at = snapshot.updated_at if fresh else now
        self._recent_checked = [item for item in self._recent_checked
                                if 0 <= observed_at - item.last_seen_at <= policy.vehicle_reassociate_seconds]
        # 已确认遮挡超时的事件先闭合，返回车辆只能开启新事件，不能复活旧事件。
        completed = self._close_departed(observed_at, policy)
        if fresh:
            self._last_snapshot_at = snapshot.updated_at
            detections = snapshot.vehicle.detections
            matched = self._associate(detections, snapshot.updated_at, policy)
            for episode in self._episodes.values():
                episode.occluded = episode.episode_id not in matched.values()
            for index, vehicle in enumerate(detections):
                episode_id = matched.get(index)
                if episode_id is None:
                    episode_id = uuid4().hex
                    self._episodes[episode_id] = _Episode(
                        episode_id, vehicle.class_id, vehicle.bbox, vehicle.bbox, snapshot.frame_size,
                        snapshot.updated_at, snapshot.updated_at, vehicle.confidence,
                        inspected=self._take_recent_checked(vehicle), uncertain=self.uncertain,
                    )
                    started.append(episode_id)
                episode = self._episodes[episode_id]
                episode.last_bbox = vehicle.bbox
                episode.last_seen_at = snapshot.updated_at
                episode.confidence = max(episode.confidence, vehicle.confidence)
                episode.occluded = False
                episode.inspected |= any(bbox_distance(guard.bbox, vehicle.bbox) <= policy.vehicle_near_px
                                         for guard in snapshot.guards)
        completed.extend(self._close_departed(now, policy))
        if not self._episodes and not snapshot.vehicle.detections:
            self.uncertain = False
        return VehicleEpisodeUpdate(tuple(started), tuple(completed))

    def _associate(self, detections: tuple[VehicleDetection, ...], observed_at: float,
                   policy: GuardBehaviorRuntimePolicy) -> dict[int, str]:
        """按同类车辆的 IoU 贪心一对一匹配，排除已经遮挡超时的事件。"""
        candidates = []
        for index, vehicle in enumerate(detections):
            for episode in self._episodes.values():
                if episode.class_id != vehicle.class_id:
                    continue
                if episode.occluded and observed_at - episode.last_seen_at >= policy.vehicle_occlusion_seconds:
                    continue
                overlap = bbox_iou(vehicle.bbox, episode.last_bbox)
                if overlap > REASSOCIATE_MIN_IOU:
                    candidates.append((overlap, index, episode.episode_id))
        matched, used = {}, set()
        for _, index, episode_id in sorted(candidates, reverse=True):
            if index not in matched and episode_id not in used:
                matched[index] = episode_id
                used.add(episode_id)
        return matched

    def _take_recent_checked(self, vehicle: VehicleDetection) -> bool:
        """将近期检查事实转移给同类同位置车辆一次，避免复制到多个目标。"""
        candidates = [(bbox_iou(vehicle.bbox, item.bbox), index)
                      for index, item in enumerate(self._recent_checked) if item.class_id == vehicle.class_id]
        if not candidates:
            return False
        overlap, index = max(candidates)
        if overlap <= REASSOCIATE_MIN_IOU:
            return False
        # 已检查事实只转移给一个同类、同位置车辆，不复制给同时出现的多个目标。
        self._recent_checked.pop(index)
        return True

    def _close_departed(self, now: float, policy: GuardBehaviorRuntimePolicy) -> list[VehicleEpisodeOutcome]:
        """已观察到缺席且超过遮挡时限后闭合事件，防止重复评估旧快照制造离场。"""
        completed = []
        for episode_id, episode in tuple(self._episodes.items()):
            # 至少观察到一帧车辆缺席；不能因同一张快照被定时评估而制造离场。
            if not episode.occluded or now - episode.last_seen_at < policy.vehicle_occlusion_seconds:
                continue
            completed.append(VehicleEpisodeOutcome(
                episode_id, episode.class_id, episode.first_bbox, episode.last_bbox,
                episode.started_at, now, episode.confidence, episode.inspected,
                self._direction_matches(episode, policy), episode.uncertain,
            ))
            if (episode.inspected and not episode.uncertain and policy.vehicle_reassociate_seconds > 0
                    and now - episode.last_seen_at <= policy.vehicle_reassociate_seconds):
                self._recent_checked.append(_RecentChecked(episode.class_id, episode.last_bbox, episode.last_seen_at))
            del self._episodes[episode_id]
        return completed

    @staticmethod
    def _direction_matches(episode: _Episode, policy: GuardBehaviorRuntimePolicy) -> bool:
        """按首末位置的归一化位移核对离场方向，忽略不足最小幅度的抖动。"""
        direction = policy.vehicle_exit_direction
        if direction == "any":
            return True
        first, last = episode.first_bbox, episode.last_bbox
        width, height = episode.frame_size
        dx = ((last[0] + last[2]) - (first[0] + first[2])) / (2 * width)
        dy = (last[3] - first[3]) / height
        delta = {"left": -dx, "right": dx, "up": -dy, "down": dy}[direction]
        return delta > 0 and delta >= policy.vehicle_direction_min_delta_ratio
