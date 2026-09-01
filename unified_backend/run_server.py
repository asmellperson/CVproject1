# 文件说明：作为服务端入口并装配依赖。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""启动统一后端。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file() -> None:
    """加载 unified_backend/.env，保留已存在的系统环境变量。"""
    load_dotenv(dotenv_path=_ENV_FILE, override=False)


# 功能：实现 `main` 对应的服务端逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者；由解释器、ASGI 服务器、React 或框架生命周期直接触发
#   - 内部调用：`_load_env_file`、`argparse.ArgumentParser`、`parser.add_argument`、`parser.parse_args`、`str`、`uvicorn.run`、`create_app`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def main() -> None:
    _load_env_file()

    # app 可能在导入期读取环境变量，必须在加载 .env 后导入。
    from unified_backend.app import create_app

    parser = argparse.ArgumentParser(description="Fuda Unified Backend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    os.environ["UNIFIED_BACKEND_PORT"] = str(args.port)
    uvicorn.run(create_app(), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
