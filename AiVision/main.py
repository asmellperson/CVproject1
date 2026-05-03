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


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        # pydantic-settings 也会读取 .env；没有 python-dotenv 时不阻断启动。
        pass


def _set_spawn_start_method() -> None:
    try:
        mp.set_start_method("spawn")
    except RuntimeError:
        # start method 已被设置时忽略。
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="AiVision FastAPI Server")
    parser.add_argument("--host", default=None, help="覆盖 API_HOST")
    parser.add_argument("--port", type=int, default=None, help="覆盖 API_PORT")
    args = parser.parse_args()

    _set_spawn_start_method()
    _load_dotenv_if_available()

    import uvicorn

    from api.app import create_app
    from core.logger import logger
    from core.settings import settings
    from platform.orchestrator import init_orchestrator

    mp_manager = mp.Manager()
    orchestrator = init_orchestrator(mp_manager)

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info(f"[main] 收到退出信号 {signum},准备停止 AiVision")
        try:
            orchestrator.stop()
        finally:
            try:
                mp_manager.shutdown()
            except Exception:
                pass
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
        orchestrator.stop()
        try:
            mp_manager.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
