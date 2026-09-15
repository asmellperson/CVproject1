"""批量处置授权使用真实认证、历史报警归属快照和原有类型权限。"""
import asyncio
from datetime import datetime
import importlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from auth.auth import create_token
from auth.user_store import UserStore
from AiVision.alarms.records.orm import AiAlarmEvent

alarms = importlib.import_module("AiVision.api.routes.alarms")


@pytest.fixture
def alarm_api(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_USERS_DB", str(tmp_path / "auth.sqlite"))
    monkeypatch.setenv("AUTH_SECRET", "alarm-batch-tests-only-secret-value")
    users = {}
    auth_store = UserStore(database_path=tmp_path / "auth.sqlite")
    for key, departments in {
        "ge": ["general_electric"], "haoda": ["haoda_company"],
        "both": ["general_electric", "haoda_company"], "research": ["research_institute"],
        "admin": ["all"],
    }.items():
        users[key] = auth_store.create_user(
            employee_id=key, name=f"测试用户-{key}", role="admin" if key == "admin" else "viewer",
            departments=departments, password_hash="test-only-unused-hash",
        )
    engine = create_engine(f"sqlite:///{tmp_path / 'alarms.sqlite'}")
    AiAlarmEvent.__table__.create(engine)
    # 旧报警加上两千条更新的报警；权限查询不得依赖最近列表。
    rows = [{"id": number, "image_path": "private-evidence", "violation_type": 5,
             "feature_name": "detect_human", "department": "general_electric" if number % 2 else "haoda_company",
             "camera_no": "same-camera-current-owner-is-irrelevant", "create_time": datetime(2020, 1, 1)}
            for number in range(1, 2002)]
    rows += [{**rows[0], "id": 3001, "department": "general_electric", "violation_type": 3,
              "feature_name": "detect_phone"},
             {**rows[0], "id": 3002, "department": "research_institute", "violation_type": 3,
              "feature_name": "detect_phone"},
             {**rows[0], "id": 3003, "department": None}]
    with engine.begin() as connection:
        connection.execute(AiAlarmEvent.__table__.insert(), rows)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(alarms, "get_session", factory)
    app = FastAPI()
    app.include_router(alarms.router)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cu, sql, _p, _ctx, _many: statements.append(sql))
    yield SimpleNamespace(app=app, users=users, tokens={key: create_token(user) for key, user in users.items()},
                          statements=statements)
    engine.dispose()


@pytest.mark.parametrize("key,expected", [
    ("ge", [1]), ("haoda", [2]), ("both", [1, 2]), ("research", [3002]),
    ("admin", [1, 2, 3001, 3002, 3003]),
])
def test_batch_returns_only_authorized_ids_and_one_indexed_query(alarm_api, key, expected):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=alarm_api.app), base_url="http://aivision") as client:
            response = await client.post("/api/alarms/access-check", json={"alarm_ids": [1, 2, 3001, 3002, 3003, 9999]},
                                         headers={"Authorization": f"Bearer {alarm_api.tokens[key]}"})
        assert response.status_code == 200
        assert response.json() == {"allowed_ids": expected}
        assert len(alarm_api.statements) == 1
        sql = alarm_api.statements[0]
        assert " IN (" in sql and "LIMIT" not in sql
        assert "image_path" not in sql and "camera_no" not in sql
    asyncio.run(scenario())


def test_batch_uses_current_database_user_not_token_or_client_claims(alarm_api):
    async def scenario():
        # 签名有效但角色和事业部声明过时，实际账号仍是通用电气 viewer。
        stale_token = create_token({**alarm_api.users["ge"], "role": "admin", "departments": ["all"]})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=alarm_api.app), base_url="http://aivision") as client:
            assert (await client.post("/api/alarms/access-check", json={"alarm_ids": [1]})).status_code == 401
            response = await client.post("/api/alarms/access-check?department=haoda_company", json={"alarm_ids": [1, 2]},
                                         headers={"Authorization": f"Bearer {stale_token}", "X-Department": "haoda_company"})
            assert response.json() == {"allowed_ids": [1]}
            response = await client.post("/api/alarms/access-check", json={"alarm_ids": [2], "allowed_ids": [2], "department": "haoda_company"},
                                         headers={"Authorization": f"Bearer {stale_token}"})
            assert response.status_code == 422
    asyncio.run(scenario())


@pytest.mark.parametrize("ids", [[], list(range(1, 102)), [True], ["1"], [0], [-1], [2**64]])
def test_batch_rejects_unbounded_or_invalid_ids_before_sql(alarm_api, ids):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=alarm_api.app), base_url="http://aivision") as client:
            response = await client.post("/api/alarms/access-check", json={"alarm_ids": ids},
                                         headers={"Authorization": f"Bearer {alarm_api.tokens['ge']}"})
        assert response.status_code == 422
        assert alarm_api.statements == []
    asyncio.run(scenario())
