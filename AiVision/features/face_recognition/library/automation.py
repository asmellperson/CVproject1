"""安装和检查人脸库 systemd 定时任务，不访问业务数据库或海康平台。"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ENTRYPOINT = "AiVision.face_library"
SERVICE_NAME = "hikvision-face-library-sync.service"
TIMER_NAME = "hikvision-face-library-sync.timer"
UNIT_DIRECTORY = Path("/etc/systemd/system")
TEMPLATE_DIRECTORY = Path(__file__).resolve().parent


def _systemd_path(path: Path, *, command: bool = False) -> str:
    """保护空格及 systemd 特殊字符，避免部署目录被展开成其他路径或参数。"""
    value = str(path)
    if any(ord(char) < 32 for char in value):
        raise ValueError("部署路径不能包含控制字符")
    value = value.replace("%", "%%")
    # WorkingDirectory 把整行当作路径，双引号会成为文件名的一部分；只有 ExecStart 需要分词引用。
    if not command:
        return value
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$")
    return f'"{value}"'


def render_units(project_root: Path, python: Path) -> dict[str, str]:
    """从仓库模板生成当前目录和当前 Python 对应的 unit，消除现场手填路径。"""
    service = (TEMPLATE_DIRECTORY / SERVICE_NAME).read_text(encoding="utf-8")
    replacements = {
        "WorkingDirectory": _systemd_path(project_root),
        "ExecStart": f"{_systemd_path(python, command=True)} -m {ENTRYPOINT}",
    }
    for key, value in replacements.items():
        service, count = re.subn(rf"^{key}=.*$", lambda _: f"{key}={value}", service, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f"service 模板必须且只能包含一个 {key}")
    return {SERVICE_NAME: service, TIMER_NAME: (TEMPLATE_DIRECTORY / TIMER_NAME).read_text(encoding="utf-8")}


def _systemctl(*arguments: str) -> str:
    """所有 systemd 操作检查退出码，不把安装失败或查询失败报告为成功。"""
    try:
        result = subprocess.run(["systemctl", *arguments], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        print(f"systemctl {arguments[0]} 失败，退出码 {exc.returncode}。")
        if exc.stderr:
            print(exc.stderr.strip())
        raise
    return result.stdout


def _properties(unit: str, *names: str) -> dict[str, str]:
    args = ["show", unit, "--no-pager"]
    for name in names:
        args.extend(("--property", name))
    return dict(line.split("=", 1) for line in _systemctl(*args).splitlines() if "=" in line)


def _entry_matches(service: dict[str, str], project_root: Path) -> bool:
    return (
        service.get("LoadState") == "loaded"
        and service.get("WorkingDirectory") == str(project_root)
        and service.get("ExecStart", "").count("argv[]=") == 1
        and re.search(rf"(?:^|\s)-m\s+{re.escape(ENTRYPOINT)}(?=\s*(?:;|$))", service.get("ExecStart", "")) is not None
    )


def _write_unit(path: Path, content: str) -> None:
    """内容不变时不重写；变更前备份，并通过替换完整文件避免写出半个 unit。"""
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        shutil.copy2(path, path.with_name(f"{path.name}.bak"))
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.chmod(0o644)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _verify_units(units: dict[str, str]) -> None:
    """写入系统目录前由 systemd 核验完整配置，错误模板不能覆盖现场可用文件。"""
    with tempfile.TemporaryDirectory(prefix="face-library-units-") as directory:
        paths = []
        for name, content in units.items():
            path = Path(directory) / name
            path.write_text(content, encoding="utf-8")
            paths.append(str(path))
        try:
            subprocess.run(["systemd-analyze", "verify", "--man=no", *paths], check=True,
                           capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            print("systemd 配置校验失败，未覆盖已安装的 unit。")
            if exc.stderr:
                print(exc.stderr.strip())
            raise


def install_systemd(project_root: Path, *, dry_run: bool = False) -> int:
    """覆盖已安装的旧入口；重载后核对实际生效配置，避免旧 drop-in 覆盖而误报成功。"""
    # 保留虚拟环境解释器的位置，不能解析其符号链接后误用系统 Python。
    python = Path(sys.executable).absolute()
    units = render_units(project_root, python)
    if dry_run:
        for name, content in units.items():
            print(f"配置预览：{name}\n{content}")
        return 0
    if os.geteuid() != 0:
        print(f"安装需要 root 权限，请使用 sudo {python} -m {ENTRYPOINT} --install-systemd")
        return 1
    _verify_units(units)
    for name, content in units.items():
        _write_unit(UNIT_DIRECTORY / name, content)
    _systemctl("daemon-reload")
    service = _properties(SERVICE_NAME, "LoadState", "WorkingDirectory", "ExecStart")
    if not _entry_matches(service, project_root):
        print("安装后的实际入口与当前项目不一致，请检查 service 的 drop-in 覆盖配置。")
        return 1
    _systemctl("reset-failed", SERVICE_NAME)
    _systemctl("enable", "--now", TIMER_NAME)
    _systemctl("start", "--no-block", SERVICE_NAME)
    print("人员同步与特征生成定时任务已安装，并已提交一次立即更新请求。")
    print(f"使用 {python} -m {ENTRYPOINT} --status 查看实际执行结果。")
    return 0


def show_status(project_root: Path) -> int:
    """同时检查调度和实际执行结果，避免仅凭 timer 运行就判定更新成功。"""
    timer = _properties(TIMER_NAME, "LoadState", "ActiveState", "UnitFileState", "LastTriggerUSec")
    service = _properties(
        SERVICE_NAME, "LoadState", "WorkingDirectory", "ExecStart", "ActiveState", "Result",
        "ExecMainStatus", "ExecMainStartTimestamp", "ExecMainExitTimestamp",
    )
    healthy = True
    if not _entry_matches(service, project_root):
        print("[失败] 已安装服务的入口或工作目录与当前项目不一致，请重新执行 --install-systemd。")
        healthy = False
    timer_ready = (timer.get("LoadState") == "loaded" and timer.get("ActiveState") == "active"
                   and timer.get("UnitFileState") == "enabled")
    print(f"定时器：{'已启用' if timer_ready else '未安装或未启用'}；最近触发：{timer.get('LastTriggerUSec') or '尚未触发'}")
    healthy = healthy and timer_ready
    print(f"最近开始：{service.get('ExecMainStartTimestamp') or '尚未执行'}")
    print(f"最近结束：{service.get('ExecMainExitTimestamp') or '尚未结束'}")
    if service.get("ActiveState") == "activating":
        print("更新正在执行，完成后再次查询结果。")
    elif not service.get("ExecMainExitTimestamp"):
        print("[失败] 尚无已完成的执行记录，不能确认同步成功。")
        healthy = False
    elif service.get("Result") != "success" or service.get("ExecMainStatus") != "0":
        print("[失败] 最近更新存在失败；已成功提交的数据保留，失败项等待下次更新重试。")
        print(f"查看日志：journalctl -u {SERVICE_NAME} -n 100 --no-pager")
        healthy = False
    else:
        print("最近一次人员同步和特征生成均已完成。")
    return 0 if healthy else 1
