# 文件说明：实现`logger` 模块相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：项目全局日志器，在标准 logging.Logger 基础上增加按功能名过滤 debug 的能力；输入与输出详见下方说明
# 参数：无。
# 返回：_Logger；返回新建的 `_Logger` 实例。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：初始化或配置 `__init__` 对应的`logger` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`logging.getLogger`、`self._logger.setLevel`、`self._parse_debug_features`。
    # 副作用/注意事项：会更新当前实例的运行状态；会向日志系统输出运行或异常信息。
    def __init__(self):
        self._logger = logging.getLogger("aivision")
        self._logger.setLevel(logging.INFO)  # 默认 INFO，debug 由白名单单独控制
        self._debug_features = self._parse_debug_features()

    # 功能：从环境变量 DEBUG_FEATURES 解析 debug 白名单；输入与输出详见下方说明
    # 参数：无。
    # 返回：set[str]；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：`AiVision/core/logger.py` 的 `_Logger::__init__` 调用本符号
    #   - 内部调用：`os.environ.get('DEBUG_FEATURES', '').strip`、`os.environ.get`、`set`、`x.strip`、`raw.split`。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：输出功能级 debug 日志（白名单控制）；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `feature`（str）：`feature` 对应的业务输入值
    #   - `msg`（str）：`msg` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._logger.debug`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
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
    # 功能：实现 `debug` 对应的`logger` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `msg`（str）：`msg` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：`AiVision/core/logger.py` 的 `_Logger::set_debug_message` 调用本符号
    #   - 内部调用：`self._logger.debug`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def debug(self, msg: str):     self._logger.debug(msg, stacklevel=2)
    # 功能：实现 `info` 对应的`logger` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `msg`（str）：`msg` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._logger.info`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def info(self, msg: str):      self._logger.info(msg, stacklevel=2)
    # 功能：实现 `warning` 对应的`logger` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `msg`（str）：`msg` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._logger.warning`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def warning(self, msg: str):   self._logger.warning(msg, stacklevel=2)
    # 功能：实现 `error` 对应的`logger` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `msg`（str）：`msg` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._logger.error`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def error(self, msg: str):     self._logger.error(msg, stacklevel=2)
    # 功能：实现 `exception` 对应的`logger` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    #   - `msg`（str）：`msg` 对应的业务输入值
    # 返回：None；仅执行处理流程，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`self._logger.exception`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息。
    def exception(self, msg: str): self._logger.exception(msg, stacklevel=2)


# 模块级全局单例，全项目统一通过此实例输出日志
logger = _Logger()