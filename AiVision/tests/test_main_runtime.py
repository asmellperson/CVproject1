import sys
from types import SimpleNamespace

from main import _configure_opencv_threads


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
