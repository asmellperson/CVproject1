"""助手会话、幂等请求和配置审计；每次数据库操作使用独立事务。"""
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from AiVision.core.config_revision import configuration_revision, require_configuration_values
from AiVision.core.db import get_session, session_scope
from AiVision.core.system_config import AiSystemConfig
from AiVision.features.security_inspection.service import InspectionService
from .orm import AssistantAction, AssistantSession, AssistantTurn
from .resources import ConfigurationCatalog
from .schema import ActionResponse, AssistantSettings, ConversationResponse, SessionResponse, TurnResponse


ACTIVE_STATUSES = ("queued", "running")
SETTINGS_KEY = "assistant"


def access_scope(user: dict, department: str | None) -> dict:
    catalog = ConfigurationCatalog(user, department)
    return {"role": user["role"], "departments": catalog.departments,
            "feature_access": {key: user["feature_access"].get(key, []) for key in catalog.departments}}


def scope_visible(previous: dict, current: dict) -> bool:
    return (not (previous["role"] == "admin" and current["role"] != "admin")
            and set(previous["departments"]) <= set(current["departments"])
            and all(set(features) <= set(current["feature_access"].get(department, []))
                    for department, features in previous["feature_access"].items()))


def session_response(row) -> SessionResponse:
    return SessionResponse(id=row.id, title=row.title, department=row.department,
                           created_at=row.created_at, updated_at=row.updated_at)


def action_response(row) -> ActionResponse:
    return ActionResponse(id=row.id, resource=row.resource, status=row.status, before=row.before,
                          after=row.after, changes=row.changes, detail=row.detail, created_at=row.created_at)


def turn_response(session, row, actions=None) -> TurnResponse:
    if actions is None:
        actions = session.scalars(select(AssistantAction).where(AssistantAction.turn_id == row.id)
                                  .order_by(AssistantAction.created_at, AssistantAction.id)).all()
    return TurnResponse(id=row.id, request_id=row.request_id, question=row.question, answer=row.answer,
                        status=row.status, progress=row.progress, created_at=row.created_at,
                        actions=[action_response(action) for action in actions])


class AssistantService:
    def settings(self) -> AssistantSettings:
        with get_session() as session:
            row = session.get(AiSystemConfig, SETTINGS_KEY)
            if row is not None:
                return AssistantSettings.model_validate(row.value)
        inherited = InspectionService().get_settings().model_dump(include=set(AssistantSettings.model_fields))
        return AssistantSettings.model_validate(inherited)

    def save_settings(self, value: AssistantSettings, *, expected_values: dict | None = None) -> None:
        with session_scope() as session:
            row = session.get(AiSystemConfig, SETTINGS_KEY, with_for_update=True)
            current = AssistantSettings.model_validate(row.value) if row else self.settings()
            require_configuration_values(current.model_dump(), expected_values)
            if row is None:
                session.add(AiSystemConfig(key=SETTINGS_KEY, value=value.model_dump()))
            else:
                row.value = value.model_dump()

    @staticmethod
    def _owned(session, session_id: str, user: dict, *, lock=False):
        row = session.get(AssistantSession, session_id, with_for_update=lock)
        if row is None or row.employee_id != user["employee_id"]:
            raise HTTPException(404, "会话不存在或不可访问")
        ConfigurationCatalog(user, row.department)
        return row

    def create_session(self, user: dict, department: str | None) -> SessionResponse:
        ConfigurationCatalog(user, department)
        with session_scope() as session:
            row = AssistantSession(id=str(uuid4()), employee_id=user["employee_id"], department=department)
            session.add(row)
            session.flush()
            return session_response(row)

    def sessions(self, user: dict, department: str | None) -> list[SessionResponse]:
        ConfigurationCatalog(user, department)
        with get_session() as session:
            rows = session.scalars(select(AssistantSession).where(
                AssistantSession.employee_id == user["employee_id"], AssistantSession.department == department,
            ).order_by(AssistantSession.updated_at.desc()).limit(100))
            return [session_response(row) for row in rows]

    def conversation(self, session_id: str, user: dict) -> ConversationResponse:
        with get_session() as session:
            row = self._owned(session, session_id, user)
            scope = access_scope(user, row.department)
            turns = session.scalars(select(AssistantTurn).where(AssistantTurn.session_id == row.id)
                                    .order_by(AssistantTurn.id.desc()).limit(100)).all()[::-1]
            visible = [turn for turn in turns if scope_visible(turn.access_scope, scope)]
            actions = {turn.id: [] for turn in visible}
            if actions:
                for action in session.scalars(select(AssistantAction).where(AssistantAction.turn_id.in_(actions))
                                              .order_by(AssistantAction.created_at, AssistantAction.id)):
                    actions[action.turn_id].append(action)
            return ConversationResponse(session=session_response(row), turns=[turn_response(session, item, actions[item.id]) for item in visible],
                                        hidden_turns=len(turns) - len(visible))

    def duplicate(self, session_id: str, request_id: str, user: dict) -> TurnResponse | None:
        with get_session() as session:
            row = self._owned(session, session_id, user)
            turn = session.scalar(select(AssistantTurn).where(AssistantTurn.request_id == request_id))
            if turn is None:
                return None
            if turn.session_id != row.id or not scope_visible(turn.access_scope, access_scope(user, row.department)):
                raise HTTPException(409, "请求编号不可重复使用")
            return turn_response(session, turn)

    def enqueue(self, session_id: str, request_id: str, question: str, user: dict) -> TurnResponse:
        with session_scope() as session:
            row = self._owned(session, session_id, user, lock=True)
            if session.scalar(select(AssistantTurn.id).where(
                AssistantTurn.session_id == row.id, AssistantTurn.status.in_(ACTIVE_STATUSES),
            )) is not None:
                raise HTTPException(409, "当前会话仍有任务在处理，请等待或停止后再发送")
            turn = AssistantTurn(session_id=row.id, request_id=request_id, question=question,
                                 access_scope=access_scope(user, row.department))
            session.add(turn)
            row.updated_at = datetime.now()
            if row.title == "新对话":
                row.title = question[:60]
            session.flush()
            return turn_response(session, turn)

    def cancel(self, session_id: str, turn_id: int, user: dict) -> None:
        with session_scope() as session:
            self._owned(session, session_id, user, lock=True)
            turn = session.get(AssistantTurn, turn_id, with_for_update=True)
            if turn is None or turn.session_id != session_id:
                raise HTTPException(404, "任务不存在")
            if turn.status in ACTIVE_STATUSES:
                turn.cancel_requested = 1
                turn.progress = "正在停止；已经保存的配置会保留在操作记录中"

    def cancelled(self, turn_id: int, user: dict) -> bool:
        with get_session() as session:
            turn = session.get(AssistantTurn, turn_id)
            row = self._owned(session, turn.session_id, user)
            if not scope_visible(turn.access_scope, access_scope(user, row.department)):
                raise HTTPException(403, "账号权限已变化，本次任务停止")
            return bool(turn.cancel_requested) or turn.status not in ACTIVE_STATUSES

    def progress(self, turn_id: int, message: str) -> None:
        with session_scope() as session:
            turn = session.get(AssistantTurn, turn_id, with_for_update=True)
            if turn.status in ACTIVE_STATUSES:
                turn.status = "running"
                turn.progress = message[:255]

    def finish(self, turn_id: int, status: str, answer: str) -> None:
        with session_scope() as session:
            turn = session.get(AssistantTurn, turn_id, with_for_update=True)
            turn.status, turn.answer, turn.progress = status, answer, ""
            session.get(AssistantSession, turn.session_id).updated_at = datetime.now()

    @staticmethod
    def has_actions(turn_id: int) -> bool:
        with get_session() as session:
            return session.scalar(select(AssistantAction.id).where(AssistantAction.turn_id == turn_id).limit(1)) is not None

    @staticmethod
    def find_action(turn_id: int, resource_key: str) -> ActionResponse | None:
        with get_session() as session:
            row = session.scalar(select(AssistantAction).where(
                AssistantAction.turn_id == turn_id, AssistantAction.resource_key == resource_key,
            ))
            return action_response(row) if row is not None else None

    def begin_action(self, turn_id: int, reference, before: dict, changes: dict) -> tuple[ActionResponse, bool]:
        identity = {"resource": reference.key}
        if reference.kind not in {"camera_creation", "camera_binding", "camera_deletion"}:
            identity.update(before=before, changes=changes)
        operation_key = configuration_revision(identity)
        with session_scope() as session:
            existing = session.scalar(select(AssistantAction).where(
                AssistantAction.turn_id == turn_id, AssistantAction.operation_key == operation_key,
            ))
            if existing is not None:
                return action_response(existing), False
            row = AssistantAction(id=str(uuid4()), turn_id=turn_id, resource_key=reference.key,
                                  operation_key=operation_key,
                                  resource=reference.model_dump(), before=before, changes=changes, status="executing")
            session.add(row)
            session.flush()
            return action_response(row), True

    def finish_action(self, action_id: str, status: str, after: dict | None, detail: str) -> ActionResponse:
        with session_scope() as session:
            row = session.get(AssistantAction, action_id, with_for_update=True)
            row.status, row.after, row.detail = status, after, detail
            session.flush()
            return action_response(row)

    def action(self, action_id: str, session_id: str, user: dict) -> ActionResponse:
        conversation = self.conversation(session_id, user)
        for turn in conversation.turns:
            for action in turn.actions:
                if action.id == action_id:
                    return action
        raise HTTPException(404, "操作记录不存在或不可访问")

    @staticmethod
    def recover() -> None:
        with session_scope() as session:
            session.query(AssistantTurn).filter(AssistantTurn.status.in_(ACTIVE_STATUSES)).update(
                {"status": "interrupted", "progress": "", "answer": "平台已重启，任务已中断。请核对操作记录后重新发起指令。"},
                synchronize_session=False,
            )
            session.query(AssistantAction).filter_by(status="executing").update(
                {"status": "unknown", "detail": "平台重启前未完成结果核对，请检查实际配置，禁止直接重试创建"},
                synchronize_session=False,
            )


assistant_service = AssistantService()
