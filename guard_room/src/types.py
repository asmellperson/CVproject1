# type.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Point = Tuple[int, int]
BBox = Tuple[int, int, int, int]

@dataclass
class Detection:
    cls_id: int
    conf: float
    bbox: BBox
    track_id: Optional[int] = None

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

@dataclass
class PersonState:
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
    extra: Dict[str, float] = field(default_factory=dict)

@dataclass
class FrameContext:
    timestamp_s: float
    frame_index: int
    fps: float
    detections: List[Detection]
    persons: List[Detection]
    phones: List[Detection]
    pose_features: Dict[int, Dict[str, float]]

@dataclass
class AlarmEvent:
    event_type: str
    timestamp_s: float
    frame_index: int
    track_id: Optional[int]
    confidence: float
    reason: str
    image_path: Optional[str] = None

    # 新增
    camera_name: str = ""
    video_path: Optional[str] = None
    video_status: str = "pending"   # pending / ready / failed