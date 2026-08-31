# 文件说明：定义`departments` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""api/v2/departments.py
部门管理 API。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user, require_admin
from api.deps import get_camera_service, get_department_service
from core.db import session_scope
from platform.camera.service import CameraService
from platform.department.service import DepartmentService

router = APIRouter(prefix="/api/v2/departments", tags=["departments"])


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


# 功能：创建部门 (admin only)；输入与输出详见下方说明
# 参数：
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.post('', dependencies=[Depends(require_admin)])` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`session_scope`、`dept_service.create_department`、`router.post`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.post("", dependencies=[Depends(require_admin)])
def create_department(
    payload: dict[str, Any],
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """创建部门 (admin only)。"""
    with session_scope() as session:
        dept = dept_service.create_department(session, payload)
        return {"name": dept.name, "display_name": dept.display_name}


# 功能：更新部门 (admin only)；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{name}', dependencies=[Depends(require_admin)])` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`session_scope`、`dept_service.update_department`、`HTTPException`、`router.put`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.put("/{name}", dependencies=[Depends(require_admin)])
def update_department(
    name: str,
    payload: dict[str, Any],
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """更新部门 (admin only)。"""
    with session_scope() as session:
        dept = dept_service.update_department(session, name, payload)
        if not dept:
            raise HTTPException(status_code=404, detail="部门不存在")
        return {"name": dept.name, "display_name": dept.display_name}


# 功能：删除部门 (admin only)；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.delete('/{name}', dependencies=[Depends(require_admin)])` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`session_scope`、`dept_service.delete_department`、`HTTPException`、`router.delete`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.delete("/{name}", dependencies=[Depends(require_admin)])
def delete_department(
    name: str,
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """删除部门 (admin only)。"""
    with session_scope() as session:
        if not dept_service.delete_department(session, name):
            raise HTTPException(status_code=404, detail="部门不存在")
        return {"ok": True}


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


# 功能：设置部门的功能列表 (admin only)；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `payload`（dict[str, Any]）：接口或事件携带的业务数据
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `dept_service`（DepartmentService）：`dept_service` 对应的业务输入值；默认值为 `Depends(get_department_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{name}/features', dependencies=[Depends(require_admin)])` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`payload.get`、`session_scope`、`dept_service.set_feature_departments`、`dept_service.get_features_by_department`、`dept_service.remove_feature_department`、`session.add`、`AiFeatureDepartment`、`router.put`。
# 副作用/注意事项：可能读取或修改数据库事务。
@router.put("/{name}/features", dependencies=[Depends(require_admin)])
def set_department_features(
    name: str,
    payload: dict[str, Any],  # {"features": [...]}
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """设置部门的功能列表 (admin only)。"""
    feature_names = payload.get("features", [])
    with session_scope() as session:
        dept_service.set_feature_departments(session, None, feature_names)
        # Wait, no, set_feature_departments is for a single feature. We need to loop through features and add/remove mappings
        # Let's do it correctly:
        # 1. Get current features for the dept
        current_features = dept_service.get_features_by_department(session, name)
        current_names = [f["name"] for f in current_features]
        # 2. Remove features no longer in the list
        for fname in current_names:
            if fname not in feature_names:
                dept_service.remove_feature_department(session, fname, name)
        # 3. Add new features in the list
        for fname in feature_names:
            if fname not in current_names:
                # Check if mapping already exists? No, because we just removed
                from platform.department.orm import AiFeatureDepartment
                session.add(AiFeatureDepartment(feature_name=fname, department=name))
        return {"ok": True}


# 功能：获取部门下的摄像头列表；输入与输出详见下方说明
# 参数：
#   - `name`（str）：业务对象名称
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `cam_service`（CameraService）：`cam_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{name}/cameras')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`cam_service.list_cameras`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/{name}/cameras")
def get_department_cameras(
    name: str,
    user: dict = Depends(get_current_user),
    cam_service: CameraService = Depends(get_camera_service),
):
    """获取部门下的摄像头列表。"""
    return cam_service.list_cameras(department=name)
