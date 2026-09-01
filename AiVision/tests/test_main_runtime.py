# 文件说明：包含程序启动、运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import os
import signal
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

import main as main_module
from main import _configure_opencv_threads


# 功能：验证 `test_configure_opencv_threads_applies_requested_limit` 对应的程序启动、运行时逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`SimpleNamespace`、`calls.append`、`monkeypatch.setitem`、`_configure_opencv_threads`。
# 副作用/注意事项：可能创建、写入、移动或删除本地文件；可能启动、等待或停止线程/进程资源。
def test_configure_opencv_threads_applies_requested_limit(monkeypatch):
    calls: list[int] = []
    fake_cv2 = SimpleNamespace(
        setNumThreads=lambda value: calls.append(value),
        getNumThreads=lambda: calls[-1],
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    actual = _configure_opencv_threads(4)

    assert calls == [4]
    assert actual == 4


def test_load_env_file_uses_aivision_env_without_overriding_system_values(
    monkeypatch,
    tmp_path,
):
    expected_env_file = Path(main_module.__file__).resolve().parent / ".env"
    assert main_module._ENV_FILE == expected_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        "AIVISION_ENV_PRIORITY=from-file\nAIVISION_ENV_FILE_ONLY=loaded\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "_ENV_FILE", env_file)
    monkeypatch.setenv("AIVISION_ENV_PRIORITY", "from-system")
    monkeypatch.delenv("AIVISION_ENV_FILE_ONLY", raising=False)

    main_module._load_env_file()

    assert os.environ["AIVISION_ENV_PRIORITY"] == "from-system"
    assert os.environ["AIVISION_ENV_FILE_ONLY"] == "loaded"


def _install_main_runtime_fakes(monkeypatch, exit_mode, signum=None):
    manager = SimpleNamespace(shutdown=Mock())
    orchestrator = SimpleNamespace(start=Mock(), stop=Mock())
    logger = SimpleNamespace(info=Mock(), exception=Mock())
    handlers = {}

    settings_module = ModuleType("core.settings")
    settings_module.settings = SimpleNamespace(
        runtime=SimpleNamespace(opencv_threads=1),
        api=SimpleNamespace(host="127.0.0.1", port=8000),
    )
    api_app_module = ModuleType("api.app")
    api_app_module.create_app = Mock(return_value=object())
    logger_module = ModuleType("core.logger")
    logger_module.logger = logger
    orchestrator_module = ModuleType("platform.orchestrator")
    orchestrator_module.init_orchestrator = Mock(return_value=orchestrator)
    uvicorn_module = ModuleType("uvicorn")

    def run(*_args, **_kwargs):
        if exit_mode == "keyboard_interrupt":
            raise KeyboardInterrupt
        if exit_mode == "signal":
            handlers[signum](signum, None)

    uvicorn_module.run = run

    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(main_module, "_set_spawn_start_method", lambda: None)
    monkeypatch.setattr(main_module, "_load_env_file", lambda: None)
    monkeypatch.setattr(main_module, "_configure_opencv_threads", lambda value: value)
    monkeypatch.setattr(main_module.mp, "Manager", lambda: manager)
    monkeypatch.setattr(
        main_module.signal,
        "signal",
        lambda registered_signum, handler: handlers.__setitem__(registered_signum, handler),
    )
    monkeypatch.setitem(sys.modules, "core.settings", settings_module)
    monkeypatch.setitem(sys.modules, "api.app", api_app_module)
    monkeypatch.setitem(sys.modules, "core.logger", logger_module)
    monkeypatch.setitem(sys.modules, "platform.orchestrator", orchestrator_module)
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_module)

    return manager, orchestrator


@pytest.mark.parametrize("exit_mode", ["normal", "keyboard_interrupt"])
def test_main_cleans_up_once_when_runtime_returns_or_is_interrupted(monkeypatch, exit_mode):
    manager, orchestrator = _install_main_runtime_fakes(monkeypatch, exit_mode)

    main_module.main()

    orchestrator.stop.assert_called_once_with()
    manager.shutdown.assert_called_once_with()


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_main_signal_handler_and_finally_share_one_cleanup(monkeypatch, signum):
    manager, orchestrator = _install_main_runtime_fakes(
        monkeypatch,
        exit_mode="signal",
        signum=signum,
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 0
    orchestrator.stop.assert_called_once_with()
    manager.shutdown.assert_called_once_with()
