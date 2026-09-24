"""
api/routes/runtime.py
运行状态、健康检查接口。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends                        # APIRouter：API路由分组器,Depends:FastAPI的依赖注入机制
from collections import Counter
from auth.auth import get_current_user
from AiVision.api.routes.cameras import camera_list_response_for_user
from AiVision.api.deps import get_camera_config_manager

from AiVision.api.deps import get_current_orchestrator                 # 获取当前的Orchestrator实例，这是API层获取当前AiVision总调度器的统一入口
from AiVision.core.settings import settings                            # AiVision全局配置对象，主要用于读取当前数据库名称

# 创建“运行状态相关接口”的路由分组，并规定这组接口统一以/api/runtime开头
router = APIRouter(prefix="/api/runtime", tags=["runtime"])

@router.get("/health")               # FastAPI路由装饰器
def health(orchestrator=Depends(get_current_orchestrator)) -> dict:
    """
    AiVision健康检查接口
    系统运行状态判定：Orchestrator已完成启动，并且至少一个模型正在运行，则ok=True
    同时返回模型数量、Worker看门狗状态和数据库名称
    主要供start.sh,status.sh及外部监控判断AiVision是否就绪
    """
    status = orchestrator.runtime_status()                   # 整个AiVision当前运行状态的汇总结果
    started = bool(status.get("started", False))             # 启动流程是否完成
    models = status.get("running_models") or []              # 获取运行中的模型
    model_ready = len(models) > 0                            # 至少有一个模型在运行
    ready = started and model_ready                          # orcheatrator完成启动，并且至少有一个模型正在运行，则代表Aivision健康
    inference = status.get("inference") or {}                
    worker_status = inference.get("workers") or {}           # 获取推理工作线程的运行状态
    # 返回健康检查结果，FastAPI会自动转成JSON
    return {
        "ok": ready,
        "service": "AiVision",
        "started": started,
        "model_ready": model_ready,
        "running_models_count": len(models),
        "worker_watchdog_running": bool(worker_status.get("watchdog_running", False)),     # 模型运行状态监控线程目前有没有在运行
        "model_workers": worker_status.get("models") or [],                                # 每一个模型更详细的运行状态
        "database": settings.db.name,                                                      # 返回当前AiVision配置连接的数据库名称
    }

@router.get("/status")
def runtime_status(
    orchestrator=Depends(get_current_orchestrator),
    user: dict = Depends(get_current_user),
    camera_config_manager=Depends(get_camera_config_manager),
) -> dict:
    """AiVision完整运行状态查询接口"""
    status = orchestrator.runtime_status()
    if user.get("role") == "admin":
        return status
    cameras = camera_list_response_for_user(camera_config_manager.list_cameras(), user)
    names = {camera["shm_name"] for camera in cameras}
    features = {name for camera in cameras for name, enabled in camera["functions"].items() if enabled}
    consumers = {}
    for name, snapshot in status.get("inference", {}).get("consumers", {}).items():
        if name not in features:
            continue
        # 同一账号的其他事业部可能没有该功能，目标统计也必须按功能筛选摄像头。
        feature_camera_ids = {camera["camera_id"] for camera in cameras if camera["functions"].get(name)}
        targets = [target for target in snapshot.get("targets", []) if target.get("camera_id") in feature_camera_ids]
        totals = Counter()
        for target in targets:
            totals.update(target.get("counts", {}))
        consumers[name] = {"targets": targets, "totals": dict(totals)}
    return {
        **status,
        "running_cameras": [name for name in status.get("running_cameras", []) if name in names],
        "running_consumers": [name for name in status.get("running_consumers", []) if name in features],
        # Worker 级统计跨摄像头聚合，只有管理员读取；普通用户仅获取授权摄像头统计。
        "inference": {"consumers": consumers},
    }
