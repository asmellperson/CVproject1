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

# 全局基础配置：DEBUG 级别起收，确保底层库的详细日志有机会被捕获，
# 再由各 Logger 的 setLevel 按需过滤。
# stacklevel 由各封装方法自行传入，此处 format 包含文件名与行号以定位调用位置。
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)

# 将常见第三方库的日志级别提升至 WARNING，避免其 DEBUG/INFO 淹没业务日志。
# 新增需要屏蔽的库时，在此列表追加库名即可。
for _name in [
    "urllib3", "asyncio", "httpcore", "httpx", "huggingface_hub", "filelock",
    "torch", "tensorflow", "PIL", "matplotlib", "ultralytics",
    "sqlalchemy.engine", "sqlalchemy.pool",
]:
    logging.getLogger(_name).setLevel(logging.WARNING)


class _Logger:
    """
    项目全局日志器，在标准 logging.Logger 基础上增加按功能名过滤 debug 的能力。

    普通日志: debug() / info() / warning() / error() / exception()，行为与标准库一致。
    功能级调试: set_debug_message(feature, msg)，只有 feature 在白名单时才输出，
                避免高频推理循环中的调试信息干扰生产日志。

    stacklevel=2:
        所有方法均透传 stacklevel=2，使日志记录的文件名与行号指向实际调用方，
        而非本封装层。
    """

    def __init__(self):
        self._logger = logging.getLogger("aivision")
        self._logger.setLevel(logging.INFO)  # 默认 INFO，debug 由白名单单独控制
        self._debug_features = self._parse_debug_features()

    @staticmethod
    def _parse_debug_features() -> set[str]:
        """
        从环境变量 DEBUG_FEATURES 解析 debug 白名单。

        格式:
            DEBUG_FEATURES=blocks,detect_face   → 仅开启指定功能的 debug 输出
            DEBUG_FEATURES=all                  → 开启所有功能的 debug 输出
            未设置或为空                         → 白名单为空集，set_debug_message 全部静默

        Returns:
            功能名字符串集合；含 'all' 时 set_debug_message 对所有功能生效。
        """
        raw = os.environ.get("DEBUG_FEATURES", "").strip()
        if not raw:
            return set()
        return {x.strip() for x in raw.split(",") if x.strip()}

    def set_debug_message(self, feature: str, msg: str):
        """
        输出功能级 debug 日志（白名单控制）。

        feature 在白名单中，或白名单包含 'all' 时，以 DEBUG 级别输出；否则静默丢弃。
        适用于推理循环等高频路径，在不修改代码的情况下按需开关调试信息。

        Args:
            feature: 功能名，如 'blocks'、'detect_face'，用于白名单匹配与日志前缀。
            msg    : 调试信息正文。
        """
        if "all" in self._debug_features or feature in self._debug_features:
            self._logger.debug(f"[{feature}] {msg}", stacklevel=2)

    # 标准日志方法，透传 stacklevel=2 使行号指向调用方而非本层
    def debug(self, msg: str):     self._logger.debug(msg, stacklevel=2)
    def info(self, msg: str):      self._logger.info(msg, stacklevel=2)
    def warning(self, msg: str):   self._logger.warning(msg, stacklevel=2)
    def error(self, msg: str):     self._logger.error(msg, stacklevel=2)
    def exception(self, msg: str): self._logger.exception(msg, stacklevel=2)


# 模块级全局单例，全项目统一通过此实例输出日志
logger = _Logger()