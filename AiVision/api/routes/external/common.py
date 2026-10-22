"""外部展示接口共享的安全响应和资源归属校验。"""
from fastapi import HTTPException
from pydantic import BaseModel

from AiVision.departments.department_registry import require_department


class DepartmentResponse(BaseModel):
    name: str
    display_name: str


class CameraResponse(BaseModel):
    id: str
    camera_id: int
    name: str
    shm_name: str
    department: str
    enabled: bool
    fps: float | None = None
    sort_order: int
    feature_sort_orders: dict[str, int]
    functions: dict[str, bool]


def require_feature_department(department, feature, service):
    try:
        require_department(department)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if feature not in service.feature_access().get(department, []):
        raise HTTPException(403, "此事业部未分配对应功能")
    return department


def scoped_camera(manager, shm_name, department):
    camera = manager.get_camera(shm_name)
    if camera is None or camera["shm_name"] != shm_name:
        raise HTTPException(404, "camera not found")
    if camera["department"] != department:
        raise HTTPException(403, "摄像头不属于所选事业部")
    return camera
