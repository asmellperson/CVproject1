"""
core/logger.py
日志模块 — 提供全局日志器,支持按功能名过滤 debug 输出。

用法:
    from core.logger import logger
    logger.info("...")
    logger.set_debug_message("blocks", "...")  # 只有功能名在白名单时才输出
"""
from __future__ import annotations
import logging
import os

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)

# 屏蔽第三方库的 DEBUG
for _name in [
    "urllib3", "asyncio", "httpcore", "httpx", "huggingface_hub", "filelock",
    "torch", "tensorflow", "PIL", "matplotlib", "ultralytics",
    "sqlalchemy.engine", "sqlalchemy.pool",
]:
    logging.getLogger(_name).setLevel(logging.WARNING)


class _Logger:
    """按功能名过滤 debug 的轻量包装"""

    def __init__(self):
        self._logger = logging.getLogger("aivision")
        self._logger.setLevel(logging.INFO)
        # 通过环境变量配置 debug 白名单: DEBUG_FEATURES=blocks,detect_face 或 DEBUG_FEATURES=all
        self._debug_features = self._parse_debug_features()

    @staticmethod
    def _parse_debug_features() -> set[str]:
        raw = os.environ.get("DEBUG_FEATURES", "").strip()
        if not raw:
            return set()
        return {x.strip() for x in raw.split(",") if x.strip()}

    def set_debug_message(self, feature: str, msg: str):
        """按功能名过滤 — 只有 feature 在白名单(或白名单含 'all')时才输出"""
        if "all" in self._debug_features or feature in self._debug_features:
            self._logger.debug(f"[{feature}] {msg}", stacklevel=2)

    def debug(self, msg: str): self._logger.debug(msg, stacklevel=2)
    def info(self, msg: str): self._logger.info(msg, stacklevel=2)
    def warning(self, msg: str): self._logger.warning(msg, stacklevel=2)
    def error(self, msg: str): self._logger.error(msg, stacklevel=2)
    def exception(self, msg: str): self._logger.exception(msg, stacklevel=2)


logger = _Logger()
