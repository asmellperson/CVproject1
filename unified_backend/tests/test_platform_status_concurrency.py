import threading
import time

import unified_backend.app as app_module


def test_get_json_concurrently_starts_upstream_requests_in_parallel(monkeypatch):
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_get_json(base_url, path, *, timeout=2.0, request=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return True, {"path": path}, 1.0, None

    monkeypatch.setattr(app_module, "_get_json", fake_get_json)

    results = app_module._get_json_concurrently({
        "one": ("http://one", "/health", None),
        "two": ("http://two", "/status", None),
        "three": ("http://three", "/cameras", None),
    })

    assert max_active >= 2
    assert results["one"][1] == {"path": "/health"}
    assert results["two"][1] == {"path": "/status"}
    assert results["three"][1] == {"path": "/cameras"}
