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

from core.logger import logger
from core.settings import settings

try:
    import yaml
except Exception:  # pragma: no cover - 仅在缺少 PyYAML 的环境下触发
    yaml = None


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ModelPathResolution:
    path: str
    source: str
    database_path: str


def _resolve_config_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return (_PROJECT_ROOT / path).resolve()


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
