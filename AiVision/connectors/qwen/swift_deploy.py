#!/usr/bin/env python3
"""为指定版本的 Swift/vLLM 部署提供严格格式约束，可独立复制到模型服务器。"""

import asyncio
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from importlib.metadata import version
import json
import logging
import sys
from typing import Annotated, Any, Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


SUPPORTED_VERSIONS = {"ms-swift": "4.4.2", "vllm": "0.27.1"}
logger = logging.getLogger("fuda.model_serving")


class FormatModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class TextFormat(FormatModel):
    type: Literal["text"]


class ObjectFormat(FormatModel):
    type: Literal["json_object"]


class SchemaDefinition(FormatModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = None
    schema_definition: dict[str, Any] = Field(alias="schema")
    strict: bool = True

    @field_validator("schema_definition")
    @classmethod
    def validate_schema(cls, value):
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError:
            # jsonschema 的原始异常包含 Schema 全文，不能进入响应或日志。
            raise ValueError("response_format 中的 JSON Schema 无效") from None
        return value


class SchemaFormat(FormatModel):
    type: Literal["json_schema"]
    json_schema: SchemaDefinition


ResponseFormat = Annotated[TextFormat | ObjectFormat | SchemaFormat, Field(discriminator="type")]


class SafeRequestInfo(dict):
    """上游后处理仍负责响应转换和计数，但日志与 JSONL 不保留对话正文。"""

    def __setitem__(self, key, value):
        super().__setitem__(key, "[已脱敏]" if key == "response" else value)


async def validation_error(_request, exc):
    # 默认 FastAPI 错误包含 input 和 ctx，可能连同密码、Schema 常量一起返回。
    return JSONResponse(status_code=422, content={
        "object": "error", "message": "请求参数校验失败",
        "errors": [{"type": error["type"]} for error in exc.errors()],
    })


def requested_port(argv: Sequence[str]) -> int:
    values = list(argv)
    for index, value in enumerate(values):
        if value == "--port":
            if index + 1 >= len(values):
                raise ValueError("--port 缺少端口值")
            raw_port = values[index + 1]
            break
        if value.startswith("--port="):
            raw_port = value.split("=", 1)[1]
            break
    else:
        raise ValueError("必须显式指定 --port")
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError("--port 必须是整数") from None
    if not 1 <= port <= 65535:
        raise ValueError("--port 超出有效范围")
    return port


def build_deploy_class(base_deploy, base_request, structured_outputs, adapter_request, fixed_port):
    """仅扩展 HTTP 请求和单次生成钩子，不替换 Swift 模板、模型或调度器。"""

    @dataclass
    class StructuredChatCompletionRequest(base_request):
        __pydantic_config__ = ConfigDict(extra="forbid", hide_input_in_errors=True)
        response_format: ResponseFormat | None = None

    class FixedPortSwiftDeploy(base_deploy):
        def _register_app(self):
            self.app.add_exception_handler(RequestValidationError, validation_error)
            super()._register_app()

        async def create_chat_completion(self, request: StructuredChatCompletionRequest, raw_request: Request,
                                         *, return_cmpl_response: bool = False):
            # 沿用上游的模型、鉴权、logprobs 校验，错误中不回显请求值。
            if (await self._check_model(request) or self._check_api_key(raw_request)
                    or self._check_max_logprobs(request)):
                return self.create_error_response(400, "模型、鉴权或 logprobs 校验未通过")
            try:
                infer_request, request_config = request.parse()
                self._set_request_config(request_config)
                response_format = getattr(request, "response_format", None)
                constrained = isinstance(response_format, (ObjectFormat, SchemaFormat))
                if constrained and (self.args.infer_backend != "vllm" or not self.infer_engine.use_async_engine):
                    return self.create_error_response(400, "格式约束需要 vLLM 异步推理后端")
                if constrained and request_config.structured_outputs_regex:
                    return self.create_error_response(400, "response_format 与正则约束不能同时指定")
                infer_kwargs = self.infer_kwargs.copy()
                adapter_path = self.args.adapter_mapping.get(request.model)
                if adapter_path:
                    infer_kwargs["adapter_request"] = adapter_request(request.model, adapter_path)

                applied = False
                if constrained:
                    constraint = (structured_outputs(json=deepcopy(response_format.json_schema.schema_definition))
                                  if isinstance(response_format, SchemaFormat) else structured_outputs(json_object=True))
                    previous_hook = infer_kwargs.get("pre_infer_hook")

                    def attach_constraint(options):
                        nonlocal applied
                        if previous_hook:
                            options = previous_hook(options)
                        params = options["generation_config"]
                        if not hasattr(params, "structured_outputs"):
                            raise RuntimeError("推理后端缺少 structured_outputs")
                        if params.structured_outputs is not None:
                            raise ValueError("生成参数中已有格式约束")
                        # 只修改本次生成参数，完整保留 Schema，不转正则或放宽字段。
                        params.structured_outputs = constraint
                        applied = True
                        return options

                    infer_kwargs["pre_infer_hook"] = attach_constraint

                response = await self.infer_async(infer_request, request_config, **infer_kwargs)
                if constrained and not applied:
                    raise RuntimeError("推理后端未执行格式约束钩子")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("模型生成失败 type=%s", type(exc).__name__)
                return self.create_error_response(400 if isinstance(exc, ValueError) else 500,
                                                  "模型生成失败，请检查服务端错误类型和格式约束支持")

            # 不调用上游创建请求信息的流程，以免把完整输入、输出和 Schema 写入日志。
            request_info = SafeRequestInfo(response="", request_type="chat_completion")
            if request_config.stream:
                async def stream_response():
                    try:
                        async for item in response:
                            item = self._post_process(request_info, item, return_cmpl_response)
                            yield f"data: {json.dumps(asdict(item), ensure_ascii=False)}\n\n"
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning("模型流式生成失败 type=%s", type(exc).__name__)
                        yield 'data: {"object":"error","message":"模型流式生成失败"}\n\n'
                        return
                    yield "data: [DONE]\n\n"
                return StreamingResponse(stream_response(), media_type="text/event-stream")
            if hasattr(response, "choices"):
                try:
                    return self._post_process(request_info, response, return_cmpl_response)
                except Exception as exc:
                    logger.warning("模型响应处理失败 type=%s", type(exc).__name__)
                    return self.create_error_response(500, "模型响应处理失败")
            return response

        def run(self):
            parsed_port = self.args.port
            self.args.port = fixed_port
            print(f"[FudaAI] Swift 部署端口锁定 requested={fixed_port} parsed_before_run={parsed_port}", flush=True)
            return super().run()

    return FixedPortSwiftDeploy


def load_deploy_class(fixed_port):
    installed = {name: version(name) for name in SUPPORTED_VERSIONS}
    if installed != SUPPORTED_VERSIONS:
        raise RuntimeError("部署入口仅适配 ms-swift 4.4.2 和 vLLM 0.27.1，请先核对版本")
    from swift.infer_engine import AdapterRequest
    from swift.infer_engine.protocol import ChatCompletionRequest
    from swift.pipelines.infer.deploy import SwiftDeploy
    from vllm import SamplingParams
    from vllm.sampling_params import StructuredOutputsParams

    if not hasattr(SamplingParams, "structured_outputs"):
        raise RuntimeError("vLLM 缺少 structured_outputs，拒绝忽略格式约束")
    deploy_class = build_deploy_class(SwiftDeploy, ChatCompletionRequest, StructuredOutputsParams, AdapterRequest, fixed_port)
    # 在加载模型前检查真实 SDK 的请求类型能否构建协议，避免启动到一半才发现类型不兼容。
    request_type = deploy_class.create_chat_completion.__annotations__["request"]
    document = TypeAdapter(request_type).json_schema()
    if "response_format" not in document.get("properties", {}):
        raise RuntimeError("部署请求未声明 response_format，拒绝忽略格式约束")
    return deploy_class


def main(argv: Sequence[str] | None = None) -> None:
    deploy_argv = list(sys.argv[1:] if argv is None else argv)
    if deploy_argv == ["--check"]:
        load_deploy_class(None)
        print("部署依赖检查通过：ms-swift 4.4.2，vLLM 0.27.1，支持 structured_outputs；未加载模型")
        return
    fixed_port = requested_port(deploy_argv)
    load_deploy_class(fixed_port)(deploy_argv).main()


if __name__ == "__main__":
    main()
