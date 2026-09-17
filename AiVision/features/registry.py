"""内置功能的唯一注册入口；包路径与持久化业务标识分离。"""
from AiVision.alarms.types import VIOLATION_TYPE_META

from ._shared.spec import FeatureSpec
from .intrusion.spec import SPEC as intrusion_spec
from .door_state.spec import SPEC as door_state_spec
from .face_dwell.spec import SPEC as face_dwell_spec
from .person_dwell.spec import SPEC as person_dwell_spec
from .logistics_channel.spec import SPEC as logistics_channel_spec
from .phone_detection.spec import SPEC as phone_detection_spec
from .face_recognition.spec import SPEC as face_recognition_spec
from .guard_behavior.spec import SPEC as guard_behavior_spec

# 保持原注册表的展示/遍历顺序；新增功能须在这里明确登记。
_BUILTIN_SPECS = (
    intrusion_spec,
    door_state_spec,
    face_dwell_spec,
    person_dwell_spec,
    logistics_channel_spec,
    phone_detection_spec,
    face_recognition_spec,
    guard_behavior_spec,
)


def _build_registry(specs: tuple[FeatureSpec, ...]) -> dict[str, FeatureSpec]:
    registry = {}
    alarm_owners: dict[int, str] = {}
    for spec in specs:
        if spec.name in registry:
            raise ValueError(f"重复的 FeatureSpec.name: {spec.name!r}")
        if not isinstance(spec.alarm_types, tuple):
            raise ValueError(f"FeatureSpec.alarm_types 必须是 tuple: {spec.name!r}")
        seen: set[int] = set()
        for alarm_type in spec.alarm_types:
            if type(alarm_type) is not int or alarm_type <= 0:
                raise ValueError(f"FeatureSpec.alarm_types 必须是正整数，且不允许 bool: {spec.name!r}")
            if alarm_type in seen:
                raise ValueError(f"FeatureSpec.alarm_types 内有重复报警类型: {spec.name!r}, {alarm_type}")
            if alarm_type not in VIOLATION_TYPE_META:
                raise ValueError(f"FeatureSpec.alarm_types 包含未注册报警类型: {spec.name!r}, {alarm_type}")
            if alarm_type in alarm_owners:
                raise ValueError(f"报警类型 {alarm_type} 已归属 Feature {alarm_owners[alarm_type]!r}，不能重复归属 {spec.name!r}")
            seen.add(alarm_type)
            alarm_owners[alarm_type] = spec.name
        registry[spec.name] = spec
    return registry


# Python 模块导入完成前不会向其他导入线程提供半初始化的注册表。
# 任一 SPEC 导入或校验失败直接传播，不跳过功能，也不保留部分注册结果。
_REGISTRY = _build_registry(_BUILTIN_SPECS)


def all_specs() -> dict[str, FeatureSpec]:
    """返回所有已注册功能的副本。"""
    return dict(_REGISTRY)


def get_spec(name: str) -> FeatureSpec | None:
    return _REGISTRY.get(name)


def list_orm_classes() -> list[type]:
    """返回内置功能的配置 ORM 类。"""
    return [spec.orm_class for spec in _REGISTRY.values()]
