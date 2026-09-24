"""事业部功能权限统一判断，所有角色均遵守功能分配。"""

from fastapi import HTTPException

from AiVision.departments.department_registry import DEPARTMENT_SPECS


def feature_departments(user: dict, feature: str) -> list[str]:
    """按事业部与功能的配对授权，避免多事业部账号串用权限。"""
    if user["role"] == "admin":
        departments = DEPARTMENT_SPECS
    elif user["role"] == "viewer":
        departments = user["departments"]
    else:
        return []
    return [department for department in departments
            if feature in user["feature_access"].get(department, [])]


def require_feature_access(user: dict, feature: str, department: str | None = None) -> None:
    """无指定事业部时检查功能入口；有事业部时校验精确资源归属。"""
    departments = feature_departments(user, feature)
    if (department is None and not departments) or (department is not None and department not in departments):
        raise HTTPException(403, "当前事业部未分配此功能或账号无权访问")
