"""新告警正式字段的写入校验；只校验调用方给出的值，不推导缺失字段。"""
from AiVision.departments.department_registry import require_department
from .types import VIOLATION_TYPE_META


def _validate_alarm_type(violation_type: int) -> None:
    """要求告警类型是正式注册整数，拒绝布尔值和未知编号。"""
    if type(violation_type) is not int or violation_type not in VIOLATION_TYPE_META:
        raise ValueError("新告警 violation_type 必须是正式报警类型注册表中的整数")


def validate_cooldown_identity(cooldown_subject_type: str, cooldown_subject_id: str, violation_type: int) -> None:
    """冷却身份由调用方明确提供，与持久化业务主体独立。"""
    _validate_alarm_type(violation_type)
    for name, value in (("cooldown_subject_type", cooldown_subject_type), ("cooldown_subject_id", cooldown_subject_id)):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"{name} 必须是明确、非空且无首尾空白的字符串")


def validate_alarm_identity(violation_type: int, feature_name: str, department: str) -> None:
    """要求调用方明确给出功能及事业部，并核对告警类型属于该功能声明。"""
    _validate_alarm_type(violation_type)
    if not isinstance(feature_name, str) or not feature_name.strip() or feature_name != feature_name.strip():
        raise ValueError("新告警必须明确提供 feature_name")
    if not isinstance(department, str) or not department.strip() or department != department.strip():
        raise ValueError("新告警必须明确提供 department")
    require_department(department)
    # Feature 发现过程中会导入告警模块；实际创建告警时注册表已就绪。
    from AiVision.features.registry import get_spec

    spec = get_spec(feature_name)
    if spec is None:
        raise ValueError(f"新告警 feature_name 未注册: {feature_name}")
    if violation_type not in spec.alarm_types:
        raise ValueError(f"告警类型与 FeatureSpec 不一致: {feature_name}")
