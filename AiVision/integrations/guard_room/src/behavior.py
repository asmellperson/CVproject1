# behavior.py
"""
行为规则引擎模块。

基于每帧的检测结果（人体框、手机框、姿态特征）对三类异常行为做实时判断：
  - absent     ：画面内持续无人；
  - phone      ：疑似玩手机；
  - prone_sleep：疑似趴睡。

设计原则：
  - 无状态输入，有状态判断：每帧输入均为无状态的检测列表，
    引擎内部维护每人的时序状态（PersonRuntimeState），实现跨帧的持续时长累计。
  - 多目标取最优：同帧多人时，各规则取置信度最高的目标作为本帧输出。
  - 容错漏检：手机规则引入时间窗口与宽限期，避免单帧漏检导致报警中断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .config import AppConfig
from .types import Detection
from collections import deque
from typing import Deque


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class RuleDecision:
    """单条规则的判断结果。

    Attributes:
        active:     本帧该规则是否触发报警。
        reason:     人类可读的触发原因，用于日志与报警通知。
        confidence: 置信度（0~1），多目标时取最高值作为本帧输出。
        track_id:   触发报警的目标跟踪 ID；absent 规则无具体目标时为 None。
    """
    active: bool = False
    reason: str = ""
    confidence: float = 0.0
    track_id: int | None = None


@dataclass
class PersonRuntimeState:
    """单个跟踪目标的跨帧运行时状态。

    由 BehaviorEngine 在首次检测到目标时创建，超过 state_ttl_seconds 未出现后销毁。

    Attributes:
        track_id:               目标跟踪 ID。
        last_bbox:              上一帧的检测框 (x1, y1, x2, y2)。
        last_center:            上一帧的中心点，用于计算帧间位移（运动量）。
        last_seen_ts:           上次被检测到的流时间戳（秒），用于 TTL 清理。
        motion_score:           当前帧与上一帧中心点的欧氏距离，衡量运动量。
        phone_hit_ts:           滑动时间窗口内各次"手机命中"的时间戳队列。
        phone_active_seconds:   手机规则连续激活的累计时长（秒）。
        last_phone_eval_ts:     上次执行手机规则评估的时间戳，用于计算 delta_t。
        last_phone_positive_ts: 上次手机证据成立的时间戳，用于宽限期判断。
        prone_frames:           趴睡候选条件连续成立的帧计数（含衰减）。
        head_down_frames:       低头特征连续成立的帧计数（含衰减）。
    """
    track_id: int
    last_bbox: tuple[int, int, int, int]
    last_center: tuple[float, float]
    last_seen_ts: float
    motion_score: float = 0.0

    phone_hit_ts: Deque[float] = field(default_factory=deque)   # 滑动窗口内命中时间戳
    phone_active_seconds: float = 0.0
    last_phone_eval_ts: float = 0.0
    last_phone_positive_ts: float = -9999.0     # 初始化为极小值，确保首次判断不受宽限期影响

    prone_frames: int = 0
    head_down_frames: int = 0


# ---------------------------------------------------------------------------
# 几何辅助函数
# ---------------------------------------------------------------------------

def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """计算两点间欧氏距离（像素）。"""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _inside_expand(
    point: tuple[float, float],
    bbox: tuple[int, int, int, int],
    pad_x: float,
    pad_y: float,
) -> bool:
    """判断点是否在向外扩展后的矩形区域内。

    用于手机检测：在人体框基础上向外扩展一定像素，
    容纳手机框中心因透视或遮挡偏移到人体框外的情况。

    Args:
        point: 待判断的点坐标 (x, y)。
        bbox:  原始矩形框 (x1, y1, x2, y2)。
        pad_x: 水平方向向外扩展的像素数。
        pad_y: 垂直方向向外扩展的像素数。
    """
    x1, y1, x2, y2 = bbox
    return (x1 - pad_x) <= point[0] <= (x2 + pad_x) and (y1 - pad_y) <= point[1] <= (y2 + pad_y)


# ---------------------------------------------------------------------------
# 行为引擎主体
# ---------------------------------------------------------------------------

class BehaviorEngine:
    """逐帧行为分析引擎。

    调用方式：每帧调用一次 update()，传入当前帧的检测结果，
    返回各规则的判断结果字典供上层（AlarmManager）决定是否触发报警。

    状态管理：
        - person_states：按 track_id 索引的跨帧状态字典，引擎内部自动创建与清理。
        - absent_started_at：记录画面首次出现"无人"状态的时间戳。
    """

    def __init__(self, config: AppConfig):
        self.cfg = config
        self.person_states: Dict[int, PersonRuntimeState] = {}  # track_id → 运行时状态
        self.absent_started_at: float | None = None             # None 表示当前画面有人

    def update(
        self,
        *,
        timestamp_s: float,
        fps: float,
        frame_shape: tuple[int, int, int],
        persons: List[Detection],
        phones: List[Detection],
        pose_features: Dict[int, Dict[str, float]],
    ) -> Dict[str, RuleDecision]:
        """执行一次行为分析，返回全部规则的判断结果。

        Args:
            timestamp_s:    当前帧的流时间戳（秒）。
            fps:            当前流帧率，用于将帧计数转换为时长。
            frame_shape:    帧的形状 (H, W, C)，用于计算相对尺寸。
            persons:        本帧检测到的人体目标列表。
            phones:         本帧检测到的手机目标列表。
            pose_features:  各 track_id 对应的姿态特征字典
                            （键如 "nose_x", "nose_y", "head_down_ratio"）。

        Returns:
            规则名 → RuleDecision 的字典，键固定为
            {"absent", "phone", "prone_sleep"}，未触发时 active=False。
        """
        self._cleanup_states(timestamp_s)   # 清理长时间未出现的目标状态，防止内存泄漏

        # 初始化本帧所有规则的默认结果（未触发）
        decisions: Dict[str, RuleDecision] = {
            "absent": RuleDecision(),
            "phone": RuleDecision(),
            "prone_sleep": RuleDecision(),
        }

        # ── 无人分支 ──────────────────────────────────────────────────────
        if not persons:
            if self.absent_started_at is None:
                self.absent_started_at = timestamp_s    # 记录无人状态开始时刻
            absent_for = timestamp_s - self.absent_started_at
            if absent_for >= self.cfg.rules.absent_seconds:
                decisions["absent"] = RuleDecision(
                    active=True,
                    reason=f"画面内持续无人 {absent_for:.1f}s",
                    # 置信度随无人时长线性增长，上限 0.99
                    confidence=min(0.99, absent_for / max(1, self.cfg.rules.absent_seconds)),
                )
            return decisions    # 无人时其余规则无意义，提前返回

        # ── 有人分支 ──────────────────────────────────────────────────────
        self.absent_started_at = None   # 重置无人计时器

        # 多目标时各规则独立取置信度最高的目标
        best_phone = RuleDecision()
        best_prone = RuleDecision()
        frame_h = frame_shape[0]

        for person in persons:
            track_id = int(person.track_id) if person.track_id is not None else -1
            center = person.center

            # 懒初始化：首次出现时创建该目标的运行时状态
            state = self.person_states.get(track_id)
            if state is None:
                state = PersonRuntimeState(
                    track_id=track_id,
                    last_bbox=person.bbox,
                    last_center=center,
                    last_seen_ts=timestamp_s,
                )
                self.person_states[track_id] = state

            # 更新运动量：当前帧与上一帧中心点的位移
            state.motion_score = _distance(center, state.last_center)
            state.last_center = center
            state.last_bbox = person.bbox
            state.last_seen_ts = timestamp_s

            pf = pose_features.get(track_id, {})
            phone_decision = self._phone_rule(state, person, phones, pf, fps, timestamp_s)
            prone_decision = self._prone_sleep_rule(state, person, pf, fps, frame_h)

            # 取各规则置信度最高的目标作为本帧输出
            if phone_decision.active and phone_decision.confidence >= best_phone.confidence:
                best_phone = phone_decision
            if prone_decision.active and prone_decision.confidence >= best_prone.confidence:
                best_prone = prone_decision

        decisions["phone"] = best_phone
        decisions["prone_sleep"] = best_prone
        return decisions

    # -----------------------------------------------------------------------
    # 规则实现
    # -----------------------------------------------------------------------

    def _phone_rule(
        self,
        state: PersonRuntimeState,
        person: Detection,
        phones: List[Detection],
        pose_features: Dict[str, float],
        fps: float,
        timestamp_s: float,
    ) -> RuleDecision:
        """手机使用检测规则。

        判断逻辑（三层过滤，缺一不可）：
          1. 空间过滤：手机框中心需在人体框扩展区域内，且位于上半身（高度 70% 以上）
             或靠近头部估计点，排除桌上/地上的手机误检。
          2. 时间窗口：在 phone_window_seconds 滑动窗口内命中帧数达到
             phone_min_hits_in_window，才认为证据成立；清除窗口外旧记录以释放内存。
          3. 持续时长：引入宽限期（phone_grace_seconds）容忍短暂漏检，
             保证证据连续成立达到 phone_seconds 后才触发报警。

        置信度计算：基于手机框与头部/人体中心的最小距离归一化，
        距离越近置信度越高，区间限定在 [0.65, 1.0]。
        """
        x1, y1, x2, y2 = person.bbox
        person_h = max(1, y2 - y1)
        person_center = person.center
        head_point = self._head_point(person, pose_features)    # 头部估计坐标

        matched_phone = None
        min_dist = 1e9  # 手机框到头部/人体中心的最小距离，用于置信度计算

        # ── 1. 空间过滤：为每个手机框判断是否属于当前人 ──
        for phone in phones:
            phone_center = phone.center
            close_to_person = _inside_expand(
                phone_center,
                person.bbox,
                self.cfg.rules.phone_near_person_px,    # 水平容差（像素）
                person_h * 0.15,                        # 垂直容差（人体高度的 15%）
            )
            close_to_head = _distance(phone_center, head_point) <= self.cfg.rules.phone_near_head_px
            in_upper_half = phone_center[1] <= y1 + person_h * 0.7  # 手机在人体上 70% 区域内

            if close_to_person and (close_to_head or in_upper_half):
                matched_phone = phone
                min_dist = min(
                    min_dist,
                    _distance(phone_center, head_point),
                    _distance(phone_center, person_center),
                )

        # ── 2. 时间窗口：维护滑动窗口内的命中记录 ──
        if state.last_phone_eval_ts <= 0:
            state.last_phone_eval_ts = timestamp_s  # 首次调用，初始化时间基准

        delta_t = max(0.0, timestamp_s - state.last_phone_eval_ts)
        state.last_phone_eval_ts = timestamp_s

        if matched_phone is not None:
            state.phone_hit_ts.append(timestamp_s)  # 本帧命中，记录时间戳

        # 淘汰窗口之外的旧命中记录
        while state.phone_hit_ts and (timestamp_s - state.phone_hit_ts[0] > self.cfg.rules.phone_window_seconds):
            state.phone_hit_ts.popleft()

        window_hits = len(state.phone_hit_ts)
        phone_present_now = window_hits >= self.cfg.rules.phone_min_hits_in_window  # 窗口内命中是否充分

        if phone_present_now:
            state.last_phone_positive_ts = timestamp_s  # 更新最近一次证据成立的时间

        # ── 3. 宽限期 + 持续时长 ──
        # 宽限期：允许短暂漏检（如手机被遮挡），不立即重置计时器
        confirmed_active = (timestamp_s - state.last_phone_positive_ts) <= self.cfg.rules.phone_grace_seconds

        if confirmed_active:
            state.phone_active_seconds += delta_t  # 累计激活时长
        else:
            state.phone_active_seconds = 0.0       # 宽限期结束后彻底重置

        duration_s = state.phone_active_seconds

        # 三个条件同时满足才触发：宽限期内 + 窗口命中充分 + 持续时长达标
        if (
            confirmed_active
            and window_hits >= self.cfg.rules.phone_min_hits_in_window
            and duration_s >= self.cfg.rules.phone_seconds
        ):
            # 距离越小置信度越高；限定在 [0.65, 1.0] 避免极端值
            conf = max(
                0.65,
                1.0 - min(0.45, min_dist / max(1.0, self.cfg.rules.phone_near_person_px * 2)),
            )
            return RuleDecision(
                active=True,
                reason=(
                    f"疑似玩手机持续 {duration_s:.1f}s "
                    f"（{self.cfg.rules.phone_window_seconds}s内命中{window_hits}帧）"
                ),
                confidence=conf,
                track_id=state.track_id,
            )

        return RuleDecision()

    def _prone_sleep_rule(
        self,
        state: PersonRuntimeState,
        person: Detection,
        pose_features: Dict[str, float],
        fps: float,
        frame_h: int,
    ) -> RuleDecision:
        """趴睡检测规则。

        综合以下两类特征判断是否趴睡：
          A. 姿态特征：head_down_ratio 超阈值（低头程度）；
          B. 几何特征：人体框高度占画面比例过小（人体呈水平姿态时框变矮）；

        帧计数采用"软衰减"策略（不满足时 -2，满足时 +1），
        避免单帧噪声导致计数骤降，同时也能在条件持续不满足时较快归零。

        置信度与 head_down_ratio 正相关，反映低头程度越深越可信。
        """
        x1, y1, x2, y2 = person.bbox
        bbox_h = max(1, y2 - y1)
        bbox_height_ratio = bbox_h / max(1, frame_h)            # 人体框高度占画面比例
        head_down_ratio = float(pose_features.get("head_down_ratio", 0.0))
        low_motion = state.motion_score <= self.cfg.rules.static_motion_threshold   # 是否几乎静止
        head_down = head_down_ratio >= self.cfg.rules.prone_head_down_ratio_threshold

        # 低头帧计数：满足时 +1，不满足时 -2（软衰减，下限 0）
        if head_down:
            state.head_down_frames += 1
        else:
            state.head_down_frames = max(0, state.head_down_frames - 2)

        # 趴睡候选：静止 + （低头帧数达标 或 框高比过小）
        prone_candidate = low_motion and (
            state.head_down_frames >= self.cfg.rules.prone_consecutive_frames
            or bbox_height_ratio <= self.cfg.rules.prone_bbox_height_ratio_threshold
        )

        # 趴睡帧计数：同样采用软衰减策略
        if prone_candidate:
            state.prone_frames += 1
        else:
            state.prone_frames = max(0, state.prone_frames - 2)

        # 将帧计数换算为时长（秒）
        duration_s = state.prone_frames / max(1.0, fps)
        if duration_s >= self.cfg.rules.prone_sleep_seconds:
            # 置信度由 head_down_ratio 线性提升，上限 0.98
            conf = min(0.98, 0.68 + head_down_ratio * 0.8)
            return RuleDecision(
                active=True,
                reason=f"疑似趴睡持续 {duration_s:.1f}s（低头+低运动量）",
                confidence=conf,
                track_id=state.track_id,
            )
        return RuleDecision()

    def _cleanup_states(self, timestamp_s: float) -> None:
        """清理超过 TTL 未出现的目标状态，防止内存随跟踪 ID 无限增长。

        TTL 由配置项 state_ttl_seconds 控制；目标消失（如离开画面）后，
        其状态在 TTL 到期前仍保留，以支持短暂遮挡后的重新识别。
        """
        stale_ids = [
            track_id
            for track_id, state in self.person_states.items()
            if (timestamp_s - state.last_seen_ts) > self.cfg.rules.state_ttl_seconds
        ]
        for track_id in stale_ids:
            self.person_states.pop(track_id, None)

    @staticmethod
    def _head_point(person: Detection, pose_features: Dict[str, float]) -> Tuple[float, float]:
        """估计头部坐标（像素绝对值）。

        优先使用姿态估计输出的鼻子关键点（相对于人体框的归一化坐标）；
        关键点不可用时回落到人体框上方 18% 处的几何估计，保证鲁棒性。

        Args:
            person:        人体检测结果，提供 bbox。
            pose_features: 姿态特征字典，包含归一化的 nose_x / nose_y（可选）。

        Returns:
            头部估计坐标 (x, y)（像素，相对于图像原点）。
        """
        x1, y1, x2, y2 = person.bbox
        if "nose_x" in pose_features and "nose_y" in pose_features:
            # 将归一化坐标还原为图像绝对坐标
            return (
                x1 + pose_features["nose_x"] * (x2 - x1),
                y1 + pose_features["nose_y"] * (y2 - y1),
            )
        # 回落方案：人体框顶部 18% 处（经验值，对应直立人体的头部位置）
        return ((x1 + x2) / 2.0, y1 + (y2 - y1) * 0.18)