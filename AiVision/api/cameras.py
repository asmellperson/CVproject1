# 文件说明：定义`cameras` 模块的 HTTP 接口、依赖注入或应用装配。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
api/cameras.py
摄像头 CRUD + 当前帧 JPEG 输出。
"""
from __future__ import annotations

import threading
import time
from typing import Any

import cv2
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from api.auth import get_current_user, require_admin
from api.deps import get_camera_service, get_current_orchestrator
from core.logger import logger
from core.settings import settings
from platform.camera.service import camera_access_departments


router = APIRouter(prefix="/api/cameras", tags=["cameras"])

_JPEG_CACHE_MAX_ITEMS = 128
_jpeg_cache_lock = threading.Lock()
_jpeg_cache: dict[tuple[Any, ...], bytes] = {}
_jpeg_cache_order: list[tuple[Any, ...]] = []


# 功能：提取当前用户可访问的全部事业部；输入用户字典，输出去重后的事业部标识列表。
# 参数：
#   - `user`（dict）：当前用户对象，兼容多事业部 `departments` 与旧版单事业部 `department` 字段
# 返回：list[str]；返回用户可访问的事业部标识，保持原始授权顺序并去除空值与重复值。
# 调用关系：
#   - 调用方：`camera_read_department`、`camera_list_response_for_user`、`get_camera_for_user` 调用本符号以统一摄像头读取权限
#   - 内部调用：`user.get`、`isinstance`、`str`、`strip`、`append`。
# 副作用/注意事项：不修改用户对象；缺少有效事业部时返回空列表。
def _camera_departments_for_user(user: dict) -> list[str]:
    raw_departments = user.get("departments")
    candidates = (
        raw_departments
        if isinstance(raw_departments, list) and raw_departments
        else [user.get("department")]
    )
    departments: list[str] = []
    for candidate in candidates:
        department = str(candidate or "").strip()
        if department and department not in departments:
            departments.append(department)
    return departments


# 功能：定义 `CameraCreateRequest` 类，封装`cameras` 模块相关的状态、约束与操作
# 参数：
#   - `name`（str）：业务对象名称
#   - `url`（str）：目标接口、媒体流或页面地址
#   - `shm_name`（str）：摄像头共享内存名称
#   - `fps`（int）：`fps` 对应的业务输入值
#   - `max_restart`（int）：`max_restart` 对应的业务输入值
#   - `enable`（bool | None）：`enable` 对应的业务输入值
#   - `enabled`（bool | None）：是否启用相应能力
#   - `department`（str | None）：业务部门名称或标识
# 返回：CameraCreateRequest；返回新建的 `CameraCreateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    shm_name: str = Field(..., min_length=1)
    fps: int = Field(5, gt=0)
    max_restart: int = Field(10, ge=0)
    enable: bool | None = None
    enabled: bool | None = None
    department: str | None = None


# 功能：定义 `CameraUpdateRequest` 类，封装`cameras` 模块相关的状态、约束与操作
# 参数：
#   - `name`（str | None）：业务对象名称
#   - `url`（str | None）：目标接口、媒体流或页面地址
#   - `fps`（int | None）：`fps` 对应的业务输入值
#   - `max_restart`（int | None）：`max_restart` 对应的业务输入值
#   - `enable`（bool | None）：`enable` 对应的业务输入值
#   - `enabled`（bool | None）：是否启用相应能力
#   - `department`（str | None）：业务部门名称或标识
# 返回：CameraUpdateRequest；返回新建的 `CameraUpdateRequest` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Field`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class CameraUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    fps: int | None = Field(None, gt=0)
    max_restart: int | None = Field(None, ge=0)
    enable: bool | None = None
    enabled: bool | None = None
    department: str | None = None


# 功能：返回当前用户可读取的部门过滤值；输入与输出详见下方说明
# 参数：
#   - `user`（dict）：当前用户或待处理用户对象
#   - `requested_department`（str | None）：`requested_department` 对应的业务输入值
# 返回：str | None；返回下推给摄像头服务的部门过滤值，多事业部且未指定部门时返回 None 并由响应层执行授权集合过滤。
# 调用关系：
#   - 调用方：`AiVision/api/cameras.py` 的 `list_cameras` 调用本符号；`AiVision/api/compat.py` 的 `compat_list_cameras` 调用本符号
#   - 内部调用：`user.get`、`_camera_departments_for_user`、`len`、`HTTPException`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def camera_read_department(user: dict, requested_department: str | None) -> str | None:
    """返回当前用户可读取的部门过滤值。"""
    if user.get("role") == "admin":
        return requested_department
    departments = _camera_departments_for_user(user)
    if not departments:
        raise HTTPException(status_code=403, detail="camera department permission required")
    if requested_department is not None:
        if requested_department not in departments:
            raise HTTPException(status_code=403, detail="camera department permission required")
        return requested_department
    return departments[0] if len(departments) == 1 else None


# 功能：普通用户只读取运行所需元数据，摄像头连接地址仅管理员可见；输入与输出详见下方说明
# 参数：
#   - `camera`（dict[str, Any]）：摄像头配置或实体
#   - `user`（dict）：当前用户或待处理用户对象
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/cameras.py` 的 `camera_list_response_for_user` 调用本符号；`AiVision/api/cameras.py` 的 `get_camera_for_user`
#         调用本符号
#   - 内部调用：`dict`、`user.get`、`response.pop`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def camera_response_for_user(camera: dict[str, Any], user: dict) -> dict[str, Any]:
    """普通用户只读取运行所需元数据，摄像头连接地址仅管理员可见。"""
    response = dict(camera)
    if user.get("role") != "admin":
        response.pop("url", None)
    return response


# 功能：读取或查询 `camera_list_response_for_user` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `cameras`（list[dict[str, Any]]）：`cameras` 对应的业务输入值
#   - `user`（dict）：当前用户或待处理用户对象
# 返回：list[dict[str, Any]]；返回当前用户授权事业部内的摄像头列表，viewer 响应不含连接地址。
# 调用关系：
#   - 调用方：`AiVision/api/cameras.py` 的 `list_cameras` 调用本符号；`AiVision/api/compat.py` 的 `compat_list_cameras` 调用本符号
#   - 内部调用：`user.get`、`set`、`_camera_departments_for_user`、`camera_access_departments`、`isdisjoint`、`camera_response_for_user`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def camera_list_response_for_user(
    cameras: list[dict[str, Any]],
    user: dict,
) -> list[dict[str, Any]]:
    visible_cameras = cameras
    if user.get("role") != "admin":
        departments = set(_camera_departments_for_user(user))
        visible_cameras = [
            camera for camera in cameras
            if not departments.isdisjoint(camera_access_departments(camera))
        ]
    return [camera_response_for_user(camera, user) for camera in visible_cameras]


# 功能：按 key 读取摄像头，并阻止 viewer 通过 id/shm 枚举其他部门；输入与输出详见下方说明
# 参数：
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值
#   - `key`（str）：用于查询、分组或缓存的键
#   - `user`（dict）：当前用户或待处理用户对象
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/cameras.py` 的 `get_camera` 调用本符号；`AiVision/api/cameras.py` 的 `get_camera_frame_jpg`
#         调用本符号；`AiVision/api/compat.py` 的 `compat_get_camera` 调用本符号；`AiVision/api/compat.py` 的 `compat_get_camera_frame_jpg`
#         调用本符号；另有 1 处静态调用
#   - 内部调用：`camera_service.get_camera`、`HTTPException`、`user.get`、`_camera_departments_for_user`、`camera_access_departments`、`isdisjoint`、`camera_response_for_user`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def get_camera_for_user(camera_service, key: str, user: dict) -> dict[str, Any]:
    """按 key 读取摄像头，并阻止 viewer 通过 id/shm 枚举其他部门。"""
    camera = camera_service.get_camera(key)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    if user.get("role") != "admin":
        departments = set(_camera_departments_for_user(user))
        if not departments or departments.isdisjoint(camera_access_departments(camera)):
            raise HTTPException(status_code=403, detail="camera department permission required")
    return camera_response_for_user(camera, user)


# 功能：读取或查询 `list_cameras` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `department`（str | None）：业务部门名称或标识；默认值为 `Query(None, description='可选按部门过滤')`
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：list[dict[str, Any]]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`Depends`、`camera_list_response_for_user`、`camera_service.list_cameras`、`camera_read_department`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("")
def list_cameras(
    department: str | None = Query(None, description="可选按部门过滤"),
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
) -> list[dict[str, Any]]:
    return camera_list_response_for_user(
        camera_service.list_cameras(
            department=camera_read_department(user, department)
        ),
        user,
    )


# 功能：创建或构建 `create_camera` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `payload`（CameraCreateRequest）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.post('', status_code=status.HTTP_201_CREATED)` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`camera_service.create_camera`、`payload.model_dump`、`HTTPException`、`str`、`router.post`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.post("", status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreateRequest,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    try:
        return camera_service.create_camera(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# 功能：读取或查询 `get_camera` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{key}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`get_camera_for_user`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/{key}")
def get_camera(
    key: str,
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    return get_camera_for_user(camera_service, key, user)


# 功能：更新或保存 `update_camera` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `payload`（CameraUpdateRequest）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.put('/{key}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`camera_service.update_camera`、`payload.model_dump`、`HTTPException`、`str`、`router.put`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.put("/{key}")
def update_camera(
    key: str,
    payload: CameraUpdateRequest,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    try:
        camera = camera_service.update_camera(key, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera


# 功能：实现 `patch_camera` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `payload`（CameraUpdateRequest）：接口或事件携带的业务数据
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.patch('/{key}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`update_camera`、`router.patch`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.patch("/{key}")
def patch_camera(
    key: str,
    payload: CameraUpdateRequest,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, Any]:
    return update_camera(key, payload, _user, camera_service)


# 功能：删除或清理 `delete_camera` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `_user`（dict）：`_user` 对应的业务输入值；默认值为 `Depends(require_admin)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
# 返回：dict[str, bool]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.delete('/{key}')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Depends`、`camera_service.delete_camera`、`HTTPException`、`router.delete`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
@router.delete("/{key}")
def delete_camera(
    key: str,
    _user: dict = Depends(require_admin),
    camera_service=Depends(get_camera_service),
) -> dict[str, bool]:
    ok = camera_service.delete_camera(key)
    if not ok:
        raise HTTPException(status_code=404, detail="camera not found")
    return {"ok": True}


# 功能：转换或规范化 `encode_frame_to_jpeg` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `frame`（未显式标注）：待处理的视频图像帧
#   - `quality`（int）：`quality` 对应的业务输入值；默认值为 `85`
#   - `max_width`（int | None）：`max_width` 对应的业务输入值；默认值为 `None`
#   - `max_height`（int | None）：`max_height` 对应的业务输入值；默认值为 `None`
#   - `cache_token`（tuple[Any, ...] | None）：`cache_token` 对应的业务输入值；默认值为 `None`
# 返回：bytes；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/cameras.py` 的 `build_camera_frame_response` 调用本符号
#   - 内部调用：`HTTPException`、`max`、`min`、`int`、`_jpeg_cache.get`、`cv2.resize`、`cv2.imencode`、`encoded.tobytes`、`_jpeg_cache_order.append`、`len`
#          等共 12 个调用。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def encode_frame_to_jpeg(
    frame,
    quality: int = 85,
    max_width: int | None = None,
    max_height: int | None = None,
    cache_token: tuple[Any, ...] | None = None,
) -> bytes:
    if frame is None:
        raise HTTPException(status_code=404, detail="frame not available")
    quality = max(1, min(int(quality), 100))
    cache_key = (cache_token, quality, max_width, max_height) if cache_token is not None else None
    if cache_key is not None:
        with _jpeg_cache_lock:
            cached = _jpeg_cache.get(cache_key)
            if cached is not None:
                return cached

    if max_width or max_height:
        height, width = frame.shape[:2]
        width_scale = (max_width / width) if max_width and width > max_width else 1.0
        height_scale = (max_height / height) if max_height and height > max_height else 1.0
        scale = min(width_scale, height_scale)
        if scale < 1.0:
            frame = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise HTTPException(status_code=500, detail="failed to encode frame")
    content = encoded.tobytes()
    if cache_key is not None:
        with _jpeg_cache_lock:
            if cache_key not in _jpeg_cache:
                _jpeg_cache_order.append(cache_key)
            _jpeg_cache[cache_key] = content
            while len(_jpeg_cache_order) > _JPEG_CACHE_MAX_ITEMS:
                old_key = _jpeg_cache_order.pop(0)
                _jpeg_cache.pop(old_key, None)
    return content


# 功能：实现 `frame_size_headers` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `frame`（未显式标注）：待处理的视频图像帧
# 返回：dict[str, str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/cameras.py` 的 `build_camera_frame_response` 调用本符号
#   - 内部调用：`str`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def frame_size_headers(frame) -> dict[str, str]:
    if frame is None:
        return {}
    height, width = frame.shape[:2]
    return {
        "X-Frame-Width": str(width),
        "X-Frame-Height": str(height),
    }


# 功能：读取、编码并返回预览帧；慢请求输出分阶段耗时；输入与输出详见下方说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `feature`（str | None）：`feature` 对应的业务输入值
#   - `quality`（int）：`quality` 对应的业务输入值
#   - `max_width`（int | None）：`max_width` 对应的业务输入值
#   - `max_height`（int | None）：`max_height` 对应的业务输入值
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值
# 返回：Response；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/api/cameras.py` 的 `get_camera_frame_jpg` 调用本符号；`AiVision/api/compat.py` 的 `compat_get_camera_frame_jpg` 调用本符号
#   - 内部调用：`time.monotonic`、`hasattr`、`orchestrator.get_camera_frame_info`、`orchestrator.get_camera_frame`、`HTTPException`、`encode_frame_to_jpeg`、`logger.warning`、`Response`、`frame_size_headers`。
# 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
def build_camera_frame_response(
    *,
    key: str,
    feature: str | None,
    quality: int,
    max_width: int | None,
    max_height: int | None,
    orchestrator,
) -> Response:
    """读取、编码并返回预览帧；慢请求输出分阶段耗时。"""
    started_at = time.monotonic()
    if hasattr(orchestrator, "get_camera_frame_info"):
        frame, updated_at = orchestrator.get_camera_frame_info(key, feature=feature)
    else:
        frame, updated_at = orchestrator.get_camera_frame(key, feature=feature), 0.0
    lookup_seconds = time.monotonic() - started_at

    if frame is None and updated_at:
        raise HTTPException(status_code=503, detail="camera frame is stale")

    encode_started_at = time.monotonic()
    content = encode_frame_to_jpeg(
        frame,
        quality,
        max_width=max_width,
        max_height=max_height,
        cache_token=(key, feature or "", updated_at),
    )
    encode_seconds = time.monotonic() - encode_started_at
    total_seconds = time.monotonic() - started_at

    if total_seconds >= settings.runtime.slow_frame_log_seconds:
        height, width = frame.shape[:2]
        logger.warning(
            f"[CameraFrame] 慢响应 key={key} feature={feature or '-'} "
            f"lookup={lookup_seconds:.3f}s encode={encode_seconds:.3f}s "
            f"total={total_seconds:.3f}s source={width}x{height} "
            f"max_width={max_width or '-'} max_height={max_height or '-'}"
        )

    return Response(
        content=content,
        media_type="image/jpeg",
        headers=frame_size_headers(frame),
    )


# 功能：读取或查询 `get_camera_frame_jpg` 对应的`cameras` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `key`（str）：用于查询、分组或缓存的键
#   - `feature`（str | None）：`feature` 对应的业务输入值；默认值为 `Query(None, description='可选 feature 名，优先返回该功能的标注帧')`
#   - `quality`（int）：`quality` 对应的业务输入值；默认值为 `Query(85, ge=1, le=100)`
#   - `max_width`（int | None）：`max_width` 对应的业务输入值；默认值为 `Query(None, ge=1, le=4096)`
#   - `max_height`（int | None）：`max_height` 对应的业务输入值；默认值为 `Query(None, ge=1, le=4096)`
#   - `user`（dict）：当前用户或待处理用户对象；默认值为 `Depends(get_current_user)`
#   - `camera_service`（未显式标注）：`camera_service` 对应的业务输入值；默认值为 `Depends(get_camera_service)`
#   - `orchestrator`（未显式标注）：`orchestrator` 对应的业务输入值；默认值为 `Depends(get_current_orchestrator)`
# 返回：Response；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：由 FastAPI 按 `router.get('/{key}/frame.jpg')` 注册，并在请求到达时调用以生成接口响应
#   - 内部调用：`Query`、`Depends`、`get_camera_for_user`、`build_camera_frame_response`、`router.get`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@router.get("/{key}/frame.jpg")
def get_camera_frame_jpg(
    key: str,
    feature: str | None = Query(None, description="可选 feature 名，优先返回该功能的标注帧"),
    quality: int = Query(85, ge=1, le=100),
    max_width: int | None = Query(None, ge=1, le=4096),
    max_height: int | None = Query(None, ge=1, le=4096),
    user: dict = Depends(get_current_user),
    camera_service=Depends(get_camera_service),
    orchestrator=Depends(get_current_orchestrator),
) -> Response:
    get_camera_for_user(camera_service, key, user)
    return build_camera_frame_response(
        key=key,
        feature=feature,
        quality=quality,
        max_width=max_width,
        max_height=max_height,
        orchestrator=orchestrator,
    )
