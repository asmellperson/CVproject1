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
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=1, max_length=4096)


class ModelRuntimeResponse(BaseModel):
    status: str
    running: bool
    alive: bool
    loaded_path: str
    last_failure: str
    shared_models: list[str]
    restart_attempts: int = 0
    next_restart_in_seconds: float = 0


class ModelReloadResponse(BaseModel):
    status: Literal["idle", "loading", "succeeded", "failed", "not_started"]
    error: str


class ModelResponse(BaseModel):
    name: str
    type: str
    path: str
    runtime: ModelRuntimeResponse
    reload: ModelReloadResponse


class ModelPathSaveResponse(BaseModel):
    configuration_saved: bool
    name: str
    path: str
    load_status: Literal["loading", "not_started"]


@router.get("", response_model=list[ModelResponse])
def list_models(runtime=Depends(get_inference_runtime_manager)):
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
