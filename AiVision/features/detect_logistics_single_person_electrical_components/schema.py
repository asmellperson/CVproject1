# 文件说明：定义数据结构的数据结构与类型契约。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""features/detect_logistics_single_person_electrical_components/schema.py"""
from typing import List

from pydantic import BaseModel, Field


# 功能：定义 `LogisticsSinglePersonElectricalComponentsValueSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `CONF_THRESHOLD`（float）：`CONF_THRESHOLD` 对应的业务输入值
#   - `IOU_THR`（float）：`IOU_THR` 对应的业务输入值
#   - `roi_pos`（list）：`roi_pos` 对应的业务输入值
#   - `region`（List[int]）：`region` 对应的业务输入值
#   - `MIN_BOX_AREA`（int）：`MIN_BOX_AREA` 对应的业务输入值
#   - `ASPECT_RATIO_RANGE`（List[float]）：`ASPECT_RATIO_RANGE` 对应的业务输入值
#   - `empty_grace_seconds`（float）：`empty_grace_seconds` 对应的时间间隔或时长
#   - `multi_grace_seconds`（float）：`multi_grace_seconds` 对应的时间间隔或时长
#   - `cap_interval`（float）：`cap_interval` 对应的时间间隔或时长
#   - `alarm_interval`（float）：`alarm_interval` 对应的时间间隔或时长
# 返回：LogisticsSinglePersonElectricalComponentsValueSchema；返回新建的 `LogisticsSinglePersonElectricalComponentsValueSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsSinglePersonElectricalComponentsValueSchema(BaseModel):
    CONF_THRESHOLD: float = Field(0.3, ge=0, le=1)
    IOU_THR: float = Field(0.3, ge=0, le=1)
    roi_pos: list = Field(default_factory=list)
    region: List[int] = Field(default_factory=list)
    MIN_BOX_AREA: int = Field(0, ge=0)
    ASPECT_RATIO_RANGE: List[float] = Field(default_factory=lambda: [0.0, 10.0])
    empty_grace_seconds: float = Field(2.0, ge=0)
    multi_grace_seconds: float = Field(1.0, ge=0)
    cap_interval: float = Field(0.2, gt=0)
    alarm_interval: float = Field(5.0, gt=0)


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


# 功能：定义 `LogisticsSinglePersonElectricalComponentsAlarmSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `sql`（_AlarmChannel）：`sql` 对应的业务输入值
#   - `horn`（_AlarmChannel）：`horn` 对应的业务输入值
#   - `wechat`（_WechatChannel）：`wechat` 对应的业务输入值
# 返回：LogisticsSinglePersonElectricalComponentsAlarmSchema；返回新建的 `LogisticsSinglePersonElectricalComponentsAlarmSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsSinglePersonElectricalComponentsAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


# 功能：定义 `LogisticsSinglePersonElectricalComponentsConfigSchema` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `enable`（bool）：`enable` 对应的业务输入值
#   - `value`（LogisticsSinglePersonElectricalComponentsValueSchema）：待转换、校验或写入的值
#   - `alarm`（LogisticsSinglePersonElectricalComponentsAlarmSchema）：`alarm` 对应的业务输入值
# 返回：LogisticsSinglePersonElectricalComponentsConfigSchema；返回新建的 `LogisticsSinglePersonElectricalComponentsConfigSchema` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsSinglePersonElectricalComponentsConfigSchema(BaseModel):
    enable: bool = False
    value: LogisticsSinglePersonElectricalComponentsValueSchema = Field(default_factory=LogisticsSinglePersonElectricalComponentsValueSchema)
    alarm: LogisticsSinglePersonElectricalComponentsAlarmSchema = Field(default_factory=LogisticsSinglePersonElectricalComponentsAlarmSchema)
