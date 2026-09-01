# 文件说明：作为程序启动入口并装配依赖。

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
from pathlib import Path
from types import FrameType

from dotenv import load_dotenv


_ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file() -> None:
    """加载 AiVision/.env，保留已存在的系统环境变量。"""
    load_dotenv(dotenv_path=_ENV_FILE, override=False)

def _set_spawn_start_method() -> None:
    """设置 multiprocessing 的启动方式为 spawn；若已设置则忽略。"""
    try:
        mp.set_start_method("spawn")
    except RuntimeError:
        # start method 已被设置时忽略。
        pass

def _configure_opencv_threads(thread_count: int) -> int:
    """限制当前进程的 OpenCV 内部线程池，并返回实际生效值。"""
    import cv2

    cv2.setNumThreads(thread_count)   # 控制opencv内部线程数
    return int(cv2.getNumThreads())   # 实际配置线程数

def main() -> None:
    # 1、解析命令行参数，不传的话就使用配置文件的settings.api.host
    parser = argparse.ArgumentParser(description="AiVision FastAPI Server")
    parser.add_argument("--host", default=None, help="覆盖 API_HOST")
    parser.add_argument("--port", type=int, default=None, help="覆盖 API_PORT")
    args = parser.parse_args()

    # 2、准备运行环境，设置多进程spawn启动方式、加载.env环境变量
    _set_spawn_start_method()
    _load_env_file()

    # 3、读取全局配置对象settings
    from core.settings import settings       # settings是AiVision全局配置对象，settings.xxx.xxx就是读取系统配置
    # 4、限制OpenCV线程数，避免CPU过载
    actual_opencv_threads = _configure_opencv_threads(settings.runtime.opencv_threads)

    # 5、导入正在运行时所需要的模块
    import uvicorn

    from api.app import create_app      # 创建AiVision HTTP API服务
    from core.logger import logger      # 项目统一日志工具
    from platform.orchestrator import init_orchestrator

    logger.info(
        f"[main] OpenCV 线程限制 配置需求={settings.runtime.opencv_threads} "
        f"实际={actual_opencv_threads}"
    )
    # 6、创建跨进程共享管理器
    mp_manager = mp.Manager()           # 创建一个可以帮助多个Python进程共享数据的管理服务
    # 7、创建AiVision总调度器，将跨进程共享管理器传入，后续Orchestrator会使用它来创建共享队列、共享字典等
    orchestrator = init_orchestrator(mp_manager)   ## 后续orchestrator.start()代表启动整个实时视觉系统
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

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        """收到退出信号时执行的函数
            signum : 收到了哪一种系统信号，比如SIGINT、SIGTERM等
            _frame : 当前栈帧对象，通常不使用
        """
        logger.info(f"[main] 收到退出信号 {signum},准备停止 AiVision")
        _cleanup_once()
        raise SystemExit(0)           # 正常结束当前Python程序

    # 8、收到 SIGINT（Ctrl+C）或 SIGTERM（kill命令）时，调用 _shutdown 函数
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 9、启动整个实时视觉系统
    try:
        orchestrator.start()            #开机

        # 10、启动HTTP API服务，持续运行，一直监听HTTP请求，直到收到退出信号
        uvicorn.run(
            create_app(),                        # FastAPI应用对象，交给uvicorn.run监听
            host=args.host or settings.api.host,
            port=args.port or settings.api.port,
            log_level="info",                    # Uvicorin日志级别
            access_log=False,                   # 关闭每个HTTP请求的访问日志
        )
    # 11、[防御性代码，疑似冗余]捕获键盘中断异常（Ctrl+C），记录日志，准备退出，额外退出保险
    except KeyboardInterrupt:                           # KeyboardInterrupt：一般是ctrl+c触发的中断异常
        logger.info("[main] KeyboardInterrupt,准备退出")
    finally:
        _cleanup_once()


if __name__ == "__main__":
    main()
