"""
core/logger.py
日志模块 — 提供全局日志器,支持按功能名过滤 debug 输出。

用法:
    from AiVision.core.logger import logger
    logger.info("...")
    logger.set_debug_message("blocks", "...")  # 只有功能名在白名单时才输出
"""
from __future__ import annotations
import logging
import os

# 给整个logging系统设置一个基础日志格式
logging.basicConfig(
    level=logging.DEBUG,                     # 基础日志级别
    format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)
# 第三方日志过滤（不要让第三方库的DEBUG/INFO日志把终端刷爆）
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
    """

    def __init__(self):
        self._logger = logging.getLogger("aivision")
        self._logger.setLevel(logging.INFO)  # 默认 INFO，debug 由白名单单独控制
        self._feature_debug_logger = logging.getLogger("aivision.feature_debug")
        self._feature_debug_logger.setLevel(logging.DEBUG)
        self._debug_features = self._parse_debug_features()

    @staticmethod
    def _parse_debug_features() -> set[str]:
        """
        从环境变量里读取"哪些功能允许打印debug"

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
        只有在DEBUG白名单上的功能，才打印整个高频调试日志。

        feature 在白名单中，或白名单包含 'all' 时，以 DEBUG 级别输出；否则静默丢弃。
        适用于推理循环等高频路径，在不修改代码的情况下按需开关调试信息。
        Args:
            feature: 功能名，如 'blocks'、'detect_face'，用于白名单匹配与日志前缀。
            msg    : 调试信息正文。
        """
        if "all" in self._debug_features or feature in self._debug_features:
            self._feature_debug_logger.debug(f"[{feature}] {msg}", stacklevel=2)
    # =============  对原生logger的简单封装  ==================
    # stacklevel=2:日志来源往调用栈上找一层，这样日志能定位真正调用位置。
    def debug(self, msg: str):     self._logger.debug(msg, stacklevel=2)            # 调试信息
    def info(self, msg: str):      self._logger.info(msg, stacklevel=2)             # 普通运行信息
    def warning(self, msg: str):   self._logger.warning(msg, stacklevel=2)          # 异常但是还能继续
    # error与exception的区别：error：只记错误信息，exception：记错误信息+traceback
    def error(self, msg: str):     self._logger.error(msg, stacklevel=2)            # 明确错误
    def exception(self, msg: str): self._logger.exception(msg, stacklevel=2)        # 错误 + python异常堆栈


# 模块级全局单例，全项目统一通过此实例输出日志
logger = _Logger()
