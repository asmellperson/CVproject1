"""部署协议的 HTTP、请求隔离和参数传递回归；不加载权重或连接业务数据库。"""

import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
import logging
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest

from AiVision.connectors.qwen import swift_deploy as deploy


@dataclass
class InferRequest:
    messages: list
    chat_template_kwargs: dict = field(default_factory=dict)


@dataclass
class RequestConfig:
    max_tokens: int = 128
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int | None = None
    stop: list = field(default_factory=list)
    stream: bool = False
    structured_outputs_regex: str | None = None


@dataclass
class ChatRequest(RequestConfig):
    model: str = "fixture-model"
    messages: list = field(default_factory=list)
    chat_template_kwargs: dict = field(default_factory=dict)

    def parse(self):
        # 模拟 Swift 按 dataclass 字段筛选的真实边界，额外格式字段会在这里丢失。
        values = asdict(self)
        return tuple(cls(**{key: value for key, value in values.items() if key in {f.name for f in fields(cls)}})
                     for cls in (InferRequest, RequestConfig))


@dataclass
class Constraint:
    json: dict | None = None
    json_object: bool | None = None


@dataclass
class Message:
    content: str


@dataclass
class Choice:
    message: Message
    finish_reason: str = "stop"


@dataclass
class Response:
    choices: list[Choice]


@dataclass
class StreamChoice:
    delta: Message
    finish_reason: str | None = None


@dataclass
class ChatCompletionStreamResponse:
    choices: list[StreamChoice]


class Engine:
    use_async_engine = True

    def __init__(self):
        self.calls = []
        self.error = None
        self.ignore_hook = False
        self.missing_field = False
        self.existing_constraint = None
        self.release = None
        self.started = None

    async def infer_async(self, request, config, **kwargs):
        await asyncio.sleep(0)
        params = SimpleNamespace(**asdict(config))
        if not self.missing_field:
            params.structured_outputs = self.existing_constraint
        options = {"generation_config": params, "request_config": config, "inputs": request,
                   "adapter_request": kwargs.get("adapter_request")}
        if not self.ignore_hook and (hook := kwargs.get("pre_infer_hook")):
            options = hook(options)
        self.calls.append(options)
        if self.started:
            self.started.set()
        if self.release:
            await self.release.wait()
        if self.error:
            raise self.error
        if config.stream:
            async def stream():
                yield ChatCompletionStreamResponse([StreamChoice(Message("fixture-private-response"))])
                yield ChatCompletionStreamResponse([StreamChoice(Message(""), "stop")])
            return stream()
        return Response([Choice(Message("fixture-private-response"))])


class SwiftDeploy:
    def __init__(self):
        self.args = SimpleNamespace(port=18200, infer_backend="vllm", adapter_mapping={},
                                    verbose=True, log_interval=20)
        self.infer_kwargs = {}
        self.infer_engine = Engine()
        self.jsonl_writer = Mock()
        self.infer_stats = Mock()
        self.default_regex = None
        self.model_check = None
        self.logprobs_check = None
        self.require_auth = False
        self.app = FastAPI()
        self._register_app()

    def _register_app(self):
        self.app.post("/v1/chat/completions")(self.create_chat_completion)

    async def _check_model(self, _request):
        return self.model_check

    def _check_api_key(self, request):
        return "denied" if self.require_auth and request.headers.get("Authorization") != "Bearer fixture-only" else None

    def _check_max_logprobs(self, _request):
        return self.logprobs_check

    def _set_request_config(self, config):
        if self.default_regex:
            config.structured_outputs_regex = self.default_regex

    def create_error_response(self, status, message):
        return deploy.JSONResponse(status_code=status, content={"object": "error", "message": message})

    async def infer_async(self, *args, **kwargs):
        return await self.infer_engine.infer_async(*args, **kwargs)

    def _post_process(self, request_info, response, _return_cmpl_response):
        if isinstance(response, ChatCompletionStreamResponse):
            request_info["response"] += response.choices[0].delta.content
        else:
            request_info["response"] = response.choices[0].message.content
        if all(choice.finish_reason for choice in response.choices):
            self.infer_stats.update(response)
            self.jsonl_writer.append(request_info.copy())
            logging.getLogger("fixture.swift").info(request_info)
        return response

    def run(self):
        return self.args.port


@pytest.fixture
def server():
    adapter = Mock(side_effect=lambda name, path: (name, path))
    cls = deploy.build_deploy_class(SwiftDeploy, ChatRequest, Constraint, adapter, 18100)
    instance = cls()
    with TestClient(instance.app) as client:
        yield SimpleNamespace(instance=instance, client=client, engine=instance.infer_engine, adapter=adapter)


def schema_format():
    return {"type": "json_schema", "json_schema": {
        "name": "fixture_plan", "strict": True, "schema": {
            "type": "object", "properties": {"mode": {"$ref": "#/$defs/mode"},
                "threshold": {"type": "number", "minimum": 0, "maximum": 1}},
            "$defs": {"mode": {"type": "string", "enum": ["chat", "query", "change"]}},
            "required": ["mode"], "additionalProperties": False,
        },
    }}


def payload(**kwargs):
    return {"model": "fixture-model", "messages": [{"role": "user", "content": "fixture-private-dialogue"}],
            "chat_template_kwargs": {"enable_thinking": False}, **kwargs}


@pytest.mark.parametrize("args, expected", [(["--port", "18100"], 18100), (["--port=18100"], 18100),
                                          (["--port", "1"], 1), (["--port=65535"], 65535)])
def test_explicit_port_forms_are_preserved(args, expected):
    assert deploy.requested_port(args) == expected


@pytest.mark.parametrize("args", [[], ["--port"], ["--port", "0"], ["--port=65536"],
                                  ["--port=fixture-private-value"]])
def test_invalid_port_errors_do_not_echo_values(args):
    with pytest.raises(ValueError) as caught:
        deploy.requested_port(args)
    assert "fixture-private-value" not in str(caught.value)


def test_port_remains_fixed_when_swift_has_selected_another_port(server):
    assert server.instance.run() == 18100


def test_complete_schema_reaches_sampling_params_without_changing_generation_or_adapter(server):
    requested = schema_format()
    before = deepcopy(requested)
    server.instance.args.adapter_mapping = {"fixture-model": "fixture-adapter"}
    response = server.client.post("/v1/chat/completions", json=payload(
        response_format=requested, max_tokens=1024, temperature=0.2, top_p=0.8, seed=17, stop=["END"]))
    assert response.status_code == 200
    call = server.engine.calls[0]
    params = call["generation_config"]
    assert params.structured_outputs.json == before["json_schema"]["schema"]
    assert params.structured_outputs.json_object is None
    assert (params.max_tokens, params.temperature, params.top_p, params.seed, params.stop) == (1024, 0.2, 0.8, 17, ["END"])
    assert call["inputs"].chat_template_kwargs == {"enable_thinking": False}
    assert call["inputs"].messages == payload()["messages"]
    assert call["adapter_request"] == ("fixture-model", "fixture-adapter")
    assert requested == before
    # 替身只核验传递，不能把它的文本返回伪称为真实模型的 Schema 生成通过。
    assert response.json()["choices"][0]["message"]["content"] == "fixture-private-response"


def test_object_mode_is_a_real_decoder_constraint(server):
    response = server.client.post("/v1/chat/completions", json=payload(response_format={"type": "json_object"}))
    assert response.status_code == 200
    constraint = server.engine.calls[0]["generation_config"].structured_outputs
    assert constraint.json_object is True and constraint.json is None


def test_production_plan_schema_is_forwarded_whole_and_existing_hook_is_preserved(server):
    from AiVision.assistant.schema import RequestPlan

    schema = RequestPlan.model_json_schema()
    requested = schema_format()
    requested["json_schema"]["schema"] = schema
    original_hook = Mock(side_effect=lambda options: options)
    server.instance.infer_kwargs["pre_infer_hook"] = original_hook
    response = server.client.post("/v1/chat/completions", json=payload(response_format=requested))
    assert response.status_code == 200
    original_hook.assert_called_once()
    assert server.instance.infer_kwargs["pre_infer_hook"] is original_hook
    assert server.engine.calls[0]["generation_config"].structured_outputs.json == schema


@pytest.mark.parametrize("fmt", [None, {"type": "text"}])
def test_plain_text_has_no_format_constraint_and_keeps_one_token_budget(server, fmt):
    response = server.client.post("/v1/chat/completions", json=payload(response_format=fmt, max_tokens=1))
    assert response.status_code == 200
    params = server.engine.calls[0]["generation_config"]
    assert params.structured_outputs is None and params.max_tokens == 1


@pytest.mark.parametrize("fmt", [
    {}, {"type": "fixture-private-format"}, {"type": "json_schema"},
    {"type": "json_object", "fixture-private-field": "fixture-private-value"},
    {"type": "json_schema", "json_schema": {"name": "fixture", "schema": {"type": "fixture-private-type"}}},
    {"type": "json_schema", "json_schema": {"name": "fixture", "strict": "false", "schema": {"type": "object"}}},
])
def test_malformed_formats_and_invalid_schemas_are_rejected_without_body_leaks(server, fmt, caplog):
    with caplog.at_level(logging.INFO):
        response = server.client.post("/v1/chat/completions", json=payload(response_format=fmt))
    assert response.status_code == 422 and not server.engine.calls
    assert "fixture-private" not in response.text + caplog.text


def test_invalid_json_and_unknown_root_field_do_not_echo_dialogue(server):
    response = server.client.post("/v1/chat/completions", content='{"messages":"fixture-private-dialogue",',
                                  headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "fixture-private" not in response.text
    response = server.client.post("/v1/chat/completions", json=payload(**{"fixture-private-field": "fixture-private-value"}))
    assert response.status_code == 422 and "fixture-private" not in response.text
    assert not server.engine.calls


@pytest.mark.parametrize("in_defaults", [False, True])
def test_regex_conflict_is_rejected_after_merging_defaults(server, in_defaults):
    arguments = {} if in_defaults else {"structured_outputs_regex": "fixture"}
    if in_defaults:
        server.instance.default_regex = "fixture"
    response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format(), **arguments))
    assert response.status_code == 400 and not server.engine.calls


@pytest.mark.parametrize("guard", ["model", "auth", "logprobs"])
def test_existing_model_auth_and_logprobs_checks_remain_before_inference(server, guard):
    if guard == "model":
        server.instance.model_check = "fixture-private-model"
    elif guard == "auth":
        server.instance.require_auth = True
    else:
        server.instance.logprobs_check = "fixture-private-logprobs"
    response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format()))
    assert response.status_code == 400 and not server.engine.calls
    assert "fixture-private" not in response.text
    if guard == "auth":
        response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format()),
                                      headers={"Authorization": "Bearer fixture-only"})
        assert response.status_code == 200


@pytest.mark.parametrize("error, status", [(ValueError("fixture-private-schema"), 400),
                                           (RuntimeError("fixture-private-dialogue"), 500)])
def test_engine_errors_are_redacted_and_never_retried(server, error, status, caplog):
    server.engine.error = error
    with caplog.at_level(logging.INFO):
        response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format()))
    assert response.status_code == status and len(server.engine.calls) == 1
    assert "fixture-private" not in response.text + caplog.text
    assert type(error).__name__ in caplog.text


@pytest.mark.parametrize("fault", ["backend", "sync", "missing_field", "ignore_hook", "existing_constraint"])
def test_unsupported_backend_and_missing_decoder_contract_fail_without_fallback(server, fault):
    if fault == "backend":
        server.instance.args.infer_backend = "transformers"
    elif fault == "sync":
        server.engine.use_async_engine = False
    elif fault == "existing_constraint":
        server.engine.existing_constraint = Constraint(json_object=True)
    else:
        setattr(server.engine, fault, True)
    response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format()))
    assert response.status_code in {400, 500}
    assert len(server.engine.calls) <= 1


def test_response_statistics_and_jsonl_continue_without_logging_input_or_output(server, caplog):
    with caplog.at_level(logging.INFO):
        response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format()))
    assert response.status_code == 200
    server.instance.infer_stats.update.assert_called_once()
    saved = server.instance.jsonl_writer.append.call_args.args[0]
    assert saved == {"response": "[已脱敏]", "request_type": "chat_completion"}
    assert "fixture-private" not in str(saved) + caplog.text


def test_response_processing_errors_are_redacted(server, monkeypatch, caplog):
    monkeypatch.setattr(server.instance, "_post_process", Mock(side_effect=ValueError("fixture-private-response")))
    with caplog.at_level(logging.INFO):
        response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format()))
    assert response.status_code == 500
    assert "fixture-private" not in response.text + caplog.text


def test_streaming_keeps_decoder_constraint_and_redacts_request_logging(server, caplog):
    with caplog.at_level(logging.INFO):
        response = server.client.post("/v1/chat/completions", json=payload(response_format=schema_format(), stream=True))
    assert response.status_code == 200 and response.text.endswith("data: [DONE]\n\n")
    assert "fixture-private-response" in response.text and "fixture-private" not in caplog.text
    assert server.engine.calls[0]["generation_config"].structured_outputs.json == schema_format()["json_schema"]["schema"]
    saved = server.instance.jsonl_writer.append.call_args.args[0]
    assert "fixture-private" not in str(saved)


def test_concurrent_requests_keep_separate_schemas_and_plain_request_has_no_residue(server):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.instance.app), base_url="http://fixture") as client:
            formats = [schema_format(), schema_format(), None]
            formats[1]["json_schema"]["schema"]["required"] = ["mode", "threshold"]
            responses = await asyncio.gather(*[
                client.post("/v1/chat/completions", json=payload(response_format=fmt)) for fmt in formats])
            assert all(response.status_code == 200 for response in responses)
    asyncio.run(run())
    constraints = [call["generation_config"].structured_outputs for call in server.engine.calls]
    assert constraints[0] is not constraints[1]
    assert constraints[0].json["required"] == ["mode"]
    assert constraints[1].json["required"] == ["mode", "threshold"]
    assert constraints[2] is None


def test_cancellation_propagates_to_awaited_engine_without_retry(server):
    async def run():
        server.engine.started, server.engine.release = asyncio.Event(), asyncio.Event()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.instance.app), base_url="http://fixture") as client:
            task = asyncio.create_task(client.post("/v1/chat/completions", json=payload(response_format=schema_format())))
            await asyncio.wait_for(server.engine.started.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(run())
    assert len(server.engine.calls) == 1
    server.instance.infer_stats.update.assert_not_called()


def test_openapi_declares_response_format_and_schema_definition(server):
    document = server.client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    request = schemas["StructuredChatCompletionRequest"]
    assert "response_format" in request["properties"] and request["additionalProperties"] is False
    assert "schema" in schemas["SchemaDefinition"]["properties"]


def test_schema_validation_exception_does_not_expose_embedded_values():
    with pytest.raises(ValidationError) as caught:
        deploy.SchemaFormat.model_validate({"type": "json_schema", "json_schema": {
            "name": "fixture", "schema": {"type": "fixture-private-type"}}})
    assert "fixture-private" not in str(caught.value)


def test_unexpected_installed_versions_fail_before_importing_model_packages(monkeypatch):
    monkeypatch.setattr(deploy, "version", lambda _name: "0.0.0")
    with pytest.raises(RuntimeError, match="核对版本"):
        deploy.load_deploy_class(18100)


def test_dependency_preflight_builds_the_actual_request_contract_without_an_engine(monkeypatch):
    monkeypatch.setattr(deploy, "version", deploy.SUPPORTED_VERSIONS.__getitem__)
    modules = {
        "swift.infer_engine": SimpleNamespace(AdapterRequest=Mock()),
        "swift.infer_engine.protocol": SimpleNamespace(ChatCompletionRequest=ChatRequest),
        "swift.pipelines.infer.deploy": SimpleNamespace(SwiftDeploy=SwiftDeploy),
        "vllm": SimpleNamespace(SamplingParams=SimpleNamespace(structured_outputs=None)),
        "vllm.sampling_params": SimpleNamespace(StructuredOutputsParams=Constraint),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    constructor = Mock(side_effect=AssertionError("依赖检查不能构建模型引擎"))
    monkeypatch.setattr(SwiftDeploy, "__init__", constructor)
    cls = deploy.load_deploy_class(None)
    request_type = cls.create_chat_completion.__annotations__["request"]
    document = deploy.TypeAdapter(request_type).json_schema()
    assert "response_format" in document["properties"]
    constructor.assert_not_called()


def test_preflight_checks_dependencies_without_initializing_engine_or_starting_server(monkeypatch, capsys):
    loader = Mock()
    monkeypatch.setattr(deploy, "load_deploy_class", loader)
    deploy.main(["--check"])
    loader.assert_called_once_with(None)
    loader.return_value.assert_not_called()
    assert "未加载模型" in capsys.readouterr().out


def test_launch_preserves_all_swift_cli_arguments(monkeypatch):
    loader = Mock()
    monkeypatch.setattr(deploy, "load_deploy_class", loader)
    args = ["--port", "18100", "--infer_backend", "vllm", "--model", "fixture-model"]
    deploy.main(args)
    loader.assert_called_once_with(18100)
    loader.return_value.assert_called_once_with(args)
    loader.return_value.return_value.main.assert_called_once_with()
