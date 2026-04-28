# run_server.py
"""
启动入口
    1、调用create_app()创建后端应用
    2、用uvicorn启动服务
"""
from __future__ import annotations

import argparse
import uvicorn
from src.server import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Guard Room FastAPI Server")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    # 创建一个FastAPI应用对象
    app = create_app(args.config)
    # 使用uvicorn启动FastAPI应用
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
