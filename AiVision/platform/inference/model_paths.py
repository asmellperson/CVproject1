# 文件说明：实现模型相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""本机模型路径配置。

模型文件路径会随部署服务器变化，不能依赖数据库中的 ai_model.path。
这里按模型 name 读取本机配置文件，作为 worker 实际加载模型时唯一的路径来源。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from AiVision.core.logger import logger
from AiVision.core.settings import settings

try:
    import yaml
except Exception:  # pragma: no cover - 仅在缺少 PyYAML 的环境下触发
    yaml = None


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# 功能：定义 `ModelPathResolution` 类，封装模型相关的状态、约束与操作
# 参数：
#   - `path`（str）：目标路径
#   - `source`（str）：`source` 对应的业务输入值
#   - `database_path`（str）：`database_path` 对应的业务输入值
# 返回：ModelPathResolution；返回新建的 `ModelPathResolution` 实例。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/model_paths.py` 的 `resolve_model_path` 实例化本符号
#   - 内部调用：`dataclass`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@dataclass(frozen=True)
class ModelPathResolution:
    path: str
    source: str
    database_path: str


# 功能：计算或解析 `_resolve_config_path` 对应的模型逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path_value`（str）：`path_value` 对应的业务输入值
# 返回：Path；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/model_paths.py` 的 `load_model_path_overrides` 调用本符号
#   - 内部调用：`Path(path_value).expanduser`、`Path`、`path.is_absolute`、`(_PROJECT_ROOT / path).resolve`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _resolve_config_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return (_PROJECT_ROOT / path).resolve()


# 功能：读取或查询 `_read_config` 对应的模型逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/model_paths.py` 的 `load_model_path_overrides` 调用本符号
#   - 内部调用：`path.exists`、`path.suffix.lower`、`json.loads`、`path.read_text`、`logger.warning`、`yaml.safe_load`、`isinstance`。
# 副作用/注意事项：会向日志系统输出运行或异常信息。
def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            if yaml is None:
                logger.warning(f"[ModelPaths] PyYAML 未安装，无法读取 YAML 配置: {path}")
                return {}
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[ModelPaths] 读取本地模型路径配置失败 {path}: {exc}")
        return {}

    return data if isinstance(data, dict) else {}


# 功能：读取本机模型路径覆盖表，返回 {model_name: path}；输入与输出详见下方说明
# 参数：无。
# 返回：dict[str, str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/model_paths.py` 的 `resolve_model_path` 调用本符号
#   - 内部调用：`_resolve_config_path`、`_read_config`、`raw.get`、`isinstance`、`section.items`、`item.get`、`path_value.strip`、`str`、`logger.info`、`',
#          '.join` 等共 12 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
@lru_cache(maxsize=1)
def load_model_path_overrides() -> dict[str, str]:
    """读取本机模型路径覆盖表，返回 {model_name: path}。"""
    config_path = _resolve_config_path(settings.model_paths.config_path)
    raw = _read_config(config_path)
    section = raw.get("models") or raw.get("model_paths") or raw

    overrides: dict[str, str] = {}
    if not isinstance(section, dict):
        return overrides

    for model_name, item in section.items():
        path_value = item.get("path") if isinstance(item, dict) else item
        if not isinstance(path_value, str):
            continue
        path_value = path_value.strip()
        if path_value:
            overrides[str(model_name)] = path_value

    if overrides:
        logger.info(
            f"[ModelPaths] 已加载本地模型路径配置 {config_path}，覆盖模型: {', '.join(sorted(overrides))}"
        )
    return overrides


# 功能：返回模型实际加载路径；输入与输出详见下方说明
# 参数：
#   - `model_cfg`（dict[str, Any]）：`model_cfg` 对应的业务输入值
# 返回：ModelPathResolution；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/model_paths.py` 的 `apply_model_path_override` 调用本符号；`AiVision/platform/inference/config_manager.py`
#         的 `ModelConfigManager::_to_dict` 调用本符号
#   - 内部调用：`str`、`model_cfg.get`、`load_model_path_overrides().get`、`load_model_path_overrides`、`ModelPathResolution`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def resolve_model_path(model_cfg: dict[str, Any]) -> ModelPathResolution:
    """返回模型实际加载路径。

    只使用本机配置文件中的路径；缺失时不再回退数据库 path。
    """
    name = str(model_cfg.get("name") or "")
    database_path = str(model_cfg.get("path") or "")
    override_path = load_model_path_overrides().get(name)
    if override_path:
        return ModelPathResolution(
            path=override_path,
            source="local_config",
            database_path=database_path,
        )
    return ModelPathResolution(
        path="",
        source="missing_local_config",
        database_path=database_path,
    )


# 功能：复制模型配置，并把 path 替换成 worker 应加载的本机路径；输入与输出详见下方说明
# 参数：
#   - `model_cfg`（dict[str, Any]）：`model_cfg` 对应的业务输入值
# 返回：dict[str, Any]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/platform/inference/base_worker.py` 的 `BaseModelWorker::__init__` 调用本符号
#   - 内部调用：`resolve_model_path`、`str`、`model_cfg.get`、`RuntimeError`、`dict`。
# 副作用/注意事项：校验或执行失败时会主动抛出异常。
def apply_model_path_override(model_cfg: dict[str, Any]) -> dict[str, Any]:
    """复制模型配置，并把 path 替换成 worker 应加载的本机路径。"""
    resolution = resolve_model_path(model_cfg)
    if not resolution.path:
        name = str(model_cfg.get("name") or "<unknown>")
        raise RuntimeError(
            f"模型 {name} 未在本机模型路径配置中设置 path；"
            f"请检查 MODEL_PATHS_CONFIG 指向的配置文件。"
        )
    next_cfg = dict(model_cfg)
    next_cfg["database_path"] = resolution.database_path
    next_cfg["path"] = resolution.path
    next_cfg["path_source"] = resolution.source
    return next_cfg
