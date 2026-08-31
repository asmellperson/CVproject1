# 文件说明：定义数据结构的数据结构与类型契约。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_phone/schema.py"""
from typing import List
from pydantic import BaseModel, Field, field_validator


# 功能：定义 `PhoneValueSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `roi_pos`（List[List[List[int]]]）：`roi_pos` 对应的业务输入值
#   - `CONF_THRESHOLD`（float）：`CONF_THRESHOLD` 对应的业务输入值
#   - `IOU_THR`（float）：`IOU_THR` 对应的业务输入值
#   - `cap_interval`（float）：`cap_interval` 对应的时间间隔或时长
#   - `alarm_interval`（float）：`alarm_interval` 对应的时间间隔或时长
#   - `MIN_CONFIRM_SECONDS`（float）：`MIN_CONFIRM_SECONDS` 对应的时间间隔或时长
#   - `MIN_CONSECUTIVE_HITS`（int）：`MIN_CONSECUTIVE_HITS` 对应的业务输入值
#   - `MAX_MISSED_SECONDS`（float）：`MAX_MISSED_SECONDS` 对应的时间间隔或时长
#   - `TRACK_TTL_SECONDS`（float）：`TRACK_TTL_SECONDS` 对应的时间间隔或时长
#   - `TRACK_IOU_THRESHOLD`（float）：`TRACK_IOU_THRESHOLD` 对应的业务输入值
#   - `PERSON_CONF_THRESHOLD`（float）：`PERSON_CONF_THRESHOLD` 对应的业务输入值
#   - `PERSON_IOU_THR`（float）：`PERSON_IOU_THR` 对应的业务输入值
#   - `REQUIRE_PERSON_ASSOCIATION`（bool）：`REQUIRE_PERSON_ASSOCIATION` 对应的业务输入值
#   - `PERSON_EXPAND_RATIO`（float）：`PERSON_EXPAND_RATIO` 对应的业务输入值
#   - `HAND_REGION_MAX_Y_RATIO`（float）：`HAND_REGION_MAX_Y_RATIO` 对应的业务输入值
#   - `MIN_PERSON_PHONE_OVERLAP`（float）：`MIN_PERSON_PHONE_OVERLAP` 对应的业务输入值
# 返回：PhoneValueSchema；返回新建的 `PhoneValueSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PhoneValueSchema(BaseModel):
    roi_pos: List[List[List[int]]] = Field(default_factory=list)
    CONF_THRESHOLD: float = Field(0.7, ge=0, le=1)
    IOU_THR: float = Field(0.5, ge=0, le=1)
    cap_interval: float = Field(0.1, gt=0)
    alarm_interval: float = Field(5.0, gt=0)
    MIN_CONFIRM_SECONDS: float = Field(1.2, ge=0)
    MIN_CONSECUTIVE_HITS: int = Field(3, ge=1)
    MAX_MISSED_SECONDS: float = Field(0.6, ge=0)
    TRACK_TTL_SECONDS: float = Field(2.0, gt=0)
    TRACK_IOU_THRESHOLD: float = Field(0.2, ge=0, le=1)
    PERSON_CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    PERSON_IOU_THR: float = Field(0.3, ge=0, le=1)
    REQUIRE_PERSON_ASSOCIATION: bool = True
    PERSON_EXPAND_RATIO: float = Field(0.18, ge=0, le=1)
    HAND_REGION_MAX_Y_RATIO: float = Field(0.85, ge=0, le=1.5)
    MIN_PERSON_PHONE_OVERLAP: float = Field(0.08, ge=0, le=1)

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


# 功能：定义 `PhoneAlarmSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `sql`（_AlarmChannel）：`sql` 对应的业务输入值
#   - `horn`（_AlarmChannel）：`horn` 对应的业务输入值
#   - `wechat`（_WechatChannel）：`wechat` 对应的业务输入值
# 返回：PhoneAlarmSchema；返回新建的 `PhoneAlarmSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PhoneAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


# 功能：定义 `PhoneConfigSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `enable`（bool）：`enable` 对应的业务输入值
#   - `value`（PhoneValueSchema）：待转换、校验或写入的值
#   - `alarm`（PhoneAlarmSchema）：`alarm` 对应的业务输入值
# 返回：PhoneConfigSchema；返回新建的 `PhoneConfigSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class PhoneConfigSchema(BaseModel):
    enable: bool = False
    value: PhoneValueSchema = Field(default_factory=PhoneValueSchema)
    alarm: PhoneAlarmSchema = Field(default_factory=PhoneAlarmSchema)
