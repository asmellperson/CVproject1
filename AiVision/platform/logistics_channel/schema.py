# 文件说明：定义数据结构的数据结构与类型契约。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""物流通道 API 的 Pydantic DTO。"""
from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from AiVision.platform.alarm_device.binding import MAX_HORN_ID

from .constants import (
    DEFAULT_DETECTION_END,
    DEFAULT_DETECTION_START,
    DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
    MAX_CAMERAS_PER_CHANNEL,
)


LogisticsFeatureName = Literal[
    "detect_logistics_single_person",
    "detect_logistics_single_person_electronics_electrician",
    "detect_logistics_single_person_electrical_components",
    "detect_logistics_single_person_precious_metal_recycling",
]
LogisticsChannelStatusReason = Literal[
    "normal", "empty", "multiple", "unknown", "unconfigured", "inactive",
]


# 功能：定义 `LogisticsChannelAlarmChannel` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `enabled`（bool）：是否启用相应能力
#   - `horn_id`（int | None）：`horn_id` 对应业务对象的唯一标识
#   - `horn_event_id`（int | None）：`horn_event_id` 对应业务对象的唯一标识
# 返回：LogisticsChannelAlarmChannel；返回新建的 `LogisticsChannelAlarmChannel` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelAlarmChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    horn_id: int | None = Field(default=None, gt=0, le=MAX_HORN_ID, strict=True)
    horn_event_id: int | None = Field(default=None, gt=0, le=MAX_HORN_ID, strict=True)

    # 功能：检查或判断 `_validate_enabled_horn` 对应的数据结构逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：'LogisticsChannelAlarmChannel'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`ValueError`、`model_validator`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @model_validator(mode="after")
    def _validate_enabled_horn(self) -> "LogisticsChannelAlarmChannel":
        if self.enabled and (self.horn_id is None or self.horn_event_id is None):
            raise ValueError("启用喇叭告警时必须提供 horn_id 和 horn_event_id")
        return self


# 功能：定义 `LogisticsChannelWechatChannel` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `enabled`（bool）：是否启用相应能力
#   - `user`（str）：当前用户或待处理用户对象
# 返回：LogisticsChannelWechatChannel；返回新建的 `LogisticsChannelWechatChannel` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelWechatChannel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    user: str = ""


# 功能：定义 `LogisticsChannelAlarm` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `sql_enable`（bool）：`sql_enable` 对应的业务输入值
#   - `horn`（LogisticsChannelAlarmChannel）：`horn` 对应的业务输入值
#   - `wechat`（LogisticsChannelWechatChannel）：`wechat` 对应的业务输入值
# 返回：LogisticsChannelAlarm；返回新建的 `LogisticsChannelAlarm` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `test_enabled_horn_requires_positive_device_and_event_ids` 实例化本符号
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelAlarm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql_enable: bool = False
    horn: LogisticsChannelAlarmChannel = Field(default_factory=LogisticsChannelAlarmChannel)
    wechat: LogisticsChannelWechatChannel = Field(default_factory=LogisticsChannelWechatChannel)


# 功能：定义 `LogisticsChannelCreate` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `name`（str）：业务对象名称
# 返回：LogisticsChannelCreate；返回新建的 `LogisticsChannelCreate` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)


# 功能：定义 `LogisticsChannelUpdate` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `name`（str | None）：业务对象名称
#   - `enabled`（bool | None）：是否启用相应能力
#   - `sort_order`（int | None）：`sort_order` 对应的业务输入值
# 返回：LogisticsChannelUpdate；返回新建的 `LogisticsChannelUpdate` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = None


# 功能：定义 `LogisticsChannelConfigUpdate` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `detection_start`（time）：`detection_start` 对应的业务输入值
#   - `detection_end`（time）：`detection_end` 对应的业务输入值
#   - `confidence_threshold`（float）：`confidence_threshold` 对应的业务输入值
#   - `empty_grace_seconds`（float）：`empty_grace_seconds` 对应的时间间隔或时长
#   - `multi_grace_seconds`（float）：`multi_grace_seconds` 对应的时间间隔或时长
#   - `alarm_interval`（float）：`alarm_interval` 对应的时间间隔或时长
#   - `alarm`（LogisticsChannelAlarm）：`alarm` 对应的业务输入值
# 返回：LogisticsChannelConfigUpdate；返回新建的 `LogisticsChannelConfigUpdate` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `test_channel_config_requires_start_before_end`
#         实例化本符号；`AiVision/tests/test_logistics_channel_service.py` 的 `test_channel_config_validates_person_confidence_threshold`
#         实例化本符号；`AiVision/tests/test_logistics_channel_service.py` 的 `test_channel_config_cannot_change_channel_enabled_state`
#         实例化本符号；`AiVision/tests/test_logistics_channel_service.py` 的
#         `test_channel_wechat_config_does_not_accept_backend_credentials` 实例化本符号；另有 1 处静态调用
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detection_start: time = DEFAULT_DETECTION_START
    detection_end: time = DEFAULT_DETECTION_END
    confidence_threshold: float = Field(
        default=DEFAULT_PERSON_CONFIDENCE_THRESHOLD,
        ge=0,
        le=1,
    )
    empty_grace_seconds: float = Field(default=2.0, ge=0)
    multi_grace_seconds: float = Field(default=1.0, ge=0)
    alarm_interval: float = Field(default=5.0, gt=0)
    alarm: LogisticsChannelAlarm = Field(default_factory=LogisticsChannelAlarm)

    # 功能：检查或判断 `_validate_detection_window` 对应的数据结构逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：'LogisticsChannelConfigUpdate'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self.detection_start.utcoffset`、`self.detection_end.utcoffset`、`ValueError`、`model_validator`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @model_validator(mode="after")
    def _validate_detection_window(self) -> "LogisticsChannelConfigUpdate":
        if (
            self.detection_start.tzinfo is not None
            or self.detection_start.utcoffset() is not None
            or self.detection_end.tzinfo is not None
            or self.detection_end.utcoffset() is not None
        ):
            raise ValueError("detection_start 和 detection_end 不支持时区")
        if self.detection_start >= self.detection_end:
            raise ValueError("detection_start 必须早于 detection_end")
        return self


# 功能：定义 `LogisticsChannelMemberCreate` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `camera_id`（int | None）：摄像头唯一标识
#   - `name`（str | None）：业务对象名称
#   - `url`（str | None）：目标接口、媒体流或页面地址
#   - `fps`（int）：`fps` 对应的业务输入值
#   - `department`（str | None）：业务部门名称或标识
#   - `shm_name`（str | None）：摄像头共享内存名称
# 返回：LogisticsChannelMemberCreate；返回新建的 `LogisticsChannelMemberCreate` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `test_member_accepts_existing_camera_id_mode`
#         实例化本符号；`AiVision/tests/test_logistics_channel_service.py` 的
#         `test_member_existing_camera_mode_rejects_explicit_new_camera_fields`
#         实例化本符号；`AiVision/tests/test_logistics_channel_service.py` 的 `test_member_accepts_new_camera_name_url_mode`
#         实例化本符号；`AiVision/tests/test_logistics_channel_service.py` 的 `test_member_requires_exactly_one_camera_input_mode` 实例化本符号；另有
#         1 处静态调用
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    fps: int = Field(default=5, gt=0)
    department: str | None = Field(default=None, max_length=100)
    shm_name: str | None = Field(default=None, min_length=1, max_length=100)

    # 功能：检查或判断 `_validate_camera_input_mode` 对应的数据结构逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：'LogisticsChannelMemberCreate'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`ValueError`、`model_validator`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @model_validator(mode="after")
    def _validate_camera_input_mode(self) -> "LogisticsChannelMemberCreate":
        has_existing_camera = self.camera_id is not None
        has_new_camera = self.name is not None or self.url is not None
        if has_existing_camera == has_new_camera:
            raise ValueError("必须且只能提供 camera_id 或 name 和 url")
        if has_existing_camera:
            new_camera_fields = {"name", "url", "fps", "department", "shm_name"}
            supplied = new_camera_fields & self.model_fields_set
            if supplied:
                raise ValueError("camera_id 模式不得提供新摄像头字段")
        if has_new_camera and (self.name is None or self.url is None):
            raise ValueError("新摄像头必须同时提供 name 和 url")
        return self


# 功能：定义 `LogisticsChannelMemberOrder` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `camera_ids`（list[Annotated[int, Field(gt=0)]]）：`camera_ids` 对应的业务输入值
# 返回：LogisticsChannelMemberOrder；返回新建的 `LogisticsChannelMemberOrder` 实例。
# 调用关系：
#   - 调用方：`AiVision/tests/test_logistics_channel_service.py` 的 `test_member_order_limits_routes_to_nine_positive_unique_ids` 实例化本符号
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelMemberOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_ids: list[Annotated[int, Field(gt=0)]] = Field(
        min_length=1,
        max_length=MAX_CAMERAS_PER_CHANNEL,
    )

    # 功能：检查或判断 `_validate_unique_camera_ids` 对应的数据结构逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：'LogisticsChannelMemberOrder'；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`len`、`set`、`ValueError`、`model_validator`。
    # 副作用/注意事项：校验或执行失败时会主动抛出异常。
    @model_validator(mode="after")
    def _validate_unique_camera_ids(self) -> "LogisticsChannelMemberOrder":
        if len(set(self.camera_ids)) != len(self.camera_ids):
            raise ValueError("camera_ids 不可重复")
        return self


# 功能：启用或停用一个通道成员；成员本身不会被删除；输入与输出详见下方说明
# 参数：
#   - `enabled`（bool）：是否启用相应能力
# 返回：LogisticsChannelMemberEnabledUpdate；返回新建的 `LogisticsChannelMemberEnabledUpdate` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelMemberEnabledUpdate(BaseModel):
    """启用或停用一个通道成员；成员本身不会被删除。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


# 功能：定义 `LogisticsChannelMemberResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `id`（int）：`id` 对应业务对象的唯一标识
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `camera_id`（int）：摄像头唯一标识
#   - `enabled`（bool）：是否启用相应能力
#   - `sort_order`（int）：`sort_order` 对应的业务输入值
#   - `created_at`（datetime | None）：`created_at` 对应的业务输入值
#   - `updated_at`（datetime | None）：`updated_at` 对应的业务输入值
# 返回：LogisticsChannelMemberResponse；返回新建的 `LogisticsChannelMemberResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    camera_id: int
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


# 功能：定义 `LogisticsChannelConfigResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `detection_start`（time）：`detection_start` 对应的业务输入值
#   - `detection_end`（time）：`detection_end` 对应的业务输入值
#   - `confidence_threshold`（float）：`confidence_threshold` 对应的业务输入值
#   - `empty_grace_seconds`（float）：`empty_grace_seconds` 对应的时间间隔或时长
#   - `multi_grace_seconds`（float）：`multi_grace_seconds` 对应的时间间隔或时长
#   - `alarm_interval`（float）：`alarm_interval` 对应的时间间隔或时长
#   - `alarm`（LogisticsChannelAlarm）：`alarm` 对应的业务输入值
# 返回：LogisticsChannelConfigResponse；返回新建的 `LogisticsChannelConfigResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    detection_start: time
    detection_end: time
    confidence_threshold: float
    empty_grace_seconds: float
    multi_grace_seconds: float
    alarm_interval: float
    alarm: LogisticsChannelAlarm

    # 功能：实现 `_adapt_channel_orm` 对应的数据结构逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `value`（Any）：待转换、校验或写入的值
    # 返回：Any；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`isinstance`、`hasattr`、`model_validator`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @model_validator(mode="before")
    @classmethod
    def _adapt_channel_orm(cls, value: Any) -> Any:
        if isinstance(value, dict) or not hasattr(value, "detection_start"):
            return value
        return {
            "detection_start": value.detection_start,
            "detection_end": value.detection_end,
            "confidence_threshold": value.confidence_threshold,
            "empty_grace_seconds": value.empty_grace_seconds,
            "multi_grace_seconds": value.multi_grace_seconds,
            "alarm_interval": value.alarm_interval,
            "alarm": {
                "sql_enable": value.sql_enable,
                "horn": {
                    "enabled": value.horn_enable,
                    "horn_id": value.horn_id,
                    "horn_event_id": value.horn_event_id,
                },
                "wechat": {
                    "enabled": value.wechat_enable,
                    "user": value.wechat_user or "",
                },
            },
        }


# 功能：运行时状态响应；调用方传入已组装的 dict，不接受 ORM 对象；输入与输出详见下方说明
# 参数：
#   - `reason`（LogisticsChannelStatusReason）：`reason` 对应的业务输入值
#   - `online`（bool | None）：`online` 对应的业务输入值
#   - `person_count`（int | None）：`person_count` 对应的数量或大小
#   - `stale`（bool）：`stale` 对应的业务输入值
#   - `stale_reason`（str | None）：`stale_reason` 对应的业务输入值
#   - `duration_seconds`（float | None）：`duration_seconds` 对应的时间间隔或时长
#   - `updated_at`（datetime | None）：`updated_at` 对应的业务输入值
# 返回：LogisticsChannelStatusResponse；返回新建的 `LogisticsChannelStatusResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelStatusResponse(BaseModel):
    """运行时状态响应；调用方传入已组装的 dict，不接受 ORM 对象。"""
    reason: LogisticsChannelStatusReason
    online: bool | None = None
    person_count: int | None = None
    stale: bool = False
    stale_reason: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    updated_at: datetime | None = None


# 功能：定义 `LogisticsChannelResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `id`（int）：`id` 对应业务对象的唯一标识
#   - `name`（str）：业务对象名称
#   - `feature_name`（LogisticsFeatureName）：`feature_name` 对应的业务输入值
#   - `enabled`（bool）：是否启用相应能力
#   - `sort_order`（int）：`sort_order` 对应的业务输入值
#   - `created_at`（datetime | None）：`created_at` 对应的业务输入值
#   - `updated_at`（datetime | None）：`updated_at` 对应的业务输入值
# 返回：LogisticsChannelResponse；返回新建的 `LogisticsChannelResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    feature_name: LogisticsFeatureName
    enabled: bool
    sort_order: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


# 功能：定义 `LogisticsChannelListResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `items`（list[LogisticsChannelResponse]）：`items` 对应的业务输入值
# 返回：LogisticsChannelListResponse；返回新建的 `LogisticsChannelListResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelListResponse(BaseModel):
    items: list[LogisticsChannelResponse]


# 功能：描述摄像头与一个物流通道的成员关系及当前在线状态；输入与输出详见下方说明
# 参数：
#   - `feature_name`（LogisticsFeatureName）：物流检测功能标识
#   - `channel_id`（int）：物流通道唯一标识
#   - `channel_name`（str）：物流通道名称
#   - `enabled`（bool）：通道和成员是否均已启用
#   - `online`（bool）：该摄像头在此通道的最新运行状态是否在线
# 返回：LogisticsCameraInventoryMembership；返回结构化的物流摄像头成员关系。
# 调用关系：
#   - 调用方：`api/logistics_channels.py` 的 `list_logistics_camera_inventory` 构造本模型；前端首页读取其序列化结果
#   - 内部调用：不调用其他项目函数，仅进行字段声明与 Pydantic 校验。
# 副作用/注意事项：无外部副作用；不包含摄像头连接地址等敏感字段。
class LogisticsCameraInventoryMembership(BaseModel):
    feature_name: LogisticsFeatureName
    channel_id: int
    channel_name: str
    enabled: bool
    online: bool


# 功能：描述平台汇总所需的一路物流摄像头安全清单；输入与输出详见下方说明
# 参数：
#   - `camera_id`（int）：摄像头唯一标识
#   - `name`（str）：摄像头名称
#   - `shm_name`（str）：摄像头共享内存标识
#   - `department`（str | None）：摄像头事业部归属
#   - `enabled`（bool）：摄像头主配置是否启用
#   - `online`（bool）：任一授权物流通道中的最新在线状态
#   - `memberships`（list[LogisticsCameraInventoryMembership]）：授权范围内的物流通道成员关系
# 返回：LogisticsCameraInventoryItem；返回不含 RTSP 地址的物流摄像头清单项。
# 调用关系：
#   - 调用方：`api/logistics_channels.py` 的 `list_logistics_camera_inventory` 构造本模型；前端首页消费其字段
#   - 内部调用：`Field`。
# 副作用/注意事项：无外部副作用；同一物理摄像头可包含多个通道成员关系。
class LogisticsCameraInventoryItem(BaseModel):
    camera_id: int
    name: str
    shm_name: str
    department: str | None = None
    enabled: bool
    online: bool
    memberships: list[LogisticsCameraInventoryMembership] = Field(default_factory=list)


# 功能：封装当前用户有权查看的物流摄像头清单；输入与输出详见下方说明
# 参数：
#   - `items`（list[LogisticsCameraInventoryItem]）：按物理摄像头去重后的安全清单
# 返回：LogisticsCameraInventoryResponse；作为 `/api/logistics-channels/inventory` 的响应体。
# 调用关系：
#   - 调用方：`api/logistics_channels.py` 的 `list_logistics_camera_inventory` 返回本模型
#   - 内部调用：`Field`。
# 副作用/注意事项：无外部副作用；响应不包含 URL、账号或密码。
class LogisticsCameraInventoryResponse(BaseModel):
    items: list[LogisticsCameraInventoryItem] = Field(default_factory=list)


# 功能：定义 `LogisticsChannelDetailResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `config`（LogisticsChannelConfigResponse）：运行配置对象
#   - `members`（list[LogisticsChannelMemberResponse]）：`members` 对应的业务输入值
#   - `status`（LogisticsChannelStatusResponse | None）：当前或目标状态值
# 返回：LogisticsChannelDetailResponse；返回新建的 `LogisticsChannelDetailResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelDetailResponse(LogisticsChannelResponse):
    config: LogisticsChannelConfigResponse
    members: list[LogisticsChannelMemberResponse] = Field(default_factory=list)
    status: LogisticsChannelStatusResponse | None = None

    # 功能：实现 `_adapt_channel_orm` 对应的数据结构逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `cls`（未显式标注）：当前类对象
    #   - `value`（Any）：待转换、校验或写入的值
    # 返回：Any；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`isinstance`、`hasattr`、`getattr`、`model_validator`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @model_validator(mode="before")
    @classmethod
    def _adapt_channel_orm(cls, value: Any) -> Any:
        if isinstance(value, dict) or not hasattr(value, "feature_name"):
            return value
        return {
            "id": value.id,
            "name": value.name,
            "feature_name": value.feature_name,
            "enabled": value.enabled,
            "sort_order": value.sort_order,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "config": value,
            "members": value.cameras,
            "status": getattr(value, "status", None),
        }


# 功能：通道状态中单路摄像头的最新运行时快照；输入与输出详见下方说明
# 参数：
#   - `camera_id`（int）：摄像头唯一标识
#   - `camera_name`（str）：`camera_name` 对应的业务输入值
#   - `count`（int | None）：`count` 对应的数量或大小
#   - `status`（LogisticsChannelStatusReason）：当前或目标状态值
#   - `online`（bool）：`online` 对应的业务输入值
#   - `updated_at`（float | None）：`updated_at` 对应的业务输入值
#   - `stale_reason`（str | None）：`stale_reason` 对应的业务输入值
# 返回：LogisticsChannelCameraRuntimeStatus；返回新建的 `LogisticsChannelCameraRuntimeStatus` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelCameraRuntimeStatus(BaseModel):
    """通道状态中单路摄像头的最新运行时快照。"""

    model_config = ConfigDict(extra="forbid")

    camera_id: int
    camera_name: str
    count: int | None = Field(default=None, ge=0)
    status: LogisticsChannelStatusReason
    online: bool
    updated_at: float | None = None
    stale_reason: str | None = None


# 功能：通道聚合运行状态；时间戳沿用运行时 Unix 秒格式；输入与输出详见下方说明
# 参数：
#   - `feature_name`（LogisticsFeatureName）：`feature_name` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `channel_name`（str）：`channel_name` 对应的业务输入值
#   - `reason`（LogisticsChannelStatusReason）：`reason` 对应的业务输入值
#   - `alarm`（bool）：`alarm` 对应的业务输入值
#   - `duration_seconds`（float | None）：`duration_seconds` 对应的时间间隔或时长
#   - `threshold_seconds`（float | None）：`threshold_seconds` 对应的时间间隔或时长
#   - `camera_ids`（list[int]）：`camera_ids` 对应的业务输入值
#   - `camera_counts`（dict[str, int | None]）：`camera_counts` 对应的业务输入值
#   - `camera_states`（dict[str, LogisticsChannelCameraRuntimeStatus]）：`camera_states` 对应的业务输入值
#   - `offending_camera_ids`（list[int]）：`offending_camera_ids` 对应的业务输入值
#   - `updated_at`（float | None）：`updated_at` 对应的业务输入值
# 返回：LogisticsChannelRuntimeStatusResponse；返回新建的 `LogisticsChannelRuntimeStatusResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelRuntimeStatusResponse(BaseModel):
    """通道聚合运行状态；时间戳沿用运行时 Unix 秒格式。"""

    model_config = ConfigDict(extra="forbid")

    feature_name: LogisticsFeatureName
    channel_id: int
    channel_name: str
    reason: LogisticsChannelStatusReason
    alarm: bool
    duration_seconds: float | None = Field(default=None, ge=0)
    threshold_seconds: float | None = Field(default=None, ge=0)
    camera_ids: list[int] = Field(default_factory=list)
    camera_counts: dict[str, int | None] = Field(default_factory=dict)
    camera_states: dict[str, LogisticsChannelCameraRuntimeStatus] = Field(default_factory=dict)
    offending_camera_ids: list[int] = Field(default_factory=list)
    updated_at: float | None = None


# 功能：定义 `LogisticsChannelAlarmResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `id`（str）：`id` 对应业务对象的唯一标识
#   - `feature_name`（LogisticsFeatureName | None）：`feature_name` 对应的业务输入值
#   - `channel_id`（int）：`channel_id` 对应业务对象的唯一标识
#   - `channel_name`（str | None）：`channel_name` 对应的业务输入值
#   - `reason`（str | None）：`reason` 对应的业务输入值
#   - `created_at`（str | None）：`created_at` 对应的业务输入值
#   - `image_url`（str）：`image_url` 对应的业务输入值
#   - `metadata`（dict[str, Any]）：`metadata` 对应的业务输入值
# 返回：LogisticsChannelAlarmResponse；返回新建的 `LogisticsChannelAlarmResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelAlarmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    feature_name: LogisticsFeatureName | None = None
    channel_id: int
    channel_name: str | None = None
    reason: str | None = None
    created_at: str | None = None
    image_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# 功能：定义 `LogisticsChannelAlarmListResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `items`（list[LogisticsChannelAlarmResponse]）：`items` 对应的业务输入值
# 返回：LogisticsChannelAlarmListResponse；返回新建的 `LogisticsChannelAlarmListResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelAlarmListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LogisticsChannelAlarmResponse] = Field(default_factory=list)


# 功能：定义 `LogisticsChannelStatisticsSummary` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `total`（int）：`total` 对应的业务输入值
#   - `today`（int）：`today` 对应的业务输入值
# 返回：LogisticsChannelStatisticsSummary；返回新建的 `LogisticsChannelStatisticsSummary` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelStatisticsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    today: int = Field(ge=0)


# 功能：定义 `LogisticsChannelDailyStatistic` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `day`（str）：`day` 对应的业务输入值
#   - `count`（int）：`count` 对应的数量或大小
# 返回：LogisticsChannelDailyStatistic；返回新建的 `LogisticsChannelDailyStatistic` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelDailyStatistic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str
    count: int = Field(ge=0)


# 功能：定义 `LogisticsChannelStatisticsResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `summary`（LogisticsChannelStatisticsSummary）：`summary` 对应的业务输入值
#   - `daily`（list[LogisticsChannelDailyStatistic]）：`daily` 对应的业务输入值
# 返回：LogisticsChannelStatisticsResponse；返回新建的 `LogisticsChannelStatisticsResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`、`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelStatisticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: LogisticsChannelStatisticsSummary
    daily: list[LogisticsChannelDailyStatistic] = Field(default_factory=list)


# 功能：定义 `LogisticsChannelOkResponse` 类，封装数据结构相关的状态、约束与操作
# 参数：
#   - `ok`（bool）：`ok` 对应的业务输入值
# 返回：LogisticsChannelOkResponse；返回新建的 `LogisticsChannelOkResponse` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`ConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class LogisticsChannelOkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
