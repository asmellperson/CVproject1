"""新告警正式字段的写入校验；只校验调用方给出的值，不推导缺失字段。"""
from AiVision.departments.department_registry import require_department
from .types import VIOLATION_TYPE_META


def validate_alarm_identity(violation_type: int, feature_name: str, department: str) -> None:
    if type(violation_type) is not int or violation_type not in VIOLATION_TYPE_META:
        raise ValueError("新告警 violation_type 必须是正式报警类型注册表中的整数")
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
    if violation_type != spec.violation_type:
        raise ValueError(f"告警类型与 FeatureSpec 不一致: {feature_name}")
