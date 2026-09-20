"""启动统一后端。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


_AIVISION_ENV_FILE = Path(__file__).resolve().parents[1] / "AiVision" / ".env"
_ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file() -> None:
    """先加载 AiVision 共享数据库和认证配置，保留系统环境变量优先级。"""
    load_dotenv(dotenv_path=_AIVISION_ENV_FILE, override=False)
    load_dotenv(dotenv_path=_ENV_FILE, override=False)

def main() -> None:
    # 1、读取run_server.py同级目录下的.env文件
    _load_env_file()

    # app 可能在导入期读取环境变量，必须在加载 .env 后导入。
    from unified_backend.app import create_app

    # 2、读取命令行参数
    parser = argparse.ArgumentParser(description="Fuda Unified Backend")
    parser.add_argument("--host", default="0.0.0.0")                    # 0.0.0.0监听所有请求
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    # 3、将后端端口写进环境变量，其他模块也可以读取
    os.environ["UNIFIED_BACKEND_PORT"] = str(args.port)
    # 4、创建FastAPI应用并通过uvicorn启动统一后端HTTP服务
    uvicorn.run(create_app(), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
