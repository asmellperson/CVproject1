# types.py
"""
全局共享数据类型模块。

集中定义系统中跨模块流通的核心数据结构，避免循环导入。
所有类型均为纯数据容器，不包含业务逻辑。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 类型别名
# ---------------------------------------------------------------------------

Point = Tuple[int, int]             # 像素坐标点 (x, y)
BBox = Tuple[int, int, int, int]    # 检测框 (x1, y1, x2, y2)，左上 + 右下


# ---------------------------------------------------------------------------
# 检测与跟踪
# ---------------------------------------------------------------------------

@dataclass
class Detection:
    """单个目标的检测结果。

    Attributes:
        cls_id:   YOLO 类别 ID，与 ClassConfig 中的映射对应。
        conf:     检测置信度（0~1）。
        bbox:     检测框 (x1, y1, x2, y2)，像素坐标。
        track_id: ByteTrack 分配的跟踪 ID；目标首次出现或跟踪丢失时为 None。
    """
    cls_id: int
    conf: float
    bbox: BBox
    track_id: Optional[int] = None

    @property
    def center(self) -> Tuple[float, float]:
        """返回检测框的中心点坐标 (cx, cy)。"""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


@dataclass
class PersonState:
    """单个跟踪目标的历史状态（当前未被核心流水线使用，保留供扩展）。

    与 behavior.py 中的 PersonRuntimeState 职责类似，
    此类为早期设计遗留，可在后续重构中合并或移除。

    Attributes:
        track_id:        跟踪 ID。
        last_bbox:       上一帧检测框。
        last_center:     上一帧中心点，用于计算运动量。
        last_timestamp:  上一帧的流时间戳（秒）。
        motion_score:    帧间中心点位移（像素），衡量运动量。
        in_post_roi:     是否处于岗位感兴趣区域内。
        head_down_frames:低头特征连续成立的帧计数。
        phone_frames:    手机使用特征连续成立的帧计数。
        drowsy_frames:   瞌睡特征连续成立的帧计数。
        visible:         当前帧是否可见（未被遮挡或离开画面）。
        history_centers: 历史中心点轨迹，用于轨迹分析。
        extra:           扩展字段，存放临时或实验性特征值。
    """
    track_id: int
    last_bbox: BBox
    last_center: Tuple[float, float]
    last_timestamp: float
    motion_score: float = 0.0
    in_post_roi: bool = False
    head_down_frames: int = 0
    phone_frames: int = 0
    drowsy_frames: int = 0
    visible: bool = True
    history_centers: List[Tuple[float, float]] = field(default_factory=list)
    extra: Dict[str, float] = field(default_factory=dict)  # 扩展字段，避免频繁修改 dataclass


@dataclass
class FrameContext:
    """单帧推理的完整上下文（当前未被核心流水线使用，保留供扩展）。

    将一帧内所有相关数据打包为单一对象，便于在函数间传递而无需多个参数。

    Attributes:
        timestamp_s:   当前帧的流时间戳（秒）。
        frame_index:   帧序号，单调递增。
        fps:           当前推理帧率。
        detections:    本帧所有目标的检测结果（含所有类别）。
        persons:       从 detections 筛出的人体目标子集。
        phones:        从 detections 筛出的手机目标子集。
        pose_features: 各 track_id 对应的姿态特征字典。
    """
    timestamp_s: float
    frame_index: int
    fps: float
    detections: List[Detection]
    persons: List[Detection]
    phones: List[Detection]
    pose_features: Dict[int, Dict[str, float]]


# ---------------------------------------------------------------------------
# 报警事件
# ---------------------------------------------------------------------------

@dataclass
class AlarmEvent:
    """报警事件的完整描述，贯穿从触发到推送的完整生命周期。

    生命周期：
        AlarmManager.emit() 创建（video_status="pending"）
            → AlarmClipRecorder 录制完成后 attach_video() 回填路径（video_status="ready"）
            → WeChatNotifier 推送

    Attributes:
        event_type:   报警类型，如 "absent"、"phone_use"、"prone_sleep"。
        timestamp_s:  报警触发时的流时间戳（秒）。
        frame_index:  触发帧的序号，与 video_path 关联定位具体片段。
        track_id:     触发目标的跟踪 ID；离岗等无具体目标的报警为 None。
        confidence:   置信度（0~1）。
        reason:       人类可读的触发原因，用于日志和推送消息。
        image_path:   报警瞬间的 JPEG 快照文件路径。
        camera_name:  产生报警的摄像头名称，用于推送消息中标识来源。
        video_path:   报警视频片段路径；录制完成前为 None。
        video_status: 视频录制状态：
                        "pending" —— 录制中（初始值）；
                        "ready"   —— 录制完成，video_path 有效；
                        "failed"  —— 录制或上传失败。
    """
    event_type: str
    timestamp_s: float
    frame_index: int
    track_id: Optional[int]
    confidence: float
    reason: str
    image_path: Optional[str] = None
    camera_name: str = ""
    video_path: Optional[str] = None
    video_status: str = "pending"   # pending → ready / failed