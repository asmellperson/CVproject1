"""福达AI助手 API：账号私有会话、异步指令与管理员模型设置。"""
from fastapi import APIRouter, Depends, HTTPException, Request

from auth.auth import get_current_user, get_current_user_from_request, require_admin
from AiVision.api.deps import get_optional_orchestrator
from AiVision.assistant.resources import ConfigurationCatalog
from AiVision.assistant.schema import (
    AssistantSettings, ConversationResponse, MessageCreate, SessionCreate, SessionResponse, TurnResponse,
)
from AiVision.assistant.service import assistant_service


router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/settings", response_model=AssistantSettings)
def get_settings(_user=Depends(require_admin)):
    return assistant_service.settings()


@router.put("/settings", response_model=AssistantSettings)
def save_settings(payload: AssistantSettings, _user=Depends(require_admin)):
    assistant_service.save_settings(payload)
    return assistant_service.settings()


@router.get("/capabilities")
def capabilities(department: str | None = None, user=Depends(get_current_user)):
    return ConfigurationCatalog(user, department).capabilities()


@router.get("/sessions", response_model=list[SessionResponse])
def sessions(department: str | None = None, user=Depends(get_current_user)):
    return assistant_service.sessions(user, department)


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(payload: SessionCreate, user=Depends(get_current_user)):
    return assistant_service.create_session(user, payload.department)


@router.get("/sessions/{session_id}", response_model=ConversationResponse)
def conversation(session_id: str, user=Depends(get_current_user)):
    return assistant_service.conversation(session_id, user)


@router.post("/sessions/{session_id}/messages", response_model=TurnResponse, status_code=202)
def message(session_id: str, payload: MessageCreate, request: Request):
    try:
        # 后台每个工具都重新校验账号权限与登录有效性，不复用中间件缓存的身份。
        return request.app.state.assistant.submit(
            session_id, payload, lambda: get_current_user_from_request(request), get_optional_orchestrator(),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sessions/{session_id}/turns/{turn_id}/cancel", status_code=204)
def cancel(session_id: str, turn_id: int, user=Depends(get_current_user)):
    assistant_service.cancel(session_id, turn_id, user)
