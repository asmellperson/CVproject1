# 文件说明：作为程序启动入口并装配依赖。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""
AiVision 后端入口。

职责保持极简:
1. 设置 multiprocessing spawn
2. 加载 .env
3. 初始化 Orchestrator
4. 启动 FastAPI/Uvicorn
5. SIGINT/SIGTERM 优雅停止
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import signal
from types import FrameType


# 功能：读取或查询 `_load_dotenv_if_available` 对应的程序启动逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/main.py` 的 `main` 调用本符号
#   - 内部调用：`load_dotenv`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        # pydantic-settings 也会读取 .env；没有 python-dotenv 时不阻断启动。
        pass


# 功能：更新或保存 `_set_spawn_start_method` 对应的程序启动逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/main.py` 的 `main` 调用本符号
#   - 内部调用：`mp.set_start_method`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def _set_spawn_start_method() -> None:
    try:
        mp.set_start_method("spawn")
    except RuntimeError:
        # start method 已被设置时忽略。
        pass


# 功能：限制当前进程的 OpenCV 内部线程池，并返回实际生效值；输入与输出详见下方说明
# 参数：
#   - `thread_count`（int）：`thread_count` 对应的数量或大小
# 返回：int；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`AiVision/main.py` 的 `main` 调用本符号；`AiVision/tests/test_main_runtime.py` 的
#         `test_configure_opencv_threads_applies_requested_limit` 调用本符号
#   - 内部调用：`cv2.setNumThreads`、`int`、`cv2.getNumThreads`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def _configure_opencv_threads(thread_count: int) -> int:
    """限制当前进程的 OpenCV 内部线程池，并返回实际生效值。"""
    import cv2

    cv2.setNumThreads(thread_count)
    return int(cv2.getNumThreads())


# 功能：实现 `main` 对应的程序启动逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者；由解释器、ASGI 服务器、React 或框架生命周期直接触发
#   - 内部调用：`argparse.ArgumentParser`、`parser.add_argument`、`parser.parse_args`、`_set_spawn_start_method`、`_load_dotenv_if_available`、`_configure_opencv_threads`、`logger.info`、`mp.Manager`、`init_orchestrator`、`signal.signal`
#          等共 15 个调用。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源；会向日志系统输出运行或异常信息。
def main() -> None:
    parser = argparse.ArgumentParser(description="AiVision FastAPI Server")
    parser.add_argument("--host", default=None, help="覆盖 API_HOST")
    parser.add_argument("--port", type=int, default=None, help="覆盖 API_PORT")
    args = parser.parse_args()

    _set_spawn_start_method()
    _load_dotenv_if_available()

    from core.settings import settings

    actual_opencv_threads = _configure_opencv_threads(settings.runtime.opencv_threads)

    import uvicorn

    from api.app import create_app
    from core.logger import logger
    from platform.orchestrator import init_orchestrator

    logger.info(
        f"[main] OpenCV 线程限制 requested={settings.runtime.opencv_threads} "
        f"actual={actual_opencv_threads}"
    )

    mp_manager = mp.Manager()
    orchestrator = init_orchestrator(mp_manager)
    cleanup_started = False

    def _cleanup_once() -> None:
        """停止运行时资源；重复调用时不再次执行清理。"""
        nonlocal cleanup_started
        if cleanup_started:
            return
        cleanup_started = True

        try:
            orchestrator.stop()
        finally:
            try:
                mp_manager.shutdown()
            except Exception:
                logger.exception("[main] 关闭跨进程共享管理器失败")

    # 功能：停止并释放 `_shutdown` 对应的程序启动逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `signum`（int）：`signum` 对应的业务输入值
    #   - `_frame`（FrameType | None）：`_frame` 对应的业务输入值
    # 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`logger.info`、`orchestrator.stop`、`mp_manager.shutdown`、`SystemExit`。
    # 副作用/注意事项：会向日志系统输出运行或异常信息；校验或执行失败时会主动抛出异常。
    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info(f"[main] 收到退出信号 {signum},准备停止 AiVision")
        _cleanup_once()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        orchestrator.start()
        uvicorn.run(
            create_app(),
            host=args.host or settings.api.host,
            port=args.port or settings.api.port,
            log_level="info",
            access_log=False,
        )
    except KeyboardInterrupt:
        logger.info("[main] KeyboardInterrupt,准备退出")
    finally:
        _cleanup_once()


if __name__ == "__main__":
    main()
