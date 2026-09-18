"""用实际 Chat Completions 报文验证解析、失败隔离和下游业务契约。"""

import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth.auth import get_current_user
from AiVision.api.routes import security_inspection as api
from AiVision.cameras.orm import AiCameraConfig
from AiVision.features.security_inspection import service as service_module
from AiVision.features.security_inspection.orm import InspectionSession
from AiVision.features.security_inspection.runtime import InspectionRuntime
from AiVision.features.security_inspection.schema import InspectionVerdict, VlmHealth, VlmSettings
from AiVision.features.security_inspection.service import InspectionService
from AiVision.features.security_inspection.vlm import VlmClient, VlmError, parse_completion
from AiVision.tests.test_security_inspection import inspection_alarms as inspection_alarms
from AiVision.tests.test_security_inspection import task, wait_for


RESULT = {"compliant": False, "confidence": 0.92, "reason": "安检员离岗，被检人独自通过。"}


def completion(content, *, finish_reason="stop", refusal=None):
    return json.dumps(
        {
            "id": "chatcmpl-inspection-test",
            "object": "chat.completion",
            "created": 1789715179,
            "model": "fuda-qwen36-27b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content, "refusal": refusal},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        },
        ensure_ascii=False,
    )


@pytest.fixture
def model_http(monkeypatch):
    calls = []

    def respond(body, status=200):
        def post(url, **kwargs):
            calls.append((url, kwargs))
            response = requests.Response()
            response.status_code = status
            response.encoding = "utf-8"
            response._content = body.encode("utf-8")
            response._content_consumed = True
            return response

        monkeypatch.setattr(requests, "post", post)
        return calls

    return respond


@pytest.mark.parametrize("compliant", [True, False])
@pytest.mark.parametrize("confidence", [0, 0.9, 1])
@pytest.mark.parametrize(
    "wrapper",
    [
        "{}",
        " \n{}\t ",
        "```json\n{}\n```",
        "```\n{}\n```",
        "<think>\n\n</think>\n\n{}",
        "<think> </think>\n```json\n{}\n```",
    ],
)
def test_json_contract_preserves_model_verdict(compliant, confidence, wrapper):
    data = {"compliant": compliant, "confidence": confidence, "reason": "  图像细节有限，依据整组画面判断。\n"}
    result = parse_completion(completion(wrapper.format(json.dumps(data, ensure_ascii=False))))
    assert isinstance(result, InspectionVerdict)
    assert result.model_dump() == data | {"reason": data["reason"].strip()}


def test_standard_chat_completion_and_image_request(model_http, monkeypatch):
    calls = model_http(completion(json.dumps(RESULT)))
    monkeypatch.setenv("SECURITY_VLM_API_KEY", "test-key")
    settings = VlmSettings()
    result, latency = VlmClient().judge([b"image-one", b"image-two"], settings)
    assert result.model_dump() == RESULT and latency >= 0
    url, request = calls[0]
    assert url == settings.base_url + "/chat/completions"
    assert request["allow_redirects"] is False and request["timeout"] == (5, settings.api_timeout_sec)
    assert request["headers"]["Authorization"] == "Bearer test-key"
    payload = request["json"]
    assert payload["model"] == settings.model and payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    images = payload["messages"][1]["content"][:2]
    assert [base64.b64decode(image["image_url"]["url"].split(",", 1)[1]) for image in images] == [
        b"image-one",
        b"image-two",
    ]


@pytest.mark.parametrize(
    "content",
    [
        '{"compliant":false,',
        "这不是 JSON",
        '说明：{"compliant":false}',
        "<think>还在分析",
        '<think>有分析内容</think>{"compliant":false}',
        '```json\n{"compliant":false}',
        '{"compliant":false}\n额外说明',
        "{}{}",
    ],
)
def test_invalid_model_json_is_not_repaired(content):
    with pytest.raises(VlmError, match="JSON_ERROR.*判定 JSON"):
        parse_completion(completion(content))


@pytest.mark.parametrize("body", ["not json", '{"choices":'])
def test_invalid_http_body_json(body):
    with pytest.raises(VlmError, match="JSON_ERROR.*Chat Completions"):
        parse_completion(body)


@pytest.mark.parametrize("field", ["compliant", "confidence", "reason"])
def test_missing_core_field(field):
    data = {key: value for key, value in RESULT.items() if key != field}
    with pytest.raises(VlmError, match=f"FIELD_ERROR.*{field}.*missing"):
        parse_completion(completion(json.dumps(data)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("compliant", "false"),
        ("compliant", 0),
        ("compliant", None),
        ("confidence", "0.9"),
        ("confidence", True),
        ("confidence", None),
        ("reason", 123),
        ("reason", []),
        ("reason", None),
    ],
)
def test_wrong_core_types_are_not_coerced(field, value):
    with pytest.raises(VlmError, match=f"FIELD_ERROR.*{field}"):
        parse_completion(completion(json.dumps(RESULT | {field: value})))


@pytest.mark.parametrize("data", [[], None, RESULT | {"scene_summary": "不属于当前协议"}])
def test_result_requires_only_current_object_fields(data):
    with pytest.raises(VlmError, match="FIELD_ERROR"):
        parse_completion(completion(json.dumps(data)))


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": {}},
        {"choices": [{"message": {"content": 1}, "finish_reason": "stop"}]},
        {"choices": [{"message": {"content": "{}"}}]},
    ],
)
def test_malformed_chat_completion_fields(body):
    with pytest.raises(VlmError, match="FIELD_ERROR.*Chat Completions"):
        parse_completion(json.dumps(body))


@pytest.mark.parametrize(
    "field,value",
    [
        ("reason", ""),
        ("reason", " \n\t"),
        ("confidence", -0.1),
        ("confidence", 1.1),
        ("confidence", float("nan")),
        ("confidence", float("inf")),
    ],
)
def test_invalid_business_values(field, value):
    with pytest.raises(VlmError, match=f"RESULT_ERROR.*{field}"):
        parse_completion(completion(json.dumps(RESULT | {field: value})))


@pytest.mark.parametrize(
    "content,finish_reason,refusal",
    [
        (json.dumps(RESULT), "length", None),
        (json.dumps(RESULT), "content_filter", None),
        (json.dumps(RESULT), "stop", "拒绝分析"),
        (None, "stop", None),
        ("", "stop", None),
        ("<think>\n</think>\n", "stop", None),
    ],
)
def test_unfinished_refused_or_empty_result_is_not_a_verdict(content, finish_reason, refusal):
    with pytest.raises(VlmError, match="RESULT_ERROR"):
        parse_completion(completion(content, finish_reason=finish_reason, refusal=refusal))


@pytest.mark.parametrize("status", [302, 401, 500, 503])
def test_http_status_precedes_body_parsing(model_http, status):
    model_http("<html>upstream error</html>", status)
    with pytest.raises(VlmError, match=f"HTTP_ERROR.*HTTP {status}"):
        VlmClient().judge([b"one", b"two"], VlmSettings())


@pytest.mark.parametrize("exception", [requests.ConnectionError, requests.Timeout])
def test_transport_error_category(monkeypatch, exception):
    def post(*args, **kwargs):
        raise exception("request detail")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(VlmError, match=f"HTTP_ERROR.*{exception.__name__}"):
        VlmClient().judge([b"one", b"two"], VlmSettings())


@pytest.mark.parametrize(
    "body,status,category",
    [
        ("upstream unavailable", 503, "HTTP_ERROR"),
        (completion("not json"), 200, "JSON_ERROR"),
        (completion(json.dumps({"reason": "private image description"})), 200, "FIELD_ERROR"),
        (completion(json.dumps(RESULT | {"confidence": 2})), 200, "RESULT_ERROR"),
    ],
)
def test_contract_errors_log_record_and_open_circuit_without_alarm(
    model_http,
    monkeypatch,
    caplog,
    inspection_alarms,
    body,
    status,
    category,
):
    instance, dispatcher, alarms, saved, frames = inspection_alarms
    calls = model_http(body, status)
    monkeypatch.setattr(VlmClient, "check_health", lambda *_: VlmHealth(reachable=True))
    runtime = InspectionRuntime(instance._complete)
    runtime.start(VlmSettings(max_concurrent=1))
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        for index in range(3):
            runtime.submit(task(session_id=f"bad-{index}", frames=frames))
            wait_for(lambda: runtime.status("general_electric")["active"] == 0 and len(saved) == index + 1)
        health = runtime.health_status()
        assert health.circuit_state == "open" and health.consecutive_failures == 3
        assert category in health.last_error and health.last_success is None
        assert "private" not in health.last_error and "private" not in caplog.text
        assert len(calls) == 3 and not alarms and dispatcher._wechat_queue.empty()
        assert all(row[1] == "error" and row[2] is None and category in row[3] for row in saved)
        assert category in caplog.text and "session=bad-0" in caplog.text
        runtime.submit(task(session_id="circuit-open", frames=frames))
        assert len(calls) == 3 and runtime.status("general_electric")["queue"] == 0
    finally:
        runtime.stop()


def test_current_contract_reaches_history_api_and_shared_alarm(model_http, monkeypatch, inspection_alarms, tmp_path):
    instance, dispatcher, alarms, _, frames = inspection_alarms
    engine = create_engine(f"sqlite:///{tmp_path / 'inspection.db'}")
    for model in (AiCameraConfig, InspectionSession):
        model.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "get_session", factory)
    monkeypatch.setattr(service_module, "session_scope", factory.begin)
    instance.service = InspectionService()
    monkeypatch.setattr(VlmClient, "check_health", lambda *_: VlmHealth(reachable=True))
    runtime = InspectionRuntime(instance._complete)
    runtime.start(VlmSettings(max_concurrent=1))
    try:
        wait_for(lambda: runtime.health_status().reachable is True)
        for index, compliant in enumerate((True, False)):
            model_http(completion("<think>\n\n</think>\n" + json.dumps(RESULT | {"compliant": compliant})))
            runtime.submit(task(session_id=f"valid-{index}", frames=frames))
            wait_for(
                lambda: (
                    len(
                        instance.service.history(
                            "general_electric",
                            camera_id=None,
                            limit=10,
                            offset=0,
                        )["items"]
                    )
                    == index + 1
                    and runtime.status("general_electric")["active"] == 0
                )
            )
        assert runtime.health_status().last_success is not None
        model_http(completion('{"compliant":'))
        runtime.submit(task(session_id="invalid", frames=frames))
        wait_for(
            lambda: (
                runtime.health_status().consecutive_failures == 1 and runtime.status("general_electric")["active"] == 0
            )
        )
    finally:
        runtime.stop()
    assert len(alarms) == 1 and alarms[0]["event_metadata"]["verdict"] == RESULT
    assert dispatcher._wechat_queue.qsize() == 1
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    app.dependency_overrides[api.get_service] = lambda: instance.service
    with TestClient(app) as client:
        response = client.get("/api/security-inspection/history?department=general_electric")
    assert response.status_code == 200
    history = response.json()
    assert history["stats"] == {
        "total": 3,
        "compliant": 1,
        "non_compliant": 1,
        "error": 1,
        "cancelled": 0,
        "rate": 50.0,
    }
    rows = {row["status"]: row for row in history["items"]}
    assert rows["non_compliant"]["verdict"] == RESULT
    assert rows["compliant"]["verdict"] == RESULT | {"compliant": True}
    assert rows["error"]["verdict"] is None and "JSON_ERROR" in rows["error"]["error"]
    engine.dispose()
