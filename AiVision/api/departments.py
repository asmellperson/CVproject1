# 文件说明：定义`departments` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""api/departments.py
部门管理 API。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.deps import get_department_service
from core.db import session_scope
from platform.department.service import DepartmentService

router = APIRouter(prefix="/api/departments", tags=["departments"])


# 功能：列出所有部门；输入与输出详见下方说明
# 参数：
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`session_scope`、`dept_service.list_departments`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("")
def list_departments(
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """列出所有部门。"""
    with session_scope() as session:
        depts = dept_service.list_departments(session)
        return [{"name": d.name, "display_name": d.display_name} for d in depts]


# 功能：获取部门下的功能列表；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{name}/features')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`session_scope`、`dept_service.get_features_by_department`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/{name}/features")
def get_department_features(
    name: str,
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """获取部门下的功能列表。"""
    with session_scope() as session:
        return dept_service.get_features_by_department(session, name)
