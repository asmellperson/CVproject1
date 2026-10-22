"""只读识别模型服务及请求合同，不导入模型、执行启动命令或保存原始响应。"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, ConfigDict

from .sandbox import json_validity, response_statistics


MAX_METADATA_BYTES = 2 * 1024 * 1024
PRODUCTS = ("vllm", "sglang", "llama.cpp", "llama-cpp-python", "ollama", "text-generation-inference",
            "xinference", "uvicorn", "gunicorn", "nginx", "transformers")
PACKAGES = ("vllm", "sglang", "transformers", "llama_cpp_python", "fastapi", "uvicorn", "xgrammar", "outlines")
REQUEST_FIELDS = {"model", "messages", "max_tokens", "temperature", "top_p", "response_format",
                  "structured_outputs", "guided_json", "chat_template_kwargs", "reasoning_effort"}
SOURCE_SIGNALS = ("response_format", "structured_outputs", "guided_json", "logits_processor",
                  "prefix_allowed_tokens_fn", "chat_template_kwargs", "enable_thinking", "max_tokens",
                  "max_new_tokens", "generate(", "transformers", "vllm")


class ProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    probe: Literal["schema_ok"]


def product_hints(value):
    return [name for name in PRODUCTS if isinstance(value, str) and name in value.lower()]


def safe_version(value):
    return value if isinstance(value, str) and re.fullmatch(r"[vb]?\d[0-9A-Za-z.+_-]{0,79}", value) else None


def openapi_contract(document):
    """只提取声明字段和额外字段策略，不能将字段声明当作真实透传证据。"""
    result = {"chat_completions_found": False, "declared_fields": [], "extra_fields_policy": "unspecified"}
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        return result
    route = next((value for name, value in paths.items() if name.endswith("/chat/completions") and isinstance(value, dict)), {})
    operation = route.get("post", {})
    if not isinstance(operation, dict):
        return result
    seen, fields, policies = set(), set(), set()

    def visit(node, depth=0):
        if not isinstance(node, dict) or depth > 16:
            return
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/") and reference not in seen:
            seen.add(reference)
            target = document
            for part in reference[2:].split("/"):
                target = target.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(target, dict) else {}
            visit(target, depth + 1)
        properties = node.get("properties", {})
        if isinstance(properties, dict):
            fields.update(REQUEST_FIELDS & properties.keys())
        if type(node.get("additionalProperties")) is bool:
            policies.add("allow" if node["additionalProperties"] else "forbid")
        for name in ("allOf", "anyOf", "oneOf"):
            for child in node.get(name, []) if isinstance(node.get(name), list) else ():
                visit(child, depth + 1)
        for name in ("requestBody", "schema"):
            visit(node.get(name), depth + 1)
        content = node.get("content", {})
        if isinstance(content, dict):
            visit(content.get("application/json"), depth + 1)

    visit(operation)
    result.update(chat_completions_found=bool(operation), declared_fields=sorted(fields),
                  extra_fields_policy=next(iter(policies)) if len(policies) == 1 else "mixed" if policies else "unspecified")
    return result


def process_details(pid, proc_root=Path("/proc")):
    result = {"pid": pid}
    process = proc_root / str(pid)
    try:
        arguments = process.joinpath("cmdline").read_bytes()[:32768].decode("utf-8", errors="replace").split("\0")
        executable = process.joinpath("exe").readlink()
        result["executable_name"] = executable.name if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", executable.name) else "other"
        position = 1
        while position < len(arguments) and arguments[position] in {"-u", "-B", "-E", "-I", "-s", "-S", "-O", "-OO", "-q"}:
            position += 1
        is_module = position + 1 < len(arguments) and arguments[position] == "-m"
        module = arguments[position + 1] if is_module else ""
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,119}", module):
            result["python_module"] = module
        # 命令行可能含 API 密钥；只检查程序入口，绝不输出完整命令或未知参数值。
        script = arguments[position] if position < len(arguments) and arguments[position].endswith(".py") else None
        launcher = Path(arguments[position]).name if position < len(arguments) else ""
        result["product_hints"] = product_hints(str(executable) + " " + module + " " + launcher)
        command = position + 2 if is_module else position + 1
        if ("uvicorn" in result["product_hints"] or "gunicorn" in result["product_hints"]) and command < len(arguments):
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,99}:[A-Za-z_][A-Za-z0-9_]{0,39}", arguments[command]):
                result["asgi_application"] = arguments[command]
        if script:
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}\.py", Path(script).name):
                result["entrypoint_name"] = Path(script).name
            path = process / "root" / script.lstrip("/") if script.startswith("/") else process / "cwd" / script
            try:
                with path.open("rb") as stream:
                    source = stream.read(MAX_METADATA_BYTES + 1)
                if len(source) <= MAX_METADATA_BYTES:
                    result["entrypoint_sha256"] = hashlib.sha256(source).hexdigest()
                    text = source.decode("utf-8", errors="replace")
                    result["source_signals"] = {key: key in text for key in SOURCE_SIGNALS}
                    result["product_hints"] = sorted(set(result["product_hints"]) | set(product_hints(text)))
                else:
                    result["source_error"] = "FileTooLarge"
            except OSError as exc:
                result["source_error"] = type(exc).__name__
        result["decoding_flags_present"] = [name for name in (
            "--structured-outputs-config", "--structured-outputs-config.backend", "--guided-decoding-backend",
            "--reasoning-parser", "--grammar",
        ) if any(argument == name or argument.startswith(name + "=") for argument in arguments)]
        backends = set()
        for index, argument in enumerate(arguments):
            flag, separator, value = argument.partition("=")
            if flag not in {"--structured-outputs-config", "--structured-outputs-config.backend", "--guided-decoding-backend"}:
                continue
            if not separator:
                value = arguments[index + 1] if index + 1 < len(arguments) else ""
            if flag == "--structured-outputs-config":
                try:
                    config = json.loads(value)
                    value = config.get("backend") if isinstance(config, dict) else None
                except ValueError:
                    value = None
            if isinstance(value, str) and value in {"auto", "xgrammar", "guidance", "outlines", "lm-format-enforcer"}:
                backends.add(value)
        result["decoding_backend_hints"] = sorted(backends)
        versions = {}
        prefixes = {executable.parent.parent}
        if arguments[0].startswith("/"):
            prefixes.add(Path(arguments[0]).parent.parent)
        for prefix in prefixes:
            environment = process / "root" / str(prefix).lstrip("/")
            for library in environment.glob("lib/python*/site-packages"):
                for package in PACKAGES:
                    for metadata in library.glob(package + "-*.dist-info/METADATA"):
                        with metadata.open("rb") as stream:
                            text = stream.read(65536).decode("utf-8", errors="replace")
                        match = re.search(r"^Version: (.+)$", text, re.MULTILINE)
                        version = safe_version(match[1]) if match else None
                        if version:
                            versions.setdefault(package, set()).add(version)
        result["installed_package_versions"] = {name: sorted(values) for name, values in versions.items()}
    except OSError as exc:
        result["inspection_error"] = type(exc).__name__
    return result


def local_listener(base_url):
    address = urlsplit(base_url)
    if address.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return {"status": "not_local", "processes": []}
    port = address.port or (443 if address.scheme == "https" else 80)
    try:
        command = subprocess.run(["ss", "-H", "-ltnp", f"sport = :{port}"], capture_output=True, text=True, timeout=5, check=True)
        if "Operation not permitted" in command.stderr:
            return {"status": "unavailable", "error_type": "PermissionError", "processes": []}
        pids = sorted({int(value) for value in re.findall(r"pid=(\d+)", command.stdout)})[:8]
        return {"status": "found" if pids else "not_found" if not command.stdout.strip() else "pid_unavailable",
                "processes": [process_details(pid) for pid in pids]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__, "processes": []}


def service_metadata(settings):
    from AiVision.connectors.qwen.client import model_headers

    base = settings["base_url"].rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    result = {"listener": local_listener(base), "endpoints": {}}
    endpoints = {"version": root + "/version", "ollama_version": root + "/api/version", "info": root + "/info",
                 "props": root + "/props", "openapi": root + "/openapi.json", "models": base + "/models"}
    with requests.Session() as transport:
        transport.trust_env = False
        for name, url in endpoints.items():
            entry = result["endpoints"][name] = {}
            try:
                with transport.get(url, headers=model_headers(), timeout=min(5.0, settings["timeout"]),
                                   allow_redirects=False, stream=True) as response:
                    entry["http_status"] = response.status_code
                    entry["http_server_hints"] = product_hints(response.headers.get("Server", ""))
                    if response.status_code != 200:
                        continue
                    chunks, length = [], 0
                    for chunk in response.iter_content(chunk_size=65536):
                        length += len(chunk)
                        if length > MAX_METADATA_BYTES:
                            raise ValueError("metadata_too_large")
                        chunks.append(chunk)
                    document = json.loads(b"".join(chunks))
                if not isinstance(document, dict):
                    raise ValueError("metadata_not_object")
                entry["versions"] = {key: value for key in ("version", "build_version", "build_info")
                                     if (value := safe_version(document.get(key))) is not None}
                if name == "openapi":
                    info = document.get("info") if isinstance(document.get("info"), dict) else {}
                    entry["application_version"] = safe_version(info.get("version"))
                    entry["product_hints"] = product_hints(info.get("title"))
                    entry["request_contract"] = openapi_contract(document)
                if name == "models":
                    models = document.get("data", [])
                    entry["requested_model_listed"] = any(isinstance(item, dict) and item.get("id") == settings["model"]
                                                          for item in models) if isinstance(models, list) else None
                    entry["owner_hints"] = sorted({hint for item in models if isinstance(item, dict)
                                                   for hint in product_hints(item.get("owned_by"))}) if isinstance(models, list) else []
            except (requests.RequestException, ValueError, OSError) as exc:
                entry["error_type"] = type(exc).__name__
    return result


def run_service_probes(settings, repeats, record, progress):
    from AiVision.assistant.responses import completion_content, json_content
    from AiVision.connectors.qwen.client import QwenClient, QwenError

    schema = ProbeResult.model_json_schema()
    conflict = [{"role": "user", "content": "只输出一句普通文本：格式探针完成。不要输出 JSON 或代码块。"}]
    counting = [{"role": "user", "content": "依次输出英文单词 one two three four five six seven eight nine ten，用空格隔开。"}]
    cases = (
        ("json_object_conflict", conflict, True, None, 128),
        ("json_schema_conflict", conflict, True, schema, 128),
        ("invalid_schema_rejection", conflict, True, {"type": "assistant_diagnostic_invalid_type"}, 128),
        ("max_tokens_control", counting, False, None, 128),
        ("max_tokens_one", counting, False, None, 1),
    )
    client = QwenClient()
    for repeat in range(1, repeats + 1):
        control_tokens = None
        for name, messages, json_mode, response_schema, limit in cases:
            row = {"scenario": name, "label": name, "repeat": repeat, "model_calls": 1, "real_model_calls": 1,
                   "behavior_ok": False, "json_ok": [], "errors": [], "failure_layers": [], "probe_status": "inconclusive",
                   "requested_max_tokens": limit, "requested_response_format": "json_schema" if response_schema else "json_object" if json_mode else "text"}
            started = time.perf_counter()
            try:
                raw, _ = client.complete(base_url=settings["base_url"], model=settings["model"], messages=messages,
                    max_tokens=limit, temperature=0.0, timeout=settings["timeout"], json_mode=json_mode, response_schema=response_schema)
                metadata = row["response_metadata"] = response_statistics(raw)
                row["http_status"] = 200
                if json_mode:
                    valid = json_validity(raw)
                    row["json_ok"] = [valid] if valid is not None else []
                if name == "invalid_schema_rejection":
                    row.update(behavior_ok=False, probe_status="failed", schema_rejection_ok=False)
                elif name == "json_object_conflict":
                    row["behavior_ok"] = bool(row["json_ok"] == [True] and isinstance(json.loads(json_content(completion_content(raw))), dict))
                    row["probe_status"] = "passed" if row["behavior_ok"] else "failed"
                elif name == "json_schema_conflict":
                    ProbeResult.model_validate_json(json_content(completion_content(raw)))
                    row.update(behavior_ok=True, probe_status="passed", schema_output_ok=True)
                elif name == "max_tokens_control":
                    control_tokens = metadata.get("completion_tokens") if metadata.get("finish_reason") in {"stop", "length"} else None
                    if type(control_tokens) is int:
                        row.update(behavior_ok=control_tokens > 1, probe_status="passed" if control_tokens > 1 else "inconclusive")
                else:
                    tokens = metadata.get("completion_tokens") if metadata.get("finish_reason") in {"stop", "length"} else None
                    if type(tokens) is int and tokens > 1:
                        row.update(probe_status="failed", max_tokens_ok=False)
                    elif type(tokens) is int and type(control_tokens) is int and control_tokens > 1:
                        row.update(behavior_ok=True, probe_status="passed", max_tokens_ok=True)
            except QwenError as exc:
                status = re.search(r"HTTP (\d{3})", str(exc))
                row["http_status"] = int(status[1]) if status else None
                row["errors"] = [type(exc).__name__]
                if name == "invalid_schema_rejection" and row["http_status"] in {400, 422}:
                    row.update(behavior_ok=True, probe_status="passed", schema_rejection_ok=True)
                else:
                    row["failure_layers"] = ["model_service"]
            except (ValueError, TypeError) as exc:
                row.update(probe_status="failed", errors=[type(exc).__name__], schema_output_ok=False)
            if row["probe_status"] == "failed":
                row["failure_layers"] = ["service_contract"]
            row["duration_seconds"] = round(time.perf_counter() - started, 6)
            record(row)
            progress(f"[service] {name} {repeat}/{repeats}: {row['probe_status']}")
