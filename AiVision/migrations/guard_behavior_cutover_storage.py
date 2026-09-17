"""一次性切换的停机检查、可核验备份和运行资产归档。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tarfile

from sqlalchemy.engine import make_url


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    # 快照含真实 RTSP 和旧推送配置，只落入受限的部署备份目录。
    with path.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def require_stopped(port: int = 7862) -> None:
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            argv = (process / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, ProcessLookupError):
            continue
        if not argv or b"python" not in Path(os.fsdecode(argv[0])).name.encode():
            continue
        if any(arg in {b"AiVision.main", b"AiVision.api.app:app"} or
               b"guard_room.src.server" in arg or arg.endswith(b"AiVision/main.py") for arg in argv):
            raise ValueError("AiVision 或旧 Guard 仍在运行，拒绝迁移")
    with socket.socket() as client:
        client.settimeout(1)
        if client.connect_ex(("127.0.0.1", port)) == 0:
            raise ValueError("AiVision 端口仍在监听，拒绝迁移")


def backup_database(url, destination: Path) -> None:
    url = make_url(url)
    if url.get_backend_name() == "sqlite":
        with sqlite3.connect(url.database) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        destination.chmod(0o600)
    elif url.get_backend_name() == "mysql":
        env = {**os.environ, "MYSQL_PWD": url.password or ""}
        command = ["mysqldump", "--single-transaction", "--quick", "--routines", "--triggers",
                   "--events", "--hex-blob", "--host", url.host, "--port", str(url.port or 3306),
                   "--user", url.username, "--databases", url.database]
        with destination.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.PIPE, check=False)
            stream.flush()
            os.fsync(stream.fileno())
        if result.returncode:
            raise ValueError("数据库备份失败；未执行迁移")
    else:
        raise ValueError("不支持的备份数据库")
    if not destination.is_file() or not destination.stat().st_size:
        raise ValueError("数据库备份为空；未执行迁移")


def create_backup(directory: Path, *, source_url, target_url, model_config: Path,
                  old_root: Path, snapshot: dict) -> dict:
    manifest_path = directory / "backup.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for name, checksum in manifest["files"].items():
            if digest(directory / name) != checksum:
                raise ValueError("备份校验失败，禁止继续")
        return json.loads((directory / "snapshot.json").read_text())
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("发现未完成备份，禁止覆盖；请检查失败原因")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    backup_database(target_url, directory / "target.sql")
    if make_url(source_url) != make_url(target_url):
        backup_database(source_url, directory / "source.sql")
    shutil.copy2(model_config, directory / "model_paths.yaml")
    (directory / "model_paths.yaml").chmod(0o600)
    # 备份当前源码而非 HEAD，避免丢失工作区已有的中文注释等改动。
    with tarfile.open(directory / "old_source.tar.gz", "w:gz") as archive:
        for path in sorted(old_root.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".md", ".toml", ".txt", ".sh"}:
                archive.add(path, arcname=str(path.relative_to(old_root)))
    (directory / "old_source.tar.gz").chmod(0o600)
    write_json(directory / "snapshot.json", snapshot)
    write_json(manifest_path, {"files": {path.name: digest(path) for path in directory.iterdir() if path.is_file()}})
    return snapshot


def archive_assets(old_root: Path, destination: Path, inventory: list[dict]) -> None:
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for entry in inventory:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("归档相对路径无效")
        source, target = old_root / relative, destination / relative
        if target.exists() and digest(target) != entry["sha256"]:
            raise ValueError("归档目标冲突，禁止覆盖")
        if source.exists():
            if digest(source) != entry["sha256"]:
                raise ValueError("备份后运行资产发生变化，停止归档")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not target.exists():
                shutil.copy2(source, target)
                target.chmod(0o600)
            if digest(target) != entry["sha256"]:
                raise ValueError("运行资产复制校验失败")
            source.unlink()
        elif not target.exists():
            raise ValueError("源资产与归档均不存在")


def asset_inventory(old_root: Path) -> list[dict]:
    # 源码另有完整备份；媒体、权重、配置、缓存等非源码资产保留原相对路径。
    return [{"path": str(path.relative_to(old_root)), "sha256": digest(path)}
            for path in sorted(old_root.rglob("*")) if path.is_file()
            and path.suffix not in {".py", ".md", ".toml", ".txt", ".sh", ".pyc"}]
