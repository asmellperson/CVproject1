"""api/v2/departments.py
部门管理 API。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user, require_admin
from api.deps import get_camera_service, get_department_service
from core.db import session_scope
from platform.camera.service import CameraService
from platform.department.service import DepartmentService

router = APIRouter(prefix="/api/v2/departments", tags=["departments"])


@router.get("")
def list_departments(
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """列出所有部门。"""
    with session_scope() as session:
        depts = dept_service.list_departments(session)
        return [{"name": d.name, "display_name": d.display_name} for d in depts]


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


@router.get("/{name}/features")
def get_department_features(
    name: str,
    user: dict = Depends(get_current_user),
    dept_service: DepartmentService = Depends(get_department_service),
):
    """获取部门下的功能列表。"""
    with session_scope() as session:
        return dept_service.get_features_by_department(session, name)


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


@router.get("/{name}/cameras")
def get_department_cameras(
    name: str,
    user: dict = Depends(get_current_user),
    cam_service: CameraService = Depends(get_camera_service),
):
    """获取部门下的摄像头列表。"""
    return cam_service.list_cameras(department=name)
