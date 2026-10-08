"""AiVision 的正式进程入口，协调运行环境、检测系统和 HTTP 服务。

在项目根目录通过 python -m AiVision.main 启动。此文件只负责组织启动和退出，
摄像头采集、模型加载、Consumer 与告警资源由 runtime/orchestrator.py 管理，
HTTP 路由和认证中间件由 api/app.py 组装。

启动顺序：
    解析命令行 → 尝试设置 spawn → 加载 AiVision/.env → 导入 Settings
        → 限制当前进程的 OpenCV 线程数 → 数据库 bootstrap
        → 创建 multiprocessing.Manager → 初始化 Orchestrator
        → 注册退出信号处理 → 启动检测资源 → 创建应用并运行 Uvicorn。
    Settings 及依赖它的业务模块延迟到环境加载后导入，避免提前读取缺失配置。
    Uvicorn 在 Orchestrator.start() 返回后才运行，前面的准备耗时会推迟端口监听。

配置来源：
    .env 路径由本文件位置确定，不依赖命令执行时的工作目录。
    已存在的进程环境变量优先于 .env；有效的 --host/--port 参数覆盖 Settings 中的监听值。
    数据库、模型路径及其他业务参数继续由各自的 Settings 或配置服务管理。

退出流程：
    信号回调或检测/HTTP 运行阶段退出 → _cleanup_once()
        → Orchestrator.stop() → Manager.shutdown()。
    清理标志用于避免多个退出入口重复回收资源，表示已开始清理，不保证全部清理成功。
    外层 try/finally 从检测启动处开始；更早的配置、数据库和编排器初始化不在其范围内。

导入本模块不会自动调用 main()；直接启动 api.app 也不会替代这里的数据库和检测初始化。
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import signal
from pathlib import Path
from types import FrameType

from dotenv import load_dotenv


# 固定为 AiVision/.env，避免从不同工作目录启动时意外读取其他环境文件。
_ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file() -> None:
    """将 AiVision/.env 中尚未设置的变量补入当前进程环境。

    override=False 保留部署脚本或系统已注入的变量。本函数不检查必填配置是否完整，
    后续导入 Settings 时再校验；也不会刷新此前已经创建的 Settings 对象。
    """
    load_dotenv(dotenv_path=_ENV_FILE, override=False)

def _set_spawn_start_method() -> None:
    """尝试将 multiprocessing 的默认启动方式设为 spawn。

    在创建 Manager 和检测子进程之前调用，使新进程按 spawn 方式重新导入模块。
    若其他入口已经设置过启动方式，保留已有上下文；此处没有 force=True，
    因而调用成功返回也不保证原有的其他启动方式被改成 spawn。
    """
    try:
        mp.set_start_method("spawn")
    except RuntimeError:
        # 嵌入运行或重复调用时可能已有进程上下文，沿用它而不强制替换。
        pass

def _configure_opencv_threads(thread_count: int) -> int:
    """设置当前进程的 OpenCV 内部线程数，避免与业务线程叠加占用过多 CPU。

    Args:
        thread_count: 来自 settings.runtime.opencv_threads 的配置值，直接传给
            cv2.setNumThreads()；本函数不额外校验或修改取值。

    Returns:
        int: cv2.getNumThreads() 报告的实际值，供启动日志与配置值对照。
            该设置只作用于当前进程，不代表各 spawn 子进程已应用同一限制。

    OpenCV 的导入和设置失败会直接向调用方传播，不会默认为已经配置成功。
    """
    import cv2

    cv2.setNumThreads(thread_count)
    return int(cv2.getNumThreads())

def main() -> None:
    """准备后端依赖、启动检测和 HTTP 监听，并在运行阶段退出时触发清理。

    从命令行读取可选的 --host 和整数 --port；未提供时使用 Settings。
    本函数会访问数据库、创建管理器子进程、启动检测资源并阻塞运行 HTTP 服务，
    不是仅创建 FastAPI 对象的工厂函数，应在主线程中作为正式入口执行。

    Raises:
        SystemExit: argparse 处理帮助或参数错误，或信号回调完成清理后请求退出。

    除显式处理的 KeyboardInterrupt 外，初始化和运行异常继续传播。
    清理回调定义之前的初始化失败不进入下方 finally；已进入运行阶段的失败
    会尝试清理，但部分启动资源是否能完整回收仍取决于各运行模块的 stop() 实现。
    """
    # 先解析参数，--help 或参数错误可在加载数据库、模型等依赖之前结束进程。
    parser = argparse.ArgumentParser(description="AiVision FastAPI Server")
    parser.add_argument("--host", default=None, help="覆盖 API_HOST")
    parser.add_argument("--port", type=int, default=None, help="覆盖 API_PORT")
    args = parser.parse_args()

    # 创建任何子进程前准备进程上下文，并在导入 Settings 前补齐环境变量。
    _set_spawn_start_method()
    _load_env_file()

    # Settings 在模块导入时读取并校验配置，不能把此导入提前到 .env 加载之前。
    from AiVision.core.settings import settings
    # 这里限制主进程的 OpenCV 并行度，摄像头/模型子进程的设置由各自入口负责。
    actual_opencv_threads = _configure_opencv_threads(settings.runtime.opencv_threads)

    # 业务模块也可能在导入时读取 Settings，因此一并延迟到环境准备之后。
    import uvicorn

    # app.py 导入时也会构造模块级 app，但此时不监听端口；下方显式创建的应用交给 Uvicorn。
    from AiVision.api.app import create_app
    from AiVision.core.logger import logger
    from AiVision.runtime.bootstrap import bootstrap_database
    from AiVision.runtime.orchestrator import init_orchestrator

    logger.info(
        f"[main] OpenCV 线程限制 配置需求={settings.runtime.opencv_threads} "
        f"实际={actual_opencv_threads}"
    )
    # 先创建缺失表并核验结构，数据库准备失败时尚未创建 Manager 或启动采集/推理。
    bootstrap_database()
    # Manager 启动独立服务进程，为运行模块提供跨进程共享对象的代理与管理能力。
    mp_manager = mp.Manager()
    # 获取并保存全局编排器；构造运行对象和真正调用 start() 启动检测是两个阶段。
    orchestrator = init_orchestrator(mp_manager)
    cleanup_started = False

    def _cleanup_once() -> None:
        """在本次 main() 调用中只尝试一次运行资源清理。

        信号回调和外层 finally 共用此入口。先停止依赖共享对象的业务资源，
        再关闭 Manager；即使 orchestrator.stop() 抛错，仍会尝试 shutdown()。
        Manager 关闭异常写日志，Orchestrator 停止异常则继续传播。
        """
        nonlocal cleanup_started
        if cleanup_started:
            return
        # 在实际清理前置位，防止退出流程再次进入；失败后也不会在本函数内自动重试。
        cleanup_started = True

        try:
            orchestrator.stop()
        finally:
            try:
                mp_manager.shutdown()
            except Exception:
                logger.exception("[main] 关闭跨进程共享管理器失败")

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        """记录退出信号，清理运行资源，然后请求正常退出进程。

        Args:
            signum: 触发回调的信号编号，此处注册 SIGINT 和 SIGTERM。
            _frame: Python 信号处理器传入的当前执行帧，本回调不使用。

        Raises:
            SystemExit: 清理正常返回后，以退出码 0 请求退出；清理自身抛错时
                原异常继续传播，不会执行到该退出语句。
        """
        logger.info(f"[main] 收到退出信号 {signum},准备停止 AiVision")
        _cleanup_once()
        raise SystemExit(0)

    # 注册进程退出回调；Python 要求在主线程执行 signal.signal()。
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 清理保护从这里开始；上面的数据库、Manager、编排器初始化及信号注册不在其中。
    try:
        orchestrator.start()

        # 检测启动返回后才进入 HTTP 服务；uvicorn.run() 在服务运行期间阻塞此流程。
        uvicorn.run(
            create_app(),
            # 按现有 or 表达式回退：空 host 或值为 0 的 port 也会使用 Settings。
            host=args.host or settings.api.host,
            port=args.port or settings.api.port,
            log_level="info",
            access_log=False,  # 关闭逐请求访问日志，业务日志仍由各模块记录。
        )
    # 若中断以 KeyboardInterrupt 形式到达这里，记录后仍由 finally 执行统一清理。
    except KeyboardInterrupt:
        logger.info("[main] KeyboardInterrupt,准备退出")
    finally:
        # 覆盖正常返回和异常退出；信号回调已开始清理时，此调用直接返回。
        _cleanup_once()


if __name__ == "__main__":
    # spawn 子进程会重新导入模块，入口保护避免导入时再次启动整套后端。
    main()
