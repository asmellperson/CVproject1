"""
api/routes/models.py
固定模型状态与本机路径配置。
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from auth.auth import require_admin
from AiVision.api.deps import get_inference_runtime_manager


router = APIRouter(prefix="/api/models", tags=["models"])


class ModelPathUpdateRequest(BaseModel):
    """固定模型的本机权重路径更新请求，路径有效性由运行服务校验。"""
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=1, max_length=4096)


class ModelRuntimeResponse(BaseModel):
    """展示当前进程、已加载路径、共享模型组与自动重启进度。"""
    status: str
    running: bool
    alive: bool
    loaded_path: str
    last_failure: str
    shared_models: list[str]
    restart_attempts: int = 0
    next_restart_in_seconds: float = 0


class ModelReloadResponse(BaseModel):
    """区分配置保存后的异步加载状态及失败原因。"""
    status: Literal["idle", "loading", "succeeded", "failed", "not_started"]
    error: str


class ModelResponse(BaseModel):
    """固定模型声明、已配置路径及实际运行状态。"""
    name: str
    type: str
    path: str
    runtime: ModelRuntimeResponse
    reload: ModelReloadResponse


class ModelPathSaveResponse(BaseModel):
    """表示路径已保存及加载是否启动，不代表模型已经成功就绪。"""
    configuration_saved: bool
    name: str
    path: str
    load_status: Literal["loading", "not_started"]


@router.get("", response_model=list[ModelResponse])
def list_models(runtime=Depends(get_inference_runtime_manager)):
    """查询固定模型列表及状态，配置读取失败时返回服务不可用。"""
    try:
        return runtime.list_models()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.patch("/{model_name}/path", response_model=ModelPathSaveResponse, status_code=202)
def patch_model_path(
    model_name: str,
    payload: ModelPathUpdateRequest,
    _user: dict = Depends(require_admin),
    runtime=Depends(get_inference_runtime_manager),
):
    """管理员保存本机模型路径并触发关联模型重载，按错误类型返回明确状态。"""
    try:
        return runtime.update_model_path(model_name, payload.path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知的固定模型") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"模型路径配置保存失败: {exc}") from exc
