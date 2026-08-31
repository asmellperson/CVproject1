# 文件说明：作为服务端入口并装配依赖。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

"""启动统一后端。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from unified_backend.app import create_app


# 功能：读取或查询 `_load_env_file` 对应的服务端逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `path`（Path）：目标路径
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：`unified_backend/run_server.py` 的 `main` 调用本符号
#   - 内部调用：`path.exists`、`path.read_text(encoding='utf-8').splitlines`、`path.read_text`、`raw_line.strip`、`line.startswith`、`line.split`、`key.strip`、`value.strip().strip('"').strip`、`value.strip().strip`、`value.strip`
#          等共 11 个调用。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def _load_env_file(path: Path) -> None:
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


# 功能：实现 `main` 对应的服务端逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者；由解释器、ASGI 服务器、React 或框架生命周期直接触发
#   - 内部调用：`_load_env_file`、`Path(__file__).resolve`、`Path`、`argparse.ArgumentParser`、`parser.add_argument`、`parser.parse_args`、`str`、`uvicorn.run`、`create_app`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def main() -> None:
    _load_env_file(Path(__file__).resolve().parent / ".env")

    parser = argparse.ArgumentParser(description="Fuda Unified Backend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    os.environ["UNIFIED_BACKEND_PORT"] = str(args.port)
    uvicorn.run(create_app(), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
