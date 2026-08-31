# 文件说明：实现配置相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

# config.py
"""
应用配置模块。

所有配置项以 Python dataclass 定义，通过 AppConfig.from_yaml() 从 YAML 文件加载。
各子配置按关注点分组，便于独立修改而不影响其他模块：

    video   —— 视频源与录制参数
    models  —— 模型路径与推理参数
    room    —— 画面分辨率
    rules   —— 行为规则阈值与冷却时间
    classes —— YOLO 类别 ID 映射
    runtime —— 调试与运行时开关
    wechat  —— 企业微信报警推送

配置加载流程：
    YAML 文件 → yaml.safe_load → 各子 dict → 对应 dataclass(**sub_dict) → AppConfig
    任何 YAML 中未出现的字段均使用 dataclass 定义的默认值，新增字段向后兼容。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# 子配置 dataclass
# ---------------------------------------------------------------------------

# 功能：视频输入与录制输出配置；输入与输出详见下方说明
# 参数：
#   - `source`（str）：`source` 对应的业务输入值
#   - `source_cam1`（str）：`source_cam1` 对应的业务输入值
#   - `source_cam2`（str）：`source_cam2` 对应的业务输入值
#   - `source_cam3`（str）：`source_cam3` 对应的业务输入值
#   - `process_every_n_frames`（int）：`process_every_n_frames` 对应的业务输入值
#   - `output_dir`（str）：`output_dir` 对应的业务输入值
#   - `save_annotated_video`（bool）：`save_annotated_video` 对应的业务输入值
#   - `annotated_video_fps`（int）：`annotated_video_fps` 对应的业务输入值
#   - `reconnect_seconds`（float）：`reconnect_seconds` 对应的时间间隔或时长
#   - `jpeg_quality`（int）：`jpeg_quality` 对应的业务输入值
#   - `camera_buffer_size`（int）：`camera_buffer_size` 对应的数量或大小
#   - `alarm_media_retention_days`（int）：`alarm_media_retention_days` 对应的业务输入值
#   - `alarm_media_max_gb`（float）：`alarm_media_max_gb` 对应的业务输入值
#   - `alarm_media_cleanup_interval_minutes`（int）：`alarm_media_cleanup_interval_minutes` 对应的时间间隔或时长
# 返回：VideoConfig；返回新建的 `VideoConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `AppConfig::from_yaml`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class VideoConfig:
    """视频输入与录制输出配置。

    摄像头源优先级：
        source_cam1 / source_cam2 / source_cam3 > source（兼容旧版单摄配置）。
    camera_sources() 方法按此优先级返回 (名称, URL) 列表。

    Attributes:
        source:                 旧版单摄像头源地址，新配置请改用 source_cam*。
        source_cam1/2/3:        多路摄像头 RTSP/文件地址，空字符串表示未配置。
        process_every_n_frames: 每隔 N 帧处理一次，用于降低 CPU/GPU 负载。
        output_dir:             报警快照、视频片段的根输出目录。
        save_annotated_video:   是否将标注后的画面录制为本地视频（调试用，磁盘占用大）。
        annotated_video_fps:    标注视频的写入帧率。
        reconnect_seconds:      摄像头断流后的重连等待时间（秒）。
        jpeg_quality:           MJPEG 流或快照的 JPEG 压缩质量（1~100）。
        camera_buffer_size:     OpenCV VideoCapture 内部缓冲帧数；设为 1 可降低延迟。
        alarm_media_retention_days: 报警图片和视频保留天数。
        alarm_media_max_gb:     alarms/alarm_clips/vehicle_clips 合计容量上限（GB）。
        alarm_media_cleanup_interval_minutes: 报警证据清理间隔（分钟）。
    """
    # 兼容旧字段
    source: str = ""

    # 多路摄像头（兼容现有双摄配置）
    source_cam1: str = ""
    source_cam2: str = ""
    source_cam3: str = ""

    process_every_n_frames: int = 3
    output_dir: str = "outputs"
    save_annotated_video: bool = False
    annotated_video_fps: int = 10
    reconnect_seconds: float = 1.0
    jpeg_quality: int = 80
    camera_buffer_size: int = 1
    alarm_media_retention_days: int = 7
    alarm_media_max_gb: float = 10.0
    alarm_media_cleanup_interval_minutes: int = 60


# 功能：模型路径与推理超参数配置；输入与输出详见下方说明
# 参数：
#   - `detector_model`（str）：`detector_model` 对应的业务输入值
#   - `vehicle_detector_model`（str）：`vehicle_detector_model` 对应的业务输入值
#   - `uniform_cls_model`（str）：`uniform_cls_model` 对应的业务输入值
#   - `pose_model_task`（str）：`pose_model_task` 对应的业务输入值
#   - `detector_conf`（float）：`detector_conf` 对应的业务输入值
#   - `phone_conf`（float）：`phone_conf` 对应的业务输入值
#   - `vehicle_conf`（float）：`vehicle_conf` 对应的业务输入值
#   - `detector_iou`（float）：`detector_iou` 对应的业务输入值
#   - `detector_imgsz`（int）：`detector_imgsz` 对应的业务输入值
#   - `vehicle_imgsz`（int）：`vehicle_imgsz` 对应的业务输入值
#   - `phone_crop_imgsz`（int）：`phone_crop_imgsz` 对应的业务输入值
#   - `phone_full_frame_imgsz`（int）：`phone_full_frame_imgsz` 对应的业务输入值
#   - `pose_imgsz`（int）：`pose_imgsz` 对应的业务输入值
#   - `use_half`（bool）：`use_half` 对应的业务输入值
#   - `tracker`（str）：`tracker` 对应的业务输入值
#   - `device`（str）：`device` 对应的业务输入值
#   - `uniform_cls_imgsz`（int）：`uniform_cls_imgsz` 对应的业务输入值
#   - `uniform_cls_conf`（float）：`uniform_cls_conf` 对应的业务输入值
# 返回：ModelConfig；返回新建的 `ModelConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `AppConfig::from_yaml`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class ModelConfig:
    """模型路径与推理超参数配置。

    Attributes:
        detector_model:     YOLO 检测模型权重路径（.pt），必填。
        vehicle_detector_model: YOLO11/COCO 车辆检测模型路径；为空时跳过车辆检测。
        uniform_cls_model:  制服分类模型路径；为空时跳过制服分类步骤。
        pose_model_task:    姿态估计任务标识；为空时跳过姿态估计。
        detector_conf:      检测置信度阈值，低于此值的框被过滤。
        phone_conf:         手机检测置信度阈值，独立于人体/主检测阈值。
        detector_iou:       NMS IoU 阈值，控制重叠框的合并程度。
        detector_imgsz:     人体检测输入尺寸，越小显存/算力占用越低。
        phone_crop_imgsz:   裁图手机检测输入尺寸。
        phone_full_frame_imgsz: 全图手机检测输入尺寸（调试模式）。
        pose_imgsz:         姿态模型输入尺寸。
        use_half:           CUDA 推理时是否使用 FP16，降低显存占用。
        tracker:            ByteTrack 配置文件名，由 Ultralytics 内置解析。
        device:             推理设备，如 "cuda:0"、"cpu"；为空时由框架自动选择。
        uniform_cls_imgsz:  制服分类模型的输入边长（正方形，像素）。
        uniform_cls_conf:   制服分类置信度阈值；低于此值不认定为保安制服。
    """
    detector_model: str                 # 必填，无默认值
    vehicle_detector_model: str = ""
    uniform_cls_model: str = ""
    pose_model_task: str = ""
    detector_conf: float = 0.35
    phone_conf: float = 0.35
    vehicle_conf: float = 0.35
    detector_iou: float = 0.45
    detector_imgsz: int = 960
    vehicle_imgsz: int = 960
    phone_crop_imgsz: int = 640
    phone_full_frame_imgsz: int = 960
    pose_imgsz: int = 640
    use_half: bool = True
    tracker: str = "bytetrack.yaml"
    device: str = ""
    uniform_cls_imgsz: int = 224
    uniform_cls_conf: float = 0.75


# 功能：画面分辨率配置，用于坐标归一化与区域判断；输入与输出详见下方说明
# 参数：
#   - `frame_width`（int）：`frame_width` 对应的业务输入值
#   - `frame_height`（int）：`frame_height` 对应的业务输入值
# 返回：RoomConfig；返回新建的 `RoomConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `AppConfig::from_yaml`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class RoomConfig:
    """画面分辨率配置，用于坐标归一化与区域判断。

    Attributes:
        frame_width:  期望处理的画面宽度（像素）。
        frame_height: 期望处理的画面高度（像素）。
    """
    frame_width: int = 1920
    frame_height: int = 1080


# 功能：行为规则阈值与报警冷却配置；输入与输出详见下方说明
# 参数：
#   - `absent_seconds`（int）：`absent_seconds` 对应的时间间隔或时长
#   - `phone_seconds`（int）：`phone_seconds` 对应的时间间隔或时长
#   - `prone_sleep_seconds`（int）：`prone_sleep_seconds` 对应的时间间隔或时长
#   - `vehicle_occlusion_seconds`（float）：`vehicle_occlusion_seconds` 对应的时间间隔或时长
#   - `phone_near_person_px`（int）：`phone_near_person_px` 对应的业务输入值
#   - `phone_near_head_px`（int）：`phone_near_head_px` 对应的业务输入值
#   - `vehicle_near_px`（int）：`vehicle_near_px` 对应的业务输入值
#   - `vehicle_roi`（list[list[float]]）：`vehicle_roi` 对应的业务输入值
#   - `vehicle_exit_direction`（str）：`vehicle_exit_direction` 对应的业务输入值
#   - `vehicle_direction_min_delta_ratio`（float）：`vehicle_direction_min_delta_ratio` 对应的业务输入值
#   - `vehicle_reassociate_seconds`（float）：`vehicle_reassociate_seconds` 对应的时间间隔或时长
#   - `static_motion_threshold`（float）：`static_motion_threshold` 对应的业务输入值
#   - `prone_head_down_ratio_threshold`（float）：`prone_head_down_ratio_threshold` 对应的业务输入值
#   - `prone_bbox_height_ratio_threshold`（float）：`prone_bbox_height_ratio_threshold` 对应的业务输入值
#   - `prone_consecutive_frames`（int）：`prone_consecutive_frames` 对应的业务输入值
#   - `state_ttl_seconds`（int）：`state_ttl_seconds` 对应的时间间隔或时长
#   - `phone_window_seconds`（int）：`phone_window_seconds` 对应的时间间隔或时长
#   - `phone_min_hits_in_window`（int）：`phone_min_hits_in_window` 对应的业务输入值
#   - `phone_grace_seconds`（int）：`phone_grace_seconds` 对应的时间间隔或时长
#   - `guard_hold_seconds`（float）：`guard_hold_seconds` 对应的时间间隔或时长
#   - `dual_sync_seconds`（float）：`dual_sync_seconds` 对应的时间间隔或时长
#   - `absent_alarm_seconds`（float）：`absent_alarm_seconds` 对应的时间间隔或时长
#   - `alarm_cooldown_absent`（int）：`alarm_cooldown_absent` 对应的业务输入值
#   - `alarm_cooldown_phone`（int）：`alarm_cooldown_phone` 对应的业务输入值
#   - `alarm_cooldown_prone_sleep`（int）：`alarm_cooldown_prone_sleep` 对应的业务输入值
#   - `alarm_cooldown_vehicle_unattended`（int）：`alarm_cooldown_vehicle_unattended` 对应的业务输入值
# 返回：RuleConfig；返回新建的 `RuleConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `AppConfig::from_yaml`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config` 实例化本符号；另有 1 处静态调用
#   - 内部调用：`field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class RuleConfig:
    """行为规则阈值与报警冷却配置。

    阈值分组说明：
        离岗检测    —— absent_seconds, absent_alarm_seconds
        手机检测    —— phone_* 系列
        趴睡检测    —— prone_* 系列
        跨摄像头    —— guard_hold_seconds, dual_sync_seconds
        报警冷却    —— alarm_cooldown_* 系列

    Attributes:
        absent_seconds:                    画面连续无人超过此时长（秒）才触发离岗。
        phone_seconds:                     手机证据连续激活超过此时长（秒）才触发报警。
        prone_sleep_seconds:               趴睡特征持续超过此时长（秒）才触发报警。
        phone_near_person_px:              手机框中心到人体框的水平容差（像素）。
        phone_near_head_px:                手机框中心到头部估计点的距离阈值（像素）。
        vehicle_near_px:                   保安靠近车辆的空间容差（像素）。
        vehicle_roi:                       车辆检测 ROI，归一化多边形点列表；为空表示全画面。
        vehicle_exit_direction:            出厂车辆在画面中的移动方向，any/right/left/down/up。
        vehicle_direction_min_delta_ratio:  方向判定所需最小位移比例，避免抖动误判。
        vehicle_reassociate_seconds:       已检查车辆断检后允许继承检查状态的时间窗口。
        static_motion_threshold:           帧间中心点位移低于此值（像素）视为静止。
        prone_head_down_ratio_threshold:   head_down_ratio 超过此值才认定为低头。
        prone_bbox_height_ratio_threshold: 人体框高度/画面高度低于此比例视为水平姿态。
        prone_consecutive_frames:          低头特征连续成立的帧数阈值，触发趴睡候选。
        state_ttl_seconds:                 目标跟踪状态在最后一次出现后的保留时间（秒）。
        phone_window_seconds:              手机检测的滑动时间窗口长度（秒）。
        phone_min_hits_in_window:          窗口内最少命中帧数，达到后才认为证据充分。
        phone_grace_seconds:               手机证据消失后允许的宽限期（秒），容忍短暂漏检。
        guard_hold_seconds:                保安识别结果的最小持续时间（秒），防止闪烁。
        dual_sync_seconds:                 双摄像头行为结论的时间同步窗口（秒）。
        absent_alarm_seconds:              离岗报警后的最小持续确认时间（秒）。
        alarm_cooldown_absent:             离岗报警的最小触发间隔（秒），默认 120。
        alarm_cooldown_phone:              手机报警的最小触发间隔（秒），默认 60。
        alarm_cooldown_prone_sleep:        趴睡报警的最小触发间隔（秒），默认 300。
        alarm_cooldown_vehicle_unattended: 车辆无人值守报警的最小触发间隔（秒）。
    """
    # ── 持续时长阈值 ───────────────────────────────────────────────────────
    absent_seconds: int = 900           # 15 分钟无人才报警
    phone_seconds: int = 300            # 玩手机 5 分钟才报警
    prone_sleep_seconds: int = 300      # 趴睡 5 分钟才报警
    vehicle_occlusion_seconds: float = 2.0  # 车辆连续消失达到该时长后确认离开

    # ── 手机空间过滤阈值 ───────────────────────────────────────────────────
    phone_near_person_px: int = 220
    phone_near_head_px: int = 160
    vehicle_near_px: int = 160
    vehicle_roi: list[list[float]] = field(default_factory=list)
    vehicle_exit_direction: str = "any"
    vehicle_direction_min_delta_ratio: float = 0.03
    vehicle_reassociate_seconds: float = 10.0

    # ── 运动量与姿态阈值 ───────────────────────────────────────────────────
    static_motion_threshold: float = 8.0
    prone_head_down_ratio_threshold: float = 0.22
    prone_bbox_height_ratio_threshold: float = 0.18
    prone_consecutive_frames: int = 8

    # ── 状态管理 ───────────────────────────────────────────────────────────
    state_ttl_seconds: int = 20         # 目标消失 20 秒后清理运行时状态

    # ── 手机时间窗口参数 ───────────────────────────────────────────────────
    phone_window_seconds: int = 3       # 滑动窗口长度
    phone_min_hits_in_window: int = 5   # 窗口内最少命中帧数（3 秒内 5 帧 ≈ 每秒约 1.7 帧）
    phone_grace_seconds: int = 2        # 漏检宽限期

    # ── 保安识别与双摄共识 ─────────────────────────────────────────────────
    guard_hold_seconds: float = 1.3     # 保安识别结果平滑窗口
    dual_sync_seconds: float = 1.5      # 两路摄像头结论需在此时间窗内对齐
    absent_alarm_seconds: float = 60.0  # 离岗报警的最小确认持续时长

    # ── 报警冷却（防止同一事件短时内重复推送）────────────────────────────
    alarm_cooldown_absent: int = 120        # 离岗：冷却 2 分钟
    alarm_cooldown_phone: int = 60          # 手机：冷却 1 分钟
    alarm_cooldown_prone_sleep: int = 300   # 趴睡：冷却 5 分钟
    alarm_cooldown_vehicle_unattended: int = 300


# 功能：YOLO 检测模型的类别 ID 映射；输入与输出详见下方说明
# 参数：
#   - `person`（int）：`person` 对应的业务输入值
#   - `play_phone`（int）：`play_phone` 对应的业务输入值
#   - `vehicle_bicycle`（int）：`vehicle_bicycle` 对应的业务输入值
#   - `vehicle_car`（int）：`vehicle_car` 对应的业务输入值
#   - `vehicle_motorcycle`（int）：`vehicle_motorcycle` 对应的业务输入值
# 返回：ClassConfig；返回新建的 `ClassConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `AppConfig::from_yaml`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class ClassConfig:
    """YOLO 检测模型的类别 ID 映射。

    与模型训练时的 data.yaml 保持一致；更换模型时需同步修改此处。

    Attributes:
        person:     人体类别 ID。
        play_phone: 玩手机类别 ID。
        vehicle_*:  YOLO11 COCO 预训练车辆相关类别 ID。
    """
    person: int = 0
    play_phone: int = 1
    vehicle_bicycle: int = 1
    vehicle_car: int = 2
    vehicle_motorcycle: int = 3


# 功能：运行时行为开关，通常不写入生产 YAML，仅用于本地调试；输入与输出详见下方说明
# 参数：
#   - `show_window`（bool）：`show_window` 对应的业务输入值
#   - `debug`（bool）：`debug` 对应的业务输入值
#   - `draw_debug`（bool）：`draw_debug` 对应的业务输入值
#   - `max_alarm_history`（int）：`max_alarm_history` 对应的业务输入值
#   - `infer_max_workers`（int）：`infer_max_workers` 对应的业务输入值
#   - `share_phone_detector`（bool）：`share_phone_detector` 对应的业务输入值
#   - `share_pose_estimator`（bool）：`share_pose_estimator` 对应的业务输入值
#   - `phone_detect_mode`（str）：`phone_detect_mode` 对应的业务输入值
#   - `enable_vehicle_unattended`（bool）：`enable_vehicle_unattended` 对应的业务输入值
#   - `vehicle_camera_id`（str）：`vehicle_camera_id` 对应业务对象的唯一标识
# 返回：RuntimeConfig；返回新建的 `RuntimeConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `AppConfig::from_yaml`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class RuntimeConfig:
    """运行时行为开关，通常不写入生产 YAML，仅用于本地调试。

    Attributes:
        show_window:        是否弹出 OpenCV 预览窗口（无头服务器需设为 False）。
        debug:              是否输出详细调试日志。
        draw_debug:         是否在画面上绘制调试信息（骨骼点、规则状态等）。
        max_alarm_history:  内存中保留的最大报警事件条数，防止长时间运行内存膨胀。
        infer_max_workers:  摄像头推理线程数上限；GPU 显存紧张时建议为 1。
        share_phone_detector: 裁图手机检测复用各摄像头人体检测模型，少加载一份 YOLO。
        share_pose_estimator: 多路摄像头共享一份姿态模型，少加载 N-1 份姿态模型。
        phone_detect_mode:  手机检测范围模式：
                              "guard_crop"      —— 仅对识别为保安的区域裁图检测（推荐）；
                              "full_frame_test" —— 对全图检测，用于调试误检问题。
        enable_vehicle_unattended: 是否启用车辆无人值守检测。
        vehicle_camera_id:  执行车辆检测的单路摄像头 ID，如 "cam1"。
    """
    show_window: bool = False
    debug: bool = True
    draw_debug: bool = False
    max_alarm_history: int = 1000
    infer_max_workers: int = 1
    share_phone_detector: bool = True
    share_pose_estimator: bool = True
    phone_detect_mode: str = "guard_crop"
    enable_vehicle_unattended: bool = True
    vehicle_camera_id: str = "cam1"


# 功能：企业微信应用消息推送配置；输入与输出详见下方说明
# 参数：
#   - `enable`（bool）：`enable` 对应的业务输入值
#   - `corpid`（str）：`corpid` 对应的业务输入值
#   - `corpsecret`（str）：`corpsecret` 对应的业务输入值
#   - `agentid`（int）：`agentid` 对应的业务输入值
#   - `alarm_user`（str）：`alarm_user` 对应的业务输入值
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `clip_seconds`（float）：`clip_seconds` 对应的时间间隔或时长
#   - `enable_phone`（bool）：`enable_phone` 对应的业务输入值
#   - `enable_absent`（bool）：`enable_absent` 对应的业务输入值
#   - `enable_prone_sleep`（bool）：`enable_prone_sleep` 对应的业务输入值
# 返回：WeChatConfig；返回新建的 `WeChatConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `AppConfig::from_yaml`
#         实例化本符号；`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config` 实例化本符号；另有 1 处静态调用
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class WeChatConfig:
    """企业微信应用消息推送配置。

    需在企业微信管理后台创建自建应用并获取以下凭证。
    enable=False 时整个推送流程被跳过，不发起任何网络请求。

    Attributes:
        enable:             总开关；False 时忽略所有推送逻辑。
        corpid:             企业微信企业 ID（CorpID）。
        corpsecret:         自建应用的 Secret。
        agentid:            自建应用的 AgentID。
        alarm_user:         接收报警消息的成员账号，多人用 '|' 分隔，"@all" 表示全体。
        camera_name:        推送消息中显示的摄像头名称，便于接收方区分报警来源。
        clip_seconds:       报警视频片段时长（秒），与 AlarmClipRecorder 保持一致。
        enable_phone:       是否推送手机报警。
        enable_absent:      是否推送离岗报警。
        enable_prone_sleep: 是否推送趴睡报警。
    """
    enable: bool = False
    corpid: str = ""
    corpsecret: str = ""
    agentid: int = 1000050
    alarm_user: str = ""
    camera_name: str = "值班室双摄像头"
    clip_seconds: float = 5.0
    enable_phone: bool = True
    enable_absent: bool = True
    enable_prone_sleep: bool = True


# ---------------------------------------------------------------------------
# 顶层配置聚合
# ---------------------------------------------------------------------------

# 功能：应用全局配置，聚合所有子配置；输入与输出详见下方说明
# 参数：
#   - `video`（VideoConfig）：`video` 对应的业务输入值
#   - `models`（ModelConfig）：`models` 对应的业务输入值
#   - `room`（RoomConfig）：`room` 对应的业务输入值
#   - `rules`（RuleConfig）：`rules` 对应的业务输入值
#   - `classes`（ClassConfig）：`classes` 对应的业务输入值
#   - `runtime`（RuntimeConfig）：`runtime` 对应的业务输入值
#   - `wechat`（WeChatConfig）：`wechat` 对应的业务输入值
# 返回：AppConfig；返回新建的 `AppConfig` 实例。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_app_config_from_sections`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_phone_conf.py` 的
#         `test_phone_crop_detection_uses_phone_conf_instead_of_scaled_detector_conf`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_state_guard_status.py` 的 `_config`
#         实例化本符号；`AiVision/integrations/guard_room/tests/test_runtime_paths.py` 的 `_config` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass
class AppConfig:
    """应用全局配置，聚合所有子配置。

    通常通过 from_yaml() 从文件加载，也可在测试中直接构造。
    """
    video: VideoConfig
    models: ModelConfig
    room: RoomConfig
    rules: RuleConfig
    classes: ClassConfig
    runtime: RuntimeConfig
    wechat: WeChatConfig

    # 功能：返回有效摄像头的 (名称, 源地址) 列表；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：list[tuple[str, str]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/state.py` 的 `AppState::__init__`
    #         调用本符号；`AiVision/integrations/guard_room/src/state.py` 的 `AppState::set_config`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_site_service.py` 的
    #         `test_site_service_creates_site_cameras_and_app_config` 调用本符号；`AiVision/integrations/guard_room/src/runtime.py` 的
    #         `GuardRoomRuntime::start` 调用本符号；另有 1 处静态调用
    #   - 内部调用：`range`、`(getattr(video, f'source_cam{idx}', '') or '').strip`、`getattr`、`sources.append`、`(video.source or
    #          '').strip`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def camera_sources(self) -> list[tuple[str, str]]:
        """返回有效摄像头的 (名称, 源地址) 列表。

        优先使用 source_cam1~9 的多路配置；均未配置时回落到旧版 source 字段。
        调用方遍历此列表即可获得所有需要启动的摄像头，无需关心兼容逻辑。

        Returns:
            非空的 [(名称, 源地址), ...] 列表；无任何有效源时返回空列表。
        """
        video = self.video
        sources: list[tuple[str, str]] = []

        # 按编号顺序收集 source_cam1 ~ source_cam9
        for idx in range(1, 10):
            value = (getattr(video, f"source_cam{idx}", "") or "").strip()
            if value:
                sources.append((f"cam{idx}", value))

        if sources:
            return sources

        # 回落：旧版单摄像头配置
        fallback = (video.source or "").strip()
        return [("cam1", fallback)] if fallback else []

    # 功能：从 YAML 文件加载并构造 AppConfig；输入与输出详见下方说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `path`（str | Path）：目标路径
    # 返回：'AppConfig'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_load_default_config`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_vehicle_behavior_does_not_alarm_when_guard_appears_before_vehicle_leaves`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_vehicle_behavior_keeps_checked_state_after_short_vehicle_detection_drop`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_vehicle_detection.py` 的
    #         `test_vehicle_behavior_reassociates_checked_vehicle_that_reappears_along_exit_direction` 调用本符号；另有 14 处静态调用
    #   - 内部调用：`open`、`yaml.safe_load`、`dict`、`data.get`、`video_data.get`、`cls`、`VideoConfig`、`ModelConfig`、`RoomConfig`、`RuleConfig`
    #          等共 13 个调用。
    # 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能发起网络请求或发送外部消息。
    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        """从 YAML 文件加载并构造 AppConfig。

        各子节点缺失时使用对应 dataclass 的默认值，新字段向后兼容。
        source_cam1 存在而 source 缺失时自动回填 source，保持旧版字段可用。

        Args:
            path: YAML 配置文件路径。

        Returns:
            完整填充的 AppConfig 实例。
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        video_data = dict(data.get("video") or {})
        # 兼容旧版：仅当 source 为空且 source_cam1 有值时自动回填
        if not video_data.get("source") and video_data.get("source_cam1"):
            video_data["source"] = video_data["source_cam1"]

        return cls(
            video=VideoConfig(**video_data),
            models=ModelConfig(**(data.get("models") or {})),
            room=RoomConfig(**(data.get("room") or {})),
            rules=RuleConfig(**(data.get("rules") or {})),
            classes=ClassConfig(**(data.get("classes") or {})),
            runtime=RuntimeConfig(**(data.get("runtime") or {})),
            wechat=WeChatConfig(**(data.get("wechat") or {})),
        )

    # 功能：将完整配置序列化为嵌套字典，可直接用于 json.dump 或写回 YAML；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/service.py` 的 `GuardRoomService::_config_sections`
    #         调用本符号；`AiVision/integrations/guard_room/src/state.py` 的 `AppState::get_config_dict`
    #         调用本符号；`AiVision/integrations/guard_room/tests/test_legacy_data_migration.py` 的 `_seed_legacy_database`
    #         调用本符号；`AiVision/integrations/guard_room/src/legacy_data_migration.py` 的 `_load_default_sections` 调用本符号
    #   - 内部调用：`asdict`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    def to_dict(self) -> dict[str, Any]:
        """将完整配置序列化为嵌套字典，可直接用于 json.dump 或写回 YAML。"""
        return {
            "video": asdict(self.video),
            "models": asdict(self.models),
            "room": asdict(self.room),
            "rules": asdict(self.rules),
            "classes": asdict(self.classes),
            "runtime": asdict(self.runtime),
            "wechat": asdict(self.wechat),
        }


# 功能：返回供推理运行时使用的副本，并把 Guard 本地路径锚定到项目目录；输入与输出详见下方说明
# 参数：
#   - `config`（AppConfig）：运行配置对象
#   - `project_root`（str | Path）：`project_root` 对应的业务输入值
# 返回：AppConfig；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/integrations/guard_room/src/runtime_manager.py` 的 `GuardRoomRuntimeManager::_get_or_create_context`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_runtime_paths.py` 的
#         `test_runtime_paths_are_anchored_without_changing_persisted_config`
#         调用本符号；`AiVision/integrations/guard_room/tests/test_runtime_paths.py` 的
#         `test_runtime_paths_keep_urls_device_indexes_and_absolute_paths` 调用本符号；`AiVision/integrations/guard_room/src/server.py` 的
#         `create_app` 调用本符号
#   - 内部调用：`deepcopy`、`Path(project_root).resolve`、`Path`、`output_dir.is_absolute`、`str`、`output_dir.resolve`、`setattr`、`local_path`、`getattr`、`range`
#          等共 11 个调用。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def resolve_runtime_paths(config: AppConfig, project_root: str | Path) -> AppConfig:
    """返回供推理运行时使用的副本，并把 Guard 本地路径锚定到项目目录。

    API 与数据库仍保存用户填写的原始值；只有交给模型和文件写入器的副本使用
    绝对路径，因此从 ``guard_room`` 独立进程迁入 AiVision 后不会依赖当前工作目录。
    """
    resolved = deepcopy(config)
    root = Path(project_root).resolve()

    # 功能：实现 `local_path` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `value`（str）：待转换、校验或写入的值
    #   - `require_path_hint`（bool）：`require_path_hint` 对应的业务输入值；默认值为 `False`
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/integrations/guard_room/src/config.py` 的 `resolve_runtime_paths` 调用本符号
    #   - 内部调用：`str(value or '').strip`、`str`、`Path`、`path.is_absolute`、`(root /
    #          path).resolve`、`len`、`raw.startswith`、`candidate.exists`。
    # 副作用/注意事项：可能启动、等待或停止线程/进程资源。
    def local_path(value: str, *, require_path_hint: bool = False) -> str:
        raw = str(value or "").strip()
        if not raw:
            return raw
        path = Path(raw)
        if path.is_absolute():
            return str(path)
        candidate = (root / path).resolve()
        has_path_hint = len(path.parts) > 1 or raw.startswith(".")
        if candidate.exists() or (require_path_hint and has_path_hint):
            return str(candidate)
        return raw

    output_dir = Path(resolved.video.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    resolved.video.output_dir = str(output_dir.resolve())

    for field_name in (
        "detector_model",
        "vehicle_detector_model",
        "uniform_cls_model",
        "pose_model_task",
    ):
        setattr(
            resolved.models,
            field_name,
            local_path(getattr(resolved.models, field_name, ""), require_path_hint=True),
        )

    resolved.models.tracker = local_path(resolved.models.tracker)

    for field_name in ("source", *(f"source_cam{index}" for index in range(1, 10))):
        value = getattr(resolved.video, field_name, "")
        if isinstance(value, str):
            setattr(resolved.video, field_name, local_path(value))

    return resolved
