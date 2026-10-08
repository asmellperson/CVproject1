"""本机模型路径的 YAML 读取、验证与原子保存。

配置相对路径以 AiVision 为根，权重必须是本机可读的绝对路径。读取结果缓存于进程内，
保存时用线程锁与文件锁串行写入，保留非目标配置及注释，并在替换文件后清缓存。
本模块只保证路径与配置有效，模型是否能加载仍需观察 Worker 状态。
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode

from AiVision.core.settings import settings


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PATH_LOCK = threading.RLock()


def _resolve_config_path(path_value: str) -> Path:
    """model_paths.yaml这个配置文件在哪里"""
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path = path.resolve()
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("MODEL_PATHS_CONFIG 必须指向 YAML 文件")
    return path


def _mapping(node: yaml.Node) -> dict[str, yaml.Node]:
    """将 YAML mapping 转成节点字典；拒绝非字符串键和重复键，避免同名配置被隐式覆盖。"""
    if not isinstance(node, MappingNode):
        raise ValueError("模型路径配置必须使用 YAML mapping")
    result = {}
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
            raise ValueError("模型路径配置的键必须是字符串")
        if key.value in result:
            raise ValueError(f"模型路径配置存在重复键: {key.value}")
        result[key.value] = value
    return result


def _read_document(path: Path) -> tuple[str, MappingNode | None]:
    """读取原始 YAML 与节点树，缺失文件视为空配置；拒绝锚点、别名和无效 path 字段。"""
    source = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
               for token in yaml.scan(source)):
            raise ValueError("模型路径配置不支持 YAML anchor / alias")
        root = yaml.compose(source, Loader=yaml.SafeLoader)
        if root is not None:
            entries = _mapping(root)
            if "models" not in entries:
                raise ValueError("模型路径配置缺少 models mapping")
            for model in _mapping(entries["models"]).values():
                fields = _mapping(model)
                value = fields.get("path")
                if value is not None and (
                    not isinstance(value, ScalarNode) or value.tag != "tag:yaml.org,2002:str"
                ):
                    raise ValueError("模型 path 必须是字符串")
        return source, root
    except yaml.YAMLError as exc:
        raise ValueError(f"模型路径 YAML 无效: {exc}") from exc


# 第一次读取YAML后，就把结果缓存起来
@lru_cache(maxsize=1)
def _load_model_paths() -> dict[str, str]:
    """读取 models.<name>.path；保存后显式清除此缓存。"""
    _, root = _read_document(_resolve_config_path(settings.model_paths.config_path))
    if root is None:
        return {}
    return {
        name: fields["path"].value.strip()
        for name, node in _mapping(_mapping(root)["models"]).items()
        if "path" in (fields := _mapping(node))
    }


def load_model_paths() -> dict[str, str]:
    """加锁读取缓存并返回外层副本，调用方修改返回字典不会改写路径缓存。"""
    with _PATH_LOCK:
        return dict(_load_model_paths())


def clear_model_paths_cache() -> None:
    """在路径锁内清除进程读取缓存；不重载 Worker，也不广播到其他进程。"""
    with _PATH_LOCK:
        _load_model_paths.cache_clear()


def validate_model_path(value: str, *, model_type: str = "yolo") -> str:
    """验证并规范化当前服务器上的模型路径。

    Args:
        value: 用户提供的绝对路径，可展开用户目录，不允许控制字符。
        model_type: 模型类型；insightface 要求包含约定 ONNX 文件的目录，
            纯检测要求 .onnx 文件，其他已支持类型要求非空可读文件。

    Returns:
        str: 解析符号链接后的绝对路径，不代表权重格式或推理设备已验证。

    Raises:
        ValueError: 路径、模型类型或必要文件不符合要求。
    """
    if not value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError("模型路径不能为空或包含控制字符")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise ValueError("请提供当前服务器上的绝对模型路径")
    try:
        path = path.resolve(strict=True)
        if model_type == "insightface":
            from AiVision.features.face_recognition.library.constants import MODEL_FILES

            if not path.is_dir():
                raise ValueError("InsightFace 模型路径必须是 buffalo_l 模型目录")
            files = [path / filename for filename in MODEL_FILES]
        elif model_type == "insightface_detection":
            if path.suffix != ".onnx":
                raise ValueError("InsightFace 纯检测模型路径必须是本地 .onnx 文件")
            files = [path]
        elif model_type in {"yolo", "yolo_pose", "timm_classifier"}:
            files = [path]
        else:
            raise ValueError("不支持的模型类型")
        for model_file in files:
            if not model_file.is_file() or model_file.stat().st_size == 0:
                raise ValueError(f"模型路径必须指向非空的普通文件: {model_file.name}")
            with model_file.open("rb") as stream:
                stream.read(1)
    except OSError as exc:
        raise ValueError(f"模型文件不存在或不可读: {exc}") from exc
    return str(path)


def _insert_entry(source: str, node: MappingNode, entry: str) -> str:
    """在节点结束处插入配置条目，保留其他文本；非空内联 mapping 不支持新增字段。"""
    if node.flow_style:
        if not node.value:
            replacement = json.dumps(yaml.safe_load(entry), ensure_ascii=False)
            return source[:node.start_mark.index] + replacement + source[node.end_mark.index:]
        raise ValueError("新增模型路径时请使用块状 models mapping，不能使用内联 mapping")
    lines = source.splitlines(keepends=True)
    offset = (len(source) if node.end_mark.index == len(source)
              else sum(len(line) for line in lines[:node.end_mark.line]))
    if offset and not source[:offset].endswith("\n"):
        entry = "\n" + entry
    return source[:offset] + entry + source[offset:]


def _updated_document(source: str, root: MappingNode | None, name: str, path: str) -> str:
    """仅生成目标模型路径的更新文本，不写磁盘；优先替换 scalar 以保留手工注释。"""
    scalar = json.dumps(path, ensure_ascii=False)
    if root is None:
        prefix = source + ("\n" if source and not source.endswith("\n") else "")
        return prefix + f"models:\n  {name}:\n    path: {scalar}\n"
    models = _mapping(root)["models"]
    entries = _mapping(models)
    if name not in entries:
        indent = " " * models.start_mark.column
        return _insert_entry(source, models, f"{indent}{name}:\n{indent}  path: {scalar}\n")
    model = entries[name]
    fields = _mapping(model)
    if "path" not in fields:
        return _insert_entry(source, model, f"{' ' * model.start_mark.column}path: {scalar}\n")
    node = fields["path"]
    # 只替换目标 scalar，保留手写注释及其他模型配置。
    if node.style in {"|", ">"}:
        scalar += "\n"
    return source[:node.start_mark.index] + scalar + source[node.end_mark.index:]


def save_model_path(name: str, value: str) -> str:
    """验证注册模型与路径后，锁定配置并原子保存。

    Args:
        name: 固定注册表中的逻辑模型名。
        value: 待验证的本机模型路径。

    Returns:
        str: 实际保存的规范化路径；不会在本函数内启动或重载模型。

    Raises:
        KeyError: 模型未注册。
        ValueError: 路径或 YAML 契约无效，或生成文本未通过回读校验。
        OSError: 配置目录、锁文件或原子写入失败。

    临时文件与目标位于同一目录，先 flush/fsync 再替换，并保留已有文件权限。
    """
    from .model_registry import get_model_spec

    spec = get_model_spec(name)
    model_path = validate_model_path(value, model_type=spec.type)
    config_path = _resolve_config_path(settings.model_paths.config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with _PATH_LOCK, config_path.with_suffix(config_path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        source, root = _read_document(config_path)
        updated = _updated_document(source, root, name, model_path)
        parsed = yaml.safe_load(updated)
        if parsed["models"][name]["path"] != model_path:
            raise ValueError("模型路径配置更新校验失败")
        mode = stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=config_path.parent,
                prefix=f".{config_path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                os.fchmod(stream.fileno(), mode)
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, config_path)
            clear_model_paths_cache()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return model_path
