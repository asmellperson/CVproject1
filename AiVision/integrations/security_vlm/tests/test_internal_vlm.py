"""验证内部千问的实际图片请求、故障处理和结果协议。"""
import base64
import json

import cv2
import numpy as np
import pytest
import requests

from AiVision.integrations.security_vlm.src.vlm_worker import BudgetGuard, VLMJudge


@pytest.fixture
def judge(tmp_path, monkeypatch):
    for key in ("SECURITY_VLM_BASE_URL", "SECURITY_VLM_MODEL", "SECURITY_VLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    return VLMJudge(
        {"vlm": {"base_url": "http://internal-model:18100/v1", "model": "fuda-qwen36-27b", "image_max_side": 32}},
        BudgetGuard(50, 0), tmp_path,
    )


class Response:
    def __init__(self, payload, status_code=200):
        self.payload, self.status_code = payload, status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def json(self):
        return self.payload


def run_judge(judge, frames=None):
    return judge.judge(
        "session-1", "security_staff_1", [0, 0, 10, 10],
        frames if frames is not None else [np.zeros((10, 10, 3), dtype=np.uint8)],
        department="electrical_components",
    )


def test_multiple_frames_are_transferred_in_order_and_usage_is_normalized(judge, monkeypatch):
    captured = {}
    verdict = {"compliant": False, "confidence": 0.9, "reason": "只有一人"}

    def post(url, **kwargs):
        captured.update(kwargs)
        return Response({
            "choices": [{"message": {"content": json.dumps(verdict)}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        })

    monkeypatch.setattr(requests, "post", post)
    result = run_judge(judge, [np.zeros((60, 120, 3), dtype=np.uint8), np.full((60, 120, 3), 255, dtype=np.uint8)])
    for key, value in verdict.items():
        assert result[key] == value
    assert result["_usage"] == {"input_tokens": 120, "output_tokens": 30}
    body = captured["json"]
    content = body["messages"][1]["content"]
    for item, expected in zip(content[:2], (0, 255)):
        data = base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape == (16, 32, 3)
        assert decoded.mean() == pytest.approx(expected, abs=1)
    assert "2 张" in content[-1]["text"]
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert body["stream"] is False
    assert captured["allow_redirects"] is False
    assert "Authorization" not in captured["headers"]


def test_environment_overrides_endpoint_model_and_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SECURITY_VLM_BASE_URL", "http://private-model:8000/v1/")
    monkeypatch.setenv("SECURITY_VLM_MODEL", "private-qwen")
    monkeypatch.setenv("SECURITY_VLM_API_KEY", "test-only-key")
    judge = VLMJudge({"vlm": {}}, BudgetGuard(50, 0), tmp_path)

    def post(url, **kwargs):
        assert url == "http://private-model:8000/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-only-key"
        assert kwargs["json"]["model"] == "private-qwen"
        return Response({"choices": [{"message": {"content": [{"type": "text", "text": '{"compliant":true}'}]}}]})

    monkeypatch.setattr(requests, "post", post)
    assert run_judge(judge)["compliant"] is True


@pytest.mark.parametrize("status", [302, 401, 404, 429, 500])
def test_http_failure_is_recorded_without_fallback(judge, monkeypatch, status):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return Response({"error": "upstream failure"}, status)

    monkeypatch.setattr(requests, "post", post)
    assert run_judge(judge)["error"] == f"api_error: HTTP {status}"
    assert len(calls) == 1


@pytest.mark.parametrize("exception,error", [(requests.Timeout, "api_timeout"), (requests.ConnectionError, "api_connection_failed")])
def test_transport_failure_is_recorded(judge, monkeypatch, exception, error):
    def post(*_args, **_kwargs):
        raise exception("test transport error")

    monkeypatch.setattr(requests, "post", post)
    assert run_judge(judge)["error"] == error


@pytest.mark.parametrize("content", [None, "", "not JSON", "[]", "null"])
def test_invalid_model_text_cannot_be_a_verdict(judge, monkeypatch, content):
    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: Response({"choices": [{"message": {"content": content}}]}))
    assert run_judge(judge)["error"] == "parse_failed"


def test_empty_frames_and_exhausted_budget_do_not_call_model(judge, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("不应发送图片请求")

    monkeypatch.setattr(requests, "post", forbidden)
    assert run_judge(judge, [])["error"] == "no_keyframes"
    judge.budget = BudgetGuard(0, 1)
    assert run_judge(judge)["error"] == "budget_exceeded"


def test_internal_model_keeps_counting_after_previous_cloud_budget_is_exhausted():
    budget = BudgetGuard(0, 0)
    budget.spent = 50
    assert budget.try_consume() is True
    assert budget.snapshot()["spent_yuan"] == 50
    assert budget.snapshot()["call_count"] == 1
