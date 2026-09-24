"""
api/routes/cameras.py
摄像头 CRUD + 当前帧 JPEG 输出。
"""
from __future__ import annotations

import threading
import time
from typing import Any

import cv2
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from auth.auth import get_current_user, require_admin
from auth.feature_permissions import feature_departments, require_feature_access
from AiVision.api.deps import get_camera_config_manager, get_current_orchestrator
from AiVision.core.logger import logger
from AiVision.core.settings import settings
from AiVision.cameras.config_manager import camera_access_departments
from AiVision.departments.department_registry import DEPARTMENT_SPECS, require_department

# 摄像头API路由基础定义
router = APIRouter(prefix="/api/cameras", tags=["cameras"])

# ------- JPEG图片缓存 -------------
_JPEG_CACHE_MAX_ITEMS = 128                    # JPEG缓存最多保存128个结果
_jpeg_cache_lock = threading.Lock()            # 同一时间只允许一个线程修改JPEG缓存
_jpeg_cache: dict[tuple[Any, ...], bytes] = {} # JPEG缓存字典
_jpeg_cache_order: list[tuple[Any, ...]] = []  # 记录加入顺序，超过128时知道先删谁

# ------------------- 请求模型 ------------------
# 创建摄像头时前端可以传什么
# 平台总览：name + url + fps + department
# 检测功能：name + url + fps +department
class CameraCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    shm_name: str = Field(..., min_length=1)
    fps: int = Field(5, gt=0)
    enabled: bool | None = None
    department: str

# 修改摄像头时前端可以传什么
class CameraUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    fps: int | None = Field(None, gt=0)
    enabled: bool | None = None
    department: str | None = None

# ------------------  摄像头访问权限  ------------------------

def _camera_departments_for_user(user: dict) -> list[str]:
    """从当前登录用户信息里，整理出这个用户有权限访问的所有部门"""
    raw_departments = user.get("departments")
    candidates = raw_departments if isinstance(raw_departments, list) else []
    return list(dict.fromkeys(
        department for department in candidates
        if isinstance(department, str) and department in DEPARTMENT_SPECS
    ))


def camera_read_department(user: dict, requested_department: str) -> str:
    """摄像头列表必须明确事业部，并在查询前校验授权。"""
    try:
        department = require_department(requested_department)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if user.get("role") != "admin" and (
        user.get("role") != "viewer" or department not in _camera_departments_for_user(user)
    ):
        raise HTTPException(status_code=403, detail="camera department permission required")
    return department


def camera_response_for_user(camera: dict[str, Any], user: dict) -> dict[str, Any]:
    """按事业部分配过滤检测功能，仅管理员可读取摄像头地址。"""
    response = dict(camera)
    # 不是管理员就不让看url
    if user.get("role") != "admin":
        response.pop("url", None)
    response["functions"] = {
        feature: enabled for feature, enabled in camera["functions"].items()
        if camera["department"] in feature_departments(user, feature)
    }
    return response

# 批量过滤用户不能看的摄像头
def camera_list_response_for_user(
    cameras: list[dict[str, Any]],
    user: dict,
) -> list[dict[str, Any]]:
    """
    1、普通用户只保留自己有权限的摄像头
    2、再把普通用户不能看的url隐藏掉
    """
    visible_cameras = cameras

    if user.get("role") != "admin":
        # 获取当前用户可以查看的所有部门
        departments = set(_camera_departments_for_user(user))

        # 用户授权的部门和摄像头所属的部门，只要有至少一个重合，就允许查看
        # A.isdisjoint(B):表示A和B的交集是不是空集（前面加个not就是A和B有交集）
        visible_cameras = [
            camera for camera in cameras
            if not departments.isdisjoint(camera_access_departments(camera))       # camera_access_department返回这个摄像头属于哪些事业部
        ]
    
    # 对可以查看的摄像头做字段脱敏（普通用户删除RTSP）
    return [camera_response_for_user(camera, user) for camera in visible_cameras]     

# 指定访问某一台摄像头时，单独检查一次是否越权
def get_camera_for_user(camera_config_manager, key: str, user: dict) -> dict[str, Any]:
    """
    查询单台摄像头，检查当前用户有没有权限看，并最后做字段脱敏
    """
    # 查询key所对应摄像头的完整的配置
    camera = camera_config_manager.get_camera(key)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    if user.get("role") != "admin":
        # 查当前用户所能查看的所有部门
        departments = set(_camera_departments_for_user(user))
        # 没有授权部门或者这个摄像头不在当前部门读取列表中，就报403
        if not departments or departments.isdisjoint(camera_access_departments(camera)):
            raise HTTPException(status_code=403, detail="camera department permission required")

    # 做字段脱敏
    return camera_response_for_user(camera, user)

# ------------------ 摄像头CRUD -------------------------

@router.get("")
def list_cameras(
    department: str = Query(..., description="正式事业部编码"),
    user: dict = Depends(get_current_user),
    camera_config_manager=Depends(get_camera_config_manager),
) -> list[dict[str, Any]]:
    """仅返回请求指定且当前用户有权访问的事业部摄像头。"""
    scope = camera_read_department(user, department)
    cameras = camera_config_manager.list_cameras(department=scope)
    return camera_list_response_for_user(cameras, user)


@router.post("", status_code=status.HTTP_201_CREATED)      # HTTP给201  Created表示新的摄像头创建成功了
def create_camera(
    payload: CameraCreateRequest,                         # 创建的摄像头数据
    _user: dict = Depends(require_admin),                 # 只有管理员能创建
    camera_config_manager=Depends(get_camera_config_manager),
) -> dict[str, Any]:
    """
    新增摄像头
    """
    try:
        return camera_config_manager.create_camera(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/{key}")
def get_camera(
    key: str,
    user: dict = Depends(get_current_user),
    camera_config_manager=Depends(get_camera_config_manager),
) -> dict[str, Any]:
    """
    接收摄像头key和当前用户，然后调用统一的单摄像头权限查询函数
    """
    return get_camera_for_user(camera_config_manager, key, user)

@router.patch("/{key}")
def patch_camera(
    key: str,
    payload: CameraUpdateRequest,
    _user: dict = Depends(require_admin),
    camera_config_manager=Depends(get_camera_config_manager),
) -> dict[str, Any]:
    """局部修改某一台摄像头。"""
    try:
        camera = camera_config_manager.update_camera(key, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return camera

@router.delete("/{key}")
def delete_camera(
    key: str,
    _user: dict = Depends(require_admin),
    camera_config_manager=Depends(get_camera_config_manager),
) -> dict[str, bool]:
    """
    删除摄像头的HTTP接口
    """
    ok = camera_config_manager.delete_camera(key)
    if not ok:
        raise HTTPException(status_code=404, detail="camera not found")
    return {"ok": True}

# -------------------------  摄像头画面JPG输出 --------------------------
def encode_frame_to_jpeg(
    frame,
    quality: int = 85,
    max_width: int | None = None,
    max_height: int | None = None,
    cache_token: tuple[Any, ...] | None = None,
) -> bytes:
    """
    把OpenCV图像帧转成浏览器能直接显示的JPEG二进制
    按照指定尺寸和质量压缩成JPEG，如果同一帧已经压缩过，直接走缓存
    参数：
        frame: Opencv图像帧，numpy.ndarray格式，三通道
        qulity：JPEG压缩质量：1~100：越大越清晰，文件大小越大
        max_width: 图片最大的宽度值
        max_height: 图片最大的高度值
        cache_token: 用来标识当前是否与上一帧相同的缓存标识，里面有updated_at,uodate_at没变说明就是同一帧
    """
    # 没有画面报404
    if frame is None:
        raise HTTPException(status_code=404, detail="frame not available")
    # 限制JPEG的质量范围
    quality = max(1, min(int(quality), 100))
    # 构造缓存key
    cache_key = (cache_token, quality, max_width, max_height) if cache_token is not None else None
    # 如果已经编码过完全相同的缓存帧，就直接返回JPEG
    if cache_key is not None:
        with _jpeg_cache_lock:
            cached = _jpeg_cache.get(cache_key)
            if cached is not None:
                return cached

    # 图片缩放（只有前端要求最大宽度或最大高度时才考虑缩图）
    if max_width or max_height:
        height, width = frame.shape[:2]
        # 计算宽高的缩放比例
        width_scale = (max_width / width) if max_width and width > max_width else 1.0
        height_scale = (max_height / height) if max_height and height > max_height else 1.0
        scale = min(width_scale, height_scale)
        if scale < 1.0:
            # 图片缩小
            frame = cv2.resize(
                frame,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
    # 对opencv图像进行编码，编码失败HTTP 500，opencv返回的encode是numpy数组
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise HTTPException(status_code=500, detail="failed to encode frame")
    # 将编码的numpy数组转换为二进制数据
    content = encoded.tobytes()
    if cache_key is not None:
        with _jpeg_cache_lock:
            if cache_key not in _jpeg_cache:
                _jpeg_cache_order.append(cache_key)   # 记录缓存加入顺序 
            _jpeg_cache[cache_key] = content   # 将刚刚编码的帧放入缓存
            # 删除最老的一条缓存
            while len(_jpeg_cache_order) > _JPEG_CACHE_MAX_ITEMS:
                old_key = _jpeg_cache_order.pop(0)
                _jpeg_cache.pop(old_key, None)
    return content

def frame_size_headers(
    frame,
    max_width: int | None = None,
    max_height: int | None = None,
) -> dict[str, str]:
    """
    将当前图像帧的宽度和高度，放进HTTP响应头里返回给前端
    """
    if frame is None:
        return {}
    height, width = frame.shape[:2]
    width_scale = (max_width / width) if max_width and width > max_width else 1.0
    height_scale = (max_height / height) if max_height and height > max_height else 1.0
    scale = min(width_scale, height_scale)
    if scale < 1.0:
        width = max(1, int(width * scale))
        height = max(1, int(height * scale))
    return {
        "X-Frame-Width": str(width),
        "X-Frame-Height": str(height),
    }


def frame_coordinate_size_headers(frame) -> dict[str, str]:
    """返回检测配置与 ROI 使用的原始帧坐标尺寸。"""
    if frame is None:
        return {}
    height, width = frame.shape[:2]
    return {
        "X-Frame-Coordinate-Width": str(width),
        "X-Frame-Coordinate-Height": str(height),
    }

def build_camera_frame_response(
    *,
    key: str,                                         # 摄像头
    feature: str | None,                              # 指定功能只返回该功能的标注画面
    quality: int,                                     
    max_width: int | None,
    max_height: int | None,
    orchestrator,                                     # 当前画面从这里拿
) -> Response:
    """
    摄像头预览图HTTP响应总流程：
        取帧
        判断新鲜度
        JPEG编码
        性能监控
        返回图片
    """
    # 开始计时
    started_at = time.monotonic()
    # 从Orchestrator获取画面
    frame, updated_at = orchestrator.get_camera_frame_info(key, feature=feature)
    # 计算取帧耗时
    lookup_seconds = time.monotonic() - started_at
    # 画面是否过期，HTTP503
    if frame is None and updated_at:
        raise HTTPException(status_code=503, detail="camera frame is stale")

    # 开始统计JPEG编码时间
    encode_started_at = time.monotonic()
    content = encode_frame_to_jpeg(
        frame,
        quality,
        max_width=max_width,
        max_height=max_height,
        cache_token=(key, feature or "", updated_at),
    )
    # 计算JPEG编码耗时
    encode_seconds = time.monotonic() - encode_started_at
    # 计算整个请求耗时
    total_seconds = time.monotonic() - started_at

    # 请求耗时大于配置的值，就会打印Warning日志
    if total_seconds >= settings.runtime.slow_frame_log_seconds:
        height, width = frame.shape[:2]
        logger.warning(
            f"[CameraFrame] 慢响应 key={key} feature={feature or '-'} "         # 哪个摄像头、哪个功能
            f"lookup={lookup_seconds:.3f}s encode={encode_seconds:.3f}s "       # 查帧耗时、编码耗时
            f"total={total_seconds:.3f}s source={width}x{height} "              # 总耗时、原始分辨率
            f"max_width={max_width or '-'} max_height={max_height or '-'}"      # 要求的最大宽高
        )

    # 最后返回HTTP图片
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            **frame_size_headers(frame, max_width=max_width, max_height=max_height),
            **frame_coordinate_size_headers(frame),
        },
    )

@router.get("/{key}/frame.jpg")
def get_camera_frame_jpg(
    key: str,
    feature: str | None = Query(None, description="指定 feature 时只返回该功能标注帧；不传则返回原始帧"),
    quality: int = Query(85, ge=1, le=100),
    max_width: int | None = Query(None, ge=1, le=4096),
    max_height: int | None = Query(None, ge=1, le=4096),
    user: dict = Depends(get_current_user),
    camera_config_manager=Depends(get_camera_config_manager),
    orchestrator=Depends(get_current_orchestrator),
) -> Response:
    """
    摄像头实时预览图的HTTP入口，先做权限检查、再从Orchestrator取图并返回JPEG
    参数：
        key：哪台摄像头
        feature： 有feature就会优先返回检测好的标注帧
        quality: JPEG压缩质量
        max_width: 前端要求的最大宽
        max_height: 前端要求的最大高度
        user: 获取当前登录用户
        camera_config_manager:做摄像头存在性和部门权限检查
        orchestrator：提供当前运行画面的对象
    """
    # 这个函数做：1、摄像头不存在：404，2、用户没有权限：403，3、有权限：继续
    camera = get_camera_for_user(camera_config_manager, key, user)
    if feature is not None:
        from AiVision.features.registry import get_spec
        if get_spec(feature) is None:
            raise HTTPException(status_code=404, detail="unknown feature")
        require_feature_access(user, feature, camera["department"])
    return build_camera_frame_response(
        key=camera["shm_name"],
        feature=feature,
        quality=quality,
        max_width=max_width,
        max_height=max_height,
        orchestrator=orchestrator,
    )
