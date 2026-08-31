# 文件说明：定义数据结构的数据结构与类型契约。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_door/schema.py"""
from typing import List
from pydantic import BaseModel, Field, field_validator


# 功能：定义 `DoorValueSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `roi_pos`（List[List[List[int]]]）：`roi_pos` 对应的业务输入值
#   - `threshold`（float）：`threshold` 对应的业务输入值
#   - `blur_kernel`（int）：`blur_kernel` 对应的业务输入值
#   - `diff_threshold`（int）：`diff_threshold` 对应的业务输入值
#   - `diff_threshold_env`（int）：`diff_threshold_env` 对应的业务输入值
#   - `env_threshold`（float）：`env_threshold` 对应的业务输入值
#   - `first_alarm`（int）：`first_alarm` 对应的业务输入值
#   - `stable_confirm_seconds`（float）：`stable_confirm_seconds` 对应的时间间隔或时长
#   - `stable_confirm_hits`（int）：`stable_confirm_hits` 对应的业务输入值
#   - `background_update_alpha`（float）：`background_update_alpha` 对应的业务输入值
#   - `global_motion_threshold`（float）：`global_motion_threshold` 对应的业务输入值
#   - `min_local_change_ratio`（float）：`min_local_change_ratio` 对应的业务输入值
#   - `cap_interval`（float）：`cap_interval` 对应的时间间隔或时长
#   - `alarm_interval`（float）：`alarm_interval` 对应的时间间隔或时长
# 返回：DoorValueSchema；返回新建的 `DoorValueSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DoorValueSchema(BaseModel):
    roi_pos: List[List[List[int]]] = Field(default_factory=list)
    threshold: float = Field(0.5, ge=0)
    blur_kernel: int = Field(5, ge=1)
    diff_threshold: int = Field(5, ge=0)
    diff_threshold_env: int = Field(10, ge=0)
    env_threshold: float = Field(10.0, ge=0)
    first_alarm: int = Field(60, ge=0)
    stable_confirm_seconds: float = Field(1.0, ge=0)
    stable_confirm_hits: int = Field(3, ge=1)
    background_update_alpha: float = Field(0.05, ge=0, le=1)
    global_motion_threshold: float = Field(0.22, ge=0)
    min_local_change_ratio: float = Field(0.01, ge=0, le=1)
    cap_interval: float = Field(0.1, gt=0)
    alarm_interval: float = Field(5.0, gt=0)

    # 功能：转换或规范化 `_normalize_roi` 对应的数据结构逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `v`（未显式标注）：`v` 对应的业务输入值
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`isinstance`、`field_validator`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @field_validator("roi_pos", mode="before")
    @classmethod
    def _normalize_roi(cls, v):
        if not isinstance(v, list) or not v:
            return v
        first = v[0]
        if isinstance(first, list) and first and not isinstance(first[0], list):
            return [v]
        return v


# 功能：定义 `_AlarmChannel` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `enable`（bool）：`enable` 对应的业务输入值
#   - `parm`（dict）：`parm` 对应的业务输入值
# 返回：_AlarmChannel；返回新建的 `_AlarmChannel` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _AlarmChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=dict)


# 功能：定义 `_WechatChannel` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `enable`（bool）：`enable` 对应的业务输入值
#   - `parm`（dict）：`parm` 对应的业务输入值
# 返回：_WechatChannel；返回新建的 `_WechatChannel` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class _WechatChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=lambda: {"user": ""})


# 功能：定义 `DoorAlarmSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `sql`（_AlarmChannel）：`sql` 对应的业务输入值
#   - `horn`（_AlarmChannel）：`horn` 对应的业务输入值
#   - `wechat`（_WechatChannel）：`wechat` 对应的业务输入值
# 返回：DoorAlarmSchema；返回新建的 `DoorAlarmSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DoorAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


# 功能：定义 `DoorConfigSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `enable`（bool）：`enable` 对应的业务输入值
#   - `value`（DoorValueSchema）：待转换、校验或写入的值
#   - `alarm`（DoorAlarmSchema）：`alarm` 对应的业务输入值
# 返回：DoorConfigSchema；返回新建的 `DoorConfigSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class DoorConfigSchema(BaseModel):
    enable: bool = False
    value: DoorValueSchema = Field(default_factory=DoorValueSchema)
    alarm: DoorAlarmSchema = Field(default_factory=DoorAlarmSchema)
