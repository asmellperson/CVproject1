"""摄像头包导入、ORM/功能注册与隔离 spawn 采集入口回归。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def isolated_environment(tmp_path):
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1",
        MYSQL_DB_URL="127.0.0.1", MYSQL_DB_USER="camera_package_test",
        MYSQL_DB_PASSWORD="test-only-unused", MYSQL_DB_NAME="camera_package_test",
        AUTO_CREATE_DB="false", DATA_PATH=str(tmp_path / "media"),
        AUTH_USERS_DB=str(tmp_path / "auth.sqlite"),
        UNIFIED_BACKEND_DATA_DIR=str(tmp_path / "backend"),
    )
    return env


@pytest.mark.parametrize("entry", [
    "AiVision.cameras.orm", "AiVision.cameras.config_manager",
    "AiVision.features", "AiVision.runtime.orchestrator",
])
def test_fresh_import_orders_keep_feature_and_orm_registration(entry, tmp_path):
    program = textwrap.dedent("""
        import importlib
        import importlib.util
        import json
        from pathlib import Path
        import sys
        import sqlalchemy

        def forbid_database(*args, **kwargs):
            raise AssertionError("module imports must not connect to a database")

        sqlalchemy.create_engine = forbid_database
        importlib.import_module(sys.argv[1])
        import AiVision.cameras as cameras
        import AiVision.features.registry as features
        from AiVision.core.db import Base
        from AiVision.cameras.orm import AiCameraConfig
        from sqlalchemy.orm import configure_mappers

        for module in ("config_manager", "orm", "runtime", "runtime_manager", "frame_reader", "probe"):
            imported = importlib.import_module(f"AiVision.cameras.{module}")
            assert Path(imported.__file__).parent == Path(cameras.__file__).parent
        for module in ("AiVision.alarms.devices.orm", "AiVision.alarms.records.orm", "AiVision.core.system_config"):
            importlib.import_module(module)
        configure_mappers()
        specs = features.all_specs()
        expected = {"blocks", "detect_door", "detect_face", "detect_human",
                    "detect_logistics_single_person", "detect_phone", "recognize_face"}
        assert set(specs) == expected
        assert Base.metadata.tables["ai_camera_config"] is AiCameraConfig.__table__
        assert AiCameraConfig.__module__ == "AiVision.cameras.orm"
        for spec in specs.values():
            assert Base.metadata.tables[spec.orm_class.__tablename__] is spec.orm_class.__table__
            assert any(fk.column.table is AiCameraConfig.__table__ for fk in spec.orm_class.__table__.foreign_keys)
        # 强制解析全部外键；不用创建或查询任何表。
        assert len(Base.metadata.sorted_tables) == len(Base.metadata.tables)
        # Check removed layout and loaded package hierarchy without resolving a retired import path.
        aivision_root = Path(importlib.util.find_spec("AiVision").origin).parent
        assert not (aivision_root / "platform").exists()
        assert not (aivision_root / "platform.py").exists()
        assert "platform" not in {name.split(".")[1] for name in sys.modules if name.startswith("AiVision.")}
        print(json.dumps({"features": sorted(specs), "tables": sorted(Base.metadata.tables)}))
    """)
    result = subprocess.run([sys.executable, "-c", program, entry], cwd=tmp_path,
                            env=isolated_environment(tmp_path), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "加载 features." not in result.stderr
    assert "ai_camera_config" in json.loads(result.stdout.splitlines()[-1])["tables"]
    assert not (tmp_path / "auth.sqlite").exists()


def test_spawn_loads_camera_entry_and_publishes_frames_without_real_camera(tmp_path):
    """只替换外部视频程序；实际 CameraRuntime.start/entry/stop 和帧读取器不打桩。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, source in {
        "ffprobe": 'import json\nprint(json.dumps({"streams": [{"width": 4, "height": 4}]}))\n',
        "ffmpeg": 'import os, time\nwhile True:\n    os.write(1, bytes([21, 42, 63]) * 16)\n    time.sleep(.02)\n',
    }.items():
        executable = bin_dir / name
        executable.write_text(f"#!{sys.executable}\n{source}")
        executable.chmod(0o700)

    script = tmp_path / "spawn_camera.py"
    script.write_text(textwrap.dedent("""
        import json
        import multiprocessing as mp
        from multiprocessing import shared_memory
        import os
        import time
        from uuid import uuid4

        from AiVision.cameras.runtime import CameraRuntime
        from AiVision.cameras.frame_reader import FrameReaderRegistry

        def main():
            mp.set_start_method("spawn", force=True)
            active_index, frame_seq = mp.Value("i", 0), mp.Value("Q", 0)
            shm_name = "camera_package_test_" + uuid4().hex
            runtime = CameraRuntime({"name": "isolated-camera", "shm_name": shm_name,
                                     "url": "rtsp://camera.test/stream", "fps": 10}, active_index, frame_seq)
            assert runtime.status and runtime.shape == (4, 4, 3)
            readers = FrameReaderRegistry()
            proc = None
            try:
                runtime.start(active_index, timeout=2, max_count=4)
                proc = runtime.proc
                assert proc.is_alive() and proc.pid != os.getpid()
                assert mp.get_start_method() == "spawn"
                assert readers.register(shm_name, runtime.shape, active_index, frame_seq)
                readers.start_all()
                deadline = time.monotonic() + 3
                while shm_name not in readers.latest_frames and time.monotonic() < deadline:
                    time.sleep(.01)
                frame = readers.latest_frames[shm_name]
                assert frame.shape == (4, 4, 3)
                assert frame[0, 0].tolist() == [21, 42, 63]
                assert not frame.flags.writeable
                assert frame_seq.value > 0
            finally:
                try:
                    readers.stop_all()
                finally:
                    runtime.stop()
            assert proc is not None and proc.exitcode == 0
            assert not proc.is_alive() and not runtime.running
            for suffix in ("_0", "_1"):
                try:
                    leftover = shared_memory.SharedMemory(name=shm_name + suffix)
                except FileNotFoundError:
                    continue
                else:
                    leftover.close()
                    leftover.unlink()
                    raise AssertionError("capture shared memory was not released")
            print(json.dumps({"entry_module": CameraRuntime._capture_entry.__module__, "spawn": True,
                              "frame_received": True, "resources_released": True}))

        if __name__ == "__main__":
            main()
    """))
    env = isolated_environment(tmp_path)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "entry_module": "AiVision.cameras.runtime", "spawn": True,
        "frame_received": True, "resources_released": True,
    }
