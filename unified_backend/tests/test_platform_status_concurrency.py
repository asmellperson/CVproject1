# 文件说明：包含`test_platform_status_concurrency` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

import threading
import time

import unified_backend.app as app_module


# 功能：验证 `test_get_json_concurrently_starts_upstream_requests_in_parallel` 对应的`test_platform_status_concurrency`
#    模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `monkeypatch`（未显式标注）：`monkeypatch` 对应的业务输入值
# 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`threading.Lock`、`monkeypatch.setattr`、`app_module._get_json_concurrently`。
# 副作用/注意事项：可能启动、等待或停止线程/进程资源。
def test_get_json_concurrently_starts_upstream_requests_in_parallel(monkeypatch):
    lock = threading.Lock()
    active = 0
    max_active = 0

    # 功能：读取或查询 `fake_get_json` 对应的`test_platform_status_concurrency` 模块逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `base_url`（未显式标注）：`base_url` 对应的业务输入值
    #   - `path`（未显式标注）：目标路径
    #   - `timeout`（未显式标注）：允许操作等待的最长秒数；默认值为 `2.0`
    #   - `request`（未显式标注）：当前 HTTP 请求及上下文；默认值为 `None`
    # 返回：未显式标注（由实现推断）；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`max`、`time.sleep`。
    # 副作用/注意事项：会修改全局或闭包状态。
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
