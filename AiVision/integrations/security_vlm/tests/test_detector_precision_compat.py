from ultralytics_compat import yolo_precision_kwargs


def test_precision_kwargs_use_quantize_when_supported():
    assert yolo_precision_kwargs(True, default_cfg={"quantize": None}) == {"quantize": 16}
    assert yolo_precision_kwargs(False, default_cfg={"quantize": None}) == {"quantize": None}


def test_precision_kwargs_keep_half_for_older_ultralytics():
    assert yolo_precision_kwargs(True, default_cfg={"half": False}) == {"half": True}
    assert yolo_precision_kwargs(False, default_cfg={"half": False}) == {"half": False}
