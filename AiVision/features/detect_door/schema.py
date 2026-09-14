"""features/detect_door/schema.py"""
from pydantic import BaseModel, ConfigDict, Field

from AiVision.features._base.alarm_schema import AlarmConfigSchema
from AiVision.features._base import defaults
from AiVision.features._base.roi import NormalizedRoi

class DoorValueSchema(BaseModel):
    """负责校验检测相关参数"""
    # extra="forbid"不能出现未定义字段
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    # 指定检测区域的多边形坐标，坐标归一化到0~1，空列表使用全帧
    roi_pos: NormalizedRoi = Field(default_factory=list)
    threshold: float = Field(0.5, ge=0, le=1)        # 相对背景的变化比例下限，默认至少50%判定为变化，ge： 值必须大于等于0
    diff_threshold: int = Field(5, ge=0)       # 当前图像与背景图像单像素差值阈值。灰度值大于5，才把这个像素记为变化
    diff_threshold_env: int = Field(10, ge=0)  # 当前图像与上一张处理图像的单像素差值阈值。差值大于10的像素被计入运动比例，用来检查画面是否剧烈变化
    env_threshold: float | None = Field(defaults.DOOR_ENV_THRESHOLD, ge=0, le=1)  # null 关闭环境变化过滤；数值为比例上限
    first_alarm: int = Field(defaults.DOOR_FIRST_ALARM, ge=0)         # 稳定确认通过后，变化还需要持续多久，才允许首次报警
    stable_confirm_seconds: float = Field(1.0, ge=0)  # 变化条件至少连续维持多久，才算确认有效
    stable_confirm_hits: int = Field(3, ge=1)         # 变化时间至少连续满足多少次
    background_update_alpha: float = Field(0.05, ge=0, le=1)    # 更新参考背景时，新画面所占的权重，默认新画面占5%，旧背景占95%
    global_motion_threshold: float = Field(0.22, ge=0, le=1)          # 当前图像相对上一张处理图像，变化像素超过22%时判为背景不稳定
    min_local_change_ratio: float = Field(0.01, ge=0, le=1)     # 变化比例的另一道下限，与threshold检查的是同一个比例，默认要求变化至少变化1%
    cap_interval: float = Field(defaults.CAP_INTERVAL, gt=0)                      # 在画面没有显著变化时，允许继续处理的间隔，默认每0.1秒检查一次
    alarm_interval: float = Field(defaults.ALARM_INTERVAL, gt=0)                    # 报警冷却


class DoorConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # 一份完整的配置由下面三个键组成
    enable: bool = False                  # 是否启用门检测，默认关闭
    value: DoorValueSchema = Field(default_factory=DoorValueSchema)    # ROI、阈值、持续时间等检测参数
    alarm: AlarmConfigSchema = Field(default_factory=AlarmConfigSchema)    # 数据库、喇叭、微信的报警配置
