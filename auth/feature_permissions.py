"""事业部功能权限统一判断，所有角色均遵守功能分配。"""

from fastapi import HTTPException

from AiVision.departments.department_registry import DEPARTMENT_SPECS


def accessible_departments(user: dict) -> list[str]:
    """角色和明确部门授权共同决定范围，未知角色与 all 均不能获得部门权限。"""
    if user.get("role") == "admin":
        return list(DEPARTMENT_SPECS)
    if user.get("role") not in {"viewer", "department_admin"}:
        return []
    return list(dict.fromkeys(value for value in user.get("departments", [])
                              if isinstance(value, str) and value in DEPARTMENT_SPECS))


def require_department_write_access(user: dict, department: str | None) -> None:
    """部门管理员不能操作未归属资源或通过请求中的部门扩大授权。"""
    if user.get("role") == "admin":
        return
    if user.get("role") != "department_admin" or department not in accessible_departments(user):
        raise HTTPException(403, "无权修改当前事业部配置")


def feature_departments(user: dict, feature: str) -> list[str]:
    """按事业部与功能的配对授权，避免多事业部账号串用权限。"""
    departments = accessible_departments(user)
    return [department for department in departments
            if feature in user["feature_access"].get(department, [])]


def require_feature_access(user: dict, feature: str, department: str | None = None) -> None:
    """无指定事业部时检查功能入口；有事业部时校验精确资源归属。"""
    departments = feature_departments(user, feature)
    if (department is None and not departments) or (department is not None and department not in departments):
        raise HTTPException(403, "当前事业部未分配此功能或账号无权访问")
