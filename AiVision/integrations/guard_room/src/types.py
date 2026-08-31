# 文件说明：定义类型契约的数据结构与类型契约。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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

# 功能：单个目标的检测结果；输入与输出详见下方说明
# 参数：
#   - `cls_id`（int）：`cls_id` 对应业务对象的唯一标识
#   - `conf`（float）：`conf` 对应的业务输入值
#   - `bbox`（BBox）：`bbox` 对应的业务输入值
#   - `track_id`（Optional[int]）：目标跟踪标识
# 返回：Detection；返回新建的 `Detection` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的
#         `test_status_reports_guards_separately_from_all_detected_people`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
#         `test_vehicle_behavior_does_not_alarm_when_guard_appears_before_vehicle_leaves`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
#         `test_vehicle_behavior_keeps_checked_state_after_short_vehicle_detection_drop` 实例化本符号；另有 14 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：返回检测框的中心点坐标 (cx, cy)；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：Tuple[float, float]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def center(self) -> Tuple[float, float]:
        """返回检测框的中心点坐标 (cx, cy)。"""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


# 功能：单个跟踪目标的历史状态（当前未被核心流水线使用，保留供扩展）；输入与输出详见下方说明
# 参数：
#   - `track_id`（int）：目标跟踪标识
#   - `last_bbox`（BBox）：`last_bbox` 对应的业务输入值
#   - `last_center`（Tuple[float, float]）：`last_center` 对应的业务输入值
#   - `last_timestamp`（float）：`last_timestamp` 对应的业务输入值
#   - `motion_score`（float）：`motion_score` 对应的业务输入值
#   - `in_post_roi`（bool）：`in_post_roi` 对应的业务输入值
#   - `head_down_frames`（int）：`head_down_frames` 对应的业务输入值
#   - `phone_frames`（int）：`phone_frames` 对应的业务输入值
#   - `drowsy_frames`（int）：`drowsy_frames` 对应的业务输入值
#   - `visible`（bool）：`visible` 对应的业务输入值
#   - `history_centers`（List[Tuple[float, float]]）：`history_centers` 对应的业务输入值
#   - `extra`（Dict[str, float]）：`extra` 对应的业务输入值
# 返回：PersonState；返回新建的 `PersonState` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：单帧推理的完整上下文（当前未被核心流水线使用，保留供扩展）；输入与输出详见下方说明
# 参数：
#   - `timestamp_s`（float）：以秒表示的流时间戳
#   - `frame_index`（int）：视频流中的帧序号
#   - `fps`（float）：`fps` 对应的业务输入值
#   - `detections`（List[Detection]）：`detections` 对应的业务输入值
#   - `persons`（List[Detection]）：`persons` 对应的业务输入值
#   - `phones`（List[Detection]）：`phones` 对应的业务输入值
#   - `pose_features`（Dict[int, Dict[str, float]]）：`pose_features` 对应的业务输入值
# 返回：FrameContext；返回新建的 `FrameContext` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

# 功能：报警事件的完整描述，贯穿从触发到推送的完整生命周期；输入与输出详见下方说明
# 参数：
#   - `event_type`（str）：事件类型标识
#   - `timestamp_s`（float）：以秒表示的流时间戳
#   - `frame_index`（int）：视频流中的帧序号
#   - `track_id`（Optional[int]）：目标跟踪标识
#   - `confidence`（float）：模型预测或规则判断的置信度
#   - `reason`（str）：`reason` 对应的业务输入值
#   - `image_path`（Optional[str]）：`image_path` 对应的业务输入值
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `video_path`（Optional[str]）：`video_path` 对应的业务输入值
#   - `video_status`（str）：`video_status` 对应的业务输入值
# 返回：AlarmEvent；返回新建的 `AlarmEvent` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/alarms.py` 的 `AlarmManager::emit`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_media_cleanup.py` 的
#         `test_cleanup_rejects_symlinks_and_alarm_manager_prunes_memory`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_manager.py` 的
#         `test_runtime_manager_enriches_status_frame_and_alarms_with_site_metadata`
#         实例化本符号；`unified_frontend/src/components/human_dwell/monitorState.ts` 的 `filterTodayHumanDwellAlarms` 引用本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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