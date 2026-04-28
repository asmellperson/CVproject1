import os
import sys
import time
import json
import signal
import importlib
import multiprocessing as mp
from pathlib import Path

ROOT = Path("/usr/zyy/Fuda_CVPreject")
AIVISION = ROOT / "AiVision"
ENV_FILE = AIVISION / ".env"

sys.path.insert(0, str(AIVISION))


def run_with_timeout(name, target, timeout=8):
    q = mp.Queue()

    def wrapper(q):
        try:
            ret = target()
            q.put(("ok", ret))
        except Exception as e:
            q.put(("err", repr(e)))

    p = mp.Process(target=wrapper, args=(q,), daemon=True)
    p.start()
    p.join(timeout)

    if p.is_alive():
        p.terminate()
        p.join(2)
        return {
            "name": name,
            "status": "timeout",
            "timeout_sec": timeout,
        }

    if q.empty():
        return {
            "name": name,
            "status": "no_result",
        }

    status, ret = q.get()
    return {
        "name": name,
        "status": status,
        "result": ret,
    }


def safe_len(x):
    try:
        return len(x)
    except Exception:
        return None


def obj_to_dict(x):
    if x is None:
        return None
    if isinstance(x, dict):
        return x
    if hasattr(x, "dict"):
        try:
            return x.dict()
        except Exception:
            pass
    if hasattr(x, "__dict__"):
        return {
            k: v
            for k, v in x.__dict__.items()
            if not k.startswith("_")
        }
    return {"value": str(x)}


def load_env_check():
    from dotenv import load_dotenv

    ok = load_dotenv(ENV_FILE)
    keys = [
        "MYSQL_DB_URL",
        "SQL_ENABLE",
        "DATA_PATH",
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_DATABASE",
        "MYSQL_DB",
    ]

    return {
        "env_file": str(ENV_FILE),
        "exists": ENV_FILE.exists(),
        "load_dotenv_ok": ok,
        "visible_keys": {
            k: ("<set>" if os.getenv(k) else None)
            for k in keys
        },
    }


def config_init_check():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)

    # 兼容不同写法
    import config
    if hasattr(config, "config_init"):
        fn = config.config_init
    else:
        from config import config_init
        fn = config_init

    t0 = time.time()
    ret = fn()
    cost = time.time() - t0

    info = {
        "cost_sec": round(cost, 3),
        "return_type": type(ret).__name__,
    }

    if isinstance(ret, tuple):
        info["tuple_len"] = len(ret)
        info["items"] = []
        for i, item in enumerate(ret):
            info["items"].append({
                "idx": i,
                "type": type(item).__name__,
                "len": safe_len(item),
                "sample": str(item)[:300],
            })
    elif isinstance(ret, dict):
        info["keys"] = list(ret.keys())
        for k, v in ret.items():
            info[f"{k}_type"] = type(v).__name__
            info[f"{k}_len"] = safe_len(v)
    else:
        info["repr"] = str(ret)[:1000]

    return info


def get_config_data():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)

    import config
    if hasattr(config, "config_init"):
        ret = config.config_init()
    else:
        from config import config_init
        ret = config_init()

    camera_cfg = None
    function_cfg = None
    model_cfg = None

    if isinstance(ret, tuple):
        # 根据之前日志：camera_cfg 1 function_cfg 5 model_cfg 4
        if len(ret) >= 3:
            camera_cfg = ret[0]
            function_cfg = ret[1]
            model_cfg = ret[2]
    elif isinstance(ret, dict):
        camera_cfg = ret.get("camera_cfg") or ret.get("camera_config") or ret.get("cameras")
        function_cfg = ret.get("function_cfg") or ret.get("function_config") or ret.get("functions")
        model_cfg = ret.get("model_cfg") or ret.get("model_config") or ret.get("models")

    return camera_cfg, function_cfg, model_cfg


def model_path_check():
    camera_cfg, function_cfg, model_cfg = get_config_data()

    rows = []
    if model_cfg is None:
        return {"error": "model_cfg is None"}

    if isinstance(model_cfg, dict):
        iterable = model_cfg.values()
    else:
        iterable = model_cfg

    for item in iterable:
        d = obj_to_dict(item)
        if d is None:
            continue

        name = d.get("name") or d.get("model_name") or d.get("model") or d.get("id")
        path = d.get("path") or d.get("model_path") or d.get("weight") or d.get("weights")
        worker = d.get("worker") or d.get("worker_path") or d.get("module") or d.get("class_path")

        exists = None
        size_mb = None
        if path:
            p = Path(str(path))
            exists = p.exists()
            if exists and p.is_file():
                size_mb = round(p.stat().st_size / 1024 / 1024, 2)

        rows.append({
            "name": str(name),
            "path": str(path),
            "exists": exists,
            "size_mb": size_mb,
            "worker": str(worker),
            "raw_keys": list(d.keys()),
        })

    return rows


def worker_import_check():
    _, _, model_cfg = get_config_data()

    modules = []
    if model_cfg is None:
        return {"error": "model_cfg is None"}

    iterable = model_cfg.values() if isinstance(model_cfg, dict) else model_cfg

    for item in iterable:
        d = obj_to_dict(item)
        if not d:
            continue
        for key in ["worker", "worker_path", "module", "class_path", "worker_class", "model_worker"]:
            val = d.get(key)
            if isinstance(val, str) and "." in val:
                # 如果是 package.module.Class，先取 module 部分
                parts = val.split(".")
                if len(parts) >= 2:
                    # 优先尝试完整模块；失败时再尝试去掉最后类名
                    modules.append(val)
                    modules.append(".".join(parts[:-1]))

    modules = sorted(set(modules))
    results = []

    for mod in modules:
        def do_import(m=mod):
            import importlib
            importlib.import_module(m)
            return "import ok"

        res = run_with_timeout(f"import {mod}", do_import, timeout=8)
        results.append(res)

    return results


def camera_check():
    camera_cfg, _, _ = get_config_data()

    if camera_cfg is None:
        return {"error": "camera_cfg is None"}

    if isinstance(camera_cfg, dict):
        iterable = camera_cfg.values()
    else:
        iterable = camera_cfg

    cams = []
    for item in iterable:
        d = obj_to_dict(item)
        if not d:
            continue

        cam_id = d.get("id") or d.get("camera_id") or d.get("name") or d.get("camera_name")
        url = (
            d.get("url")
            or d.get("rtsp")
            or d.get("rtsp_url")
            or d.get("video_url")
            or d.get("path")
            or d.get("source")
        )

        if url:
            cams.append({
                "id": str(cam_id),
                "url": str(url),
                "raw_keys": list(d.keys()),
            })

    results = []

    for cam in cams:
        def test_cam(c=cam):
            import cv2
            cap = cv2.VideoCapture(c["url"], cv2.CAP_FFMPEG)

            try:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
            except Exception:
                pass

            ok_open = cap.isOpened()
            ok_read = False
            shape = None

            if ok_open:
                ok_read, frame = cap.read()
                if ok_read and frame is not None:
                    shape = tuple(frame.shape)

            cap.release()

            return {
                "id": c["id"],
                "url_preview": c["url"][:80],
                "opened": ok_open,
                "read": ok_read,
                "shape": shape,
            }

        res = run_with_timeout(f"camera {cam['id']}", test_cam, timeout=6)
        results.append(res)

    return results


def main():
    print("\n========== AiVision 启动诊断 ==========")
    print(f"ROOT     = {ROOT}")
    print(f"AIVISION = {AIVISION}")
    print(f"ENV      = {ENV_FILE}")

    checks = [
        ("01_env", load_env_check, 5),
        ("02_config_init", config_init_check, 10),
        ("03_model_paths", model_path_check, 10),
        ("04_worker_imports", worker_import_check, 15),
        ("05_camera_read", camera_check, 15),
    ]

    final = {}
    for name, fn, timeout in checks:
        print(f"\n--- {name} ---")
        res = run_with_timeout(name, fn, timeout=timeout)
        final[name] = res
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    print("\n========== 诊断完成 ==========")


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)
    main()
