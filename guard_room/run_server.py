# run_server.py
"""
启动入口
    1、调用create_app()创建后端应用
    2、用uvicorn启动服务
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn
from src.server import create_app


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs without overriding exported env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


if __name__ == "__main__":
    _load_env_file(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(description="Guard Room FastAPI Server")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()

    os.environ["GUARD_ROOM_PORT"] = str(args.port)

    # 创建一个FastAPI应用对象
    app = create_app(args.config)
    # 使用uvicorn启动FastAPI应用
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
