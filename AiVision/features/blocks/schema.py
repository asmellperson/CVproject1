"""features/blocks/schema.py — 区域入侵检测前端入参校验"""
from typing import List
from pydantic import BaseModel, Field, field_validator


class BlocksValueSchema(BaseModel):
    roi_pos: List[List[List[int]]] = Field(default_factory=list)
    threshold: float = Field(0.1, ge=0)
    blur_kernel: int = Field(5, ge=1)
    diff_threshold: int = Field(10, ge=0)
    diff_threshold_env: int = Field(10, ge=0)
    env_threshold: float = Field(0.5, ge=0)
    cap_interval: float = Field(0.1, gt=0)
    alarm_interval: float = Field(5.0, gt=0)

    @field_validator("roi_pos", mode="before")
    @classmethod
    def _normalize_roi(cls, v):
        # 兼容: 单 polygon list[list[int]] → list[list[list[int]]]
        if not isinstance(v, list) or not v:
            return v
        first = v[0]
        if isinstance(first, list) and first and not isinstance(first[0], list):
            return [v]
        return v


class _AlarmChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=dict)


class _WechatChannel(BaseModel):
    enable: bool = False
    parm: dict = Field(default_factory=lambda: {"user": ""})


class BlocksAlarmSchema(BaseModel):
    sql: _AlarmChannel = Field(default_factory=_AlarmChannel)
    horn: _AlarmChannel = Field(default_factory=_AlarmChannel)
    wechat: _WechatChannel = Field(default_factory=_WechatChannel)


class BlocksConfigSchema(BaseModel):
    """blocks 完整配置 — 前端 PUT 时的请求体格式"""
    enable: bool = False
    value: BlocksValueSchema = Field(default_factory=BlocksValueSchema)
    alarm: BlocksAlarmSchema = Field(default_factory=BlocksAlarmSchema)
