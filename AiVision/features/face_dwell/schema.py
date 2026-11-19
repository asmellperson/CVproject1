"""人脸逗留配置校验，时间以秒计，MAX_LOST 以跟踪更新次数计。"""
from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._shared.alarm_schema import AlarmConfigSchema
from AiVision.features._shared import defaults
from AiVision.features._shared.roi import NormalizedRoi

class FaceValueSchema(BaseModel):
    """约束检测置信度、去重与跟踪 IoU，以及逗留和丢失容忍参数。"""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    roi_pos: NormalizedRoi = Field(default_factory=list)
    FACE_SCORE_THR: float = Field(defaults.FACE_SCORE_THR, ge=0, le=1)  # InsightFace 检测置信度
    MAX_TIME: float = Field(defaults.MAX_TIME, ge=0)                                    # 同一条人脸跟踪轨迹达到这个逗留时间，并且本次仍匹配到了目标时，进入报警状态
    DETECTION_IOU_THR: float = Field(defaults.FACE_DETECTION_IOU_THR, ge=0, le=1)  # 检测框 NMS 去重 IoU
    TRACK_IOU_THR: float = Field(defaults.TRACK_IOU_THR, ge=0, le=1)  # 跨帧跟踪 IoU
    MAX_LOST: int = Field(defaults.MAX_LOST, ge=0)                                         # 默认第六次仍未匹配时删除轨迹
    cap_interval: float = Field(defaults.CAP_INTERVAL, gt=0)
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)


class FaceConfigSchema(BaseModel):
    """人脸逗留的启用开关、检测参数和告警通道配置。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    enable: bool = False
    value: FaceValueSchema = Field(default_factory=FaceValueSchema)
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)
