"""离线迁移中显式批准的逐行赋值；不推断旧值含义或补齐非法数据。"""


def check_row_ids(changes, row_ids):
    """要求赋值计划只引用实际存在的配置行，避免拼错 ID 后静默漏改。"""
    if not isinstance(changes, dict) or set(changes) - {str(value) for value in row_ids}:
        raise ValueError("赋值计划必须按存在的配置行 ID 指定")


def apply_row_changes(row, changes, *, allowed_fields):
    """在源值符合 expected 且字段明确获准时返回应用赋值后的副本。

    每个新值都必须有对应旧值前置条件；任何源值偏差立即停止迁移。
    """
    result = dict(row)
    if str(row["id"]) not in changes:
        return result
    assignment = changes[str(row["id"])]
    if not isinstance(assignment, dict) or set(assignment) != {"expected", "values"}:
        raise ValueError("逐行赋值必须包含 expected 和 values")
    expected, values = assignment["expected"], assignment["values"]
    if (not isinstance(expected, dict) or not isinstance(values, dict) or not values
            or set(values) - allowed_fields or set(expected) - (allowed_fields | {"enable"})
            or set(values) - set(expected)):
        raise ValueError("赋值字段未授权，或缺少对应原值前置检查")
    if any(row.get(field) != value for field, value in expected.items()):
        raise ValueError(f"id={row['id']}: 赋值计划的前置值不一致，停止")
    result.update(values)
    return result
