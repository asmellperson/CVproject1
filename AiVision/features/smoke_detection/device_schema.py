"""摄像头真实参数与烟雾屏蔽区域的公开契约，不包含设备凭据。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DeviceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SmokeParameterChoice(DeviceModel):
    value: str
    label: str


class SmokeParameter(DeviceModel):
    key: str
    label: str
    kind: Literal["boolean", "integer", "enum"]
    value: bool | int | str
    minimum: int | None = None
    maximum: int | None = None
    choices: list[SmokeParameterChoice] = Field(default_factory=list)


class SmokeParametersState(DeviceModel):
    supported: bool
    message: str = ""
    channel_id: int
    global_enabled: bool | None = None
    parameters: list[SmokeParameter] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SmokeParametersUpdate(DeviceModel):
    values: dict[str, bool | int | str] = Field(min_length=1, max_length=10)


class SmokeShieldPoint(DeviceModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class SmokeShieldRegion(DeviceModel):
    id: int = Field(gt=0)
    enabled: bool = True
    name: str = Field(default="", max_length=32)
    points: list[SmokeShieldPoint] = Field(min_length=3, max_length=10)

    @model_validator(mode="after")
    def validate_polygon(self):
        """拒绝重复点、零面积和自交区域，避免设备拒绝或屏蔽范围歧义。"""
        pairs = [(p.x, p.y) for p in self.points]
        if len(set(pairs)) != len(pairs):
            raise ValueError("屏蔽区域不能包含重复坐标")
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pairs, pairs[1:] + pairs[:1]))
        if abs(area) < 1e-9:
            raise ValueError("屏蔽区域必须具有有效面积")

        def cross(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        def on_segment(a, b, c):
            return (abs(cross(a, b, c)) < 1e-9
                    and min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
                    and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))

        count = len(pairs)
        for i in range(count):
            a, b = pairs[i], pairs[(i + 1) % count]
            for j in range(i + 1, count):
                if j == i + 1 or (i == 0 and j == count - 1):
                    continue
                c, d = pairs[j], pairs[(j + 1) % count]
                if (cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0
                        or on_segment(a, b, c) or on_segment(a, b, d)
                        or on_segment(c, d, a) or on_segment(c, d, b)):
                    raise ValueError("屏蔽区域不能自交")
        return self


class SmokeShieldState(DeviceModel):
    supported: bool
    writable: bool = False
    message: str = ""
    enabled: bool = False
    channel_id: int
    coordinate_width: int | None = None
    coordinate_height: int | None = None
    max_regions: int = 0
    min_points: int = 3
    max_points: int = 10
    regions: list[SmokeShieldRegion] = Field(default_factory=list)


class SmokeShieldUpdate(DeviceModel):
    enabled: bool
    regions: list[SmokeShieldRegion] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def unique_regions(self):
        if len({region.id for region in self.regions}) != len(self.regions):
            raise ValueError("屏蔽区域编号不能重复")
        return self
