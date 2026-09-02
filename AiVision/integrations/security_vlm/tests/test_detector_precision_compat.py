# 文件说明：包含`test_detector_precision_compat` 模块的自动化测试、测试夹具与断言辅助代码。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from AiVision.integrations.security_vlm.src.ultralytics_compat import yolo_precision_kwargs


# 功能：验证 `test_precision_kwargs_use_quantize_when_supported` 对应的`test_detector_precision_compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`yolo_precision_kwargs`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_precision_kwargs_use_quantize_when_supported():
    assert yolo_precision_kwargs(True, default_cfg={"quantize": None}) == {"quantize": 16}
    assert yolo_precision_kwargs(False, default_cfg={"quantize": None}) == {"quantize": None}


# 功能：验证 `test_precision_kwargs_keep_half_for_older_ultralytics` 对应的`test_detector_precision_compat` 模块逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`yolo_precision_kwargs`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
def test_precision_kwargs_keep_half_for_older_ultralytics():
    assert yolo_precision_kwargs(True, default_cfg={"half": False}) == {"half": True}
    assert yolo_precision_kwargs(False, default_cfg={"half": False}) == {"half": False}
