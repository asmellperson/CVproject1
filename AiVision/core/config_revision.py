"""对已读取配置生成版本标识，在资源事务锁内拒绝覆盖并发修改。"""
import hashlib
import json

from pydantic_core import to_jsonable_python


class ConfigurationConflict(ValueError):
    """调用方读取配置后，其他操作者已经保存了不同的值。"""


def configuration_revision(value: dict) -> str:
    content = json.dumps(to_jsonable_python(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


def require_configuration_revision(value: dict, expected_revision: str | None) -> None:
    if expected_revision is not None and configuration_revision(value) != expected_revision:
        raise ConfigurationConflict("配置已被其他操作修改，请重新读取后再提交")


def configuration_values(value, fields) -> dict:
    return {key: value[key] if isinstance(value, dict) else getattr(value, key) for key in fields}


def require_configuration_values(current: dict, expected: dict | None) -> None:
    if expected is not None:
        require_configuration_revision(configuration_values(current, expected), configuration_revision(expected))
