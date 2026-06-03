"""启动统一后端。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from unified_backend.app import create_app


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
