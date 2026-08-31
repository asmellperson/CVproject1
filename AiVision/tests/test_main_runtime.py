# 文件说明：包含程序启动、运行时的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import sys
from types import SimpleNamespace

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
