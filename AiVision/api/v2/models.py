"""
api/v2/models.py
推理模型配置 CRUD。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import require_admin
from api.deps import get_model_service


router = APIRouter(prefix="/api/v2/models", tags=["models"])


class ModelUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1)
    type: str | None = Field(None, min_length=1)
    path: str | None = Field(None, min_length=1)
    import_path: str | None = None
    description: str | None = None
    enable: bool | None = None


class ModelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field("yolo", min_length=1)
    path: str = Field(..., min_length=1)
    import_path: str | None = None
    description: str | None = None
    enable: bool = True


@router.get("")
def list_models(model_service=Depends(get_model_service)) -> list[dict[str, Any]]:
    return model_service.list_models(enabled_only=False)


@router.post("")
def create_model(
    payload: ModelCreateRequest,
    _user: dict = Depends(require_admin),
    model_service=Depends(get_model_service),
) -> dict[str, Any]:
    return model_service.create_model(payload.model_dump())


@router.get("/{model_id}")
def get_model(model_id: int, model_service=Depends(get_model_service)) -> dict[str, Any]:
    model = model_service.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


@router.put("/{model_id}")
def update_model(
    model_id: int,
    payload: ModelUpdateRequest,
    _user: dict = Depends(require_admin),
    model_service=Depends(get_model_service),
) -> dict[str, Any]:
    model = model_service.update_model(model_id, payload.model_dump(exclude_none=True))
    if model is None:
        raise HTTPException(status_code=404, detail="model not found")
    return model


@router.patch("/{model_id}")
def patch_model(
    model_id: int,
    payload: ModelUpdateRequest,
    _user: dict = Depends(require_admin),
    model_service=Depends(get_model_service),
) -> dict[str, Any]:
    return update_model(model_id, payload, _user, model_service)
