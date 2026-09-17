"""保安行为配置的严格输入合同及独立导入边界。"""
import ast
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from AiVision.features.guard_behavior.constants import MAX_MODEL_IMGSZ, MIN_MODEL_IMGSZ, SITE_POLICY_DEFAULTS
from AiVision.features.guard_behavior.schema import (
    GuardBehaviorAlarmPolicyUpdate, GuardBehaviorCameraRoiUpdate,
    GuardBehaviorSitePolicySchema, GuardBehaviorSitePolicyUpdate, GuardBehaviorSiteUpdate,
)
from test_alarm_device_package import isolated_environment


def test_policy_defaults_are_exact_and_full_vehicle_selection_is_required():
    assert GuardBehaviorSitePolicySchema().model_dump() == dict(SITE_POLICY_DEFAULTS)
    with pytest.raises(ValueError, match="vehicle_camera_id"):
        GuardBehaviorSitePolicySchema(vehicle_inspection_enabled=True)
    with pytest.raises(ValueError, match="必须为 None"):
        GuardBehaviorSitePolicySchema(vehicle_camera_id=1)
    assert GuardBehaviorSitePolicySchema(vehicle_inspection_enabled=True, vehicle_camera_id=1).vehicle_camera_id == 1
    assert GuardBehaviorSitePolicyUpdate(phone_seconds=6).model_dump(exclude_unset=True) == {"phone_seconds": 6.}


@pytest.mark.parametrize("field", [
    "person_confidence_threshold", "phone_confidence_threshold", "uniform_confidence_threshold",
    "vehicle_confidence_threshold", "model_iou_threshold", "prone_head_down_ratio_threshold",
    "prone_bbox_height_ratio_threshold", "vehicle_direction_min_delta_ratio",
])
def test_probability_and_ratio_bounds(field):
    for valid in (0, 1, 0.25):
        assert getattr(GuardBehaviorSitePolicySchema(**{field: valid}), field) == valid
    for invalid in (-0.01, 1.01, True, "0.5", float("inf"), float("nan")):
        with pytest.raises(ValueError):
            GuardBehaviorSitePolicySchema(**{field: invalid})


@pytest.mark.parametrize("field", ["person_phone_imgsz", "phone_crop_imgsz", "pose_imgsz", "vehicle_imgsz"])
def test_image_sizes_are_bounded_strict_integers(field):
    for valid in (MIN_MODEL_IMGSZ, 640, MAX_MODEL_IMGSZ):
        assert getattr(GuardBehaviorSitePolicySchema(**{field: valid}), field) == valid
    for invalid in (MIN_MODEL_IMGSZ - 1, MAX_MODEL_IMGSZ + 1, 0, -1, 640.0, "640", True):
        with pytest.raises(ValueError):
            GuardBehaviorSitePolicySchema(**{field: invalid})


@pytest.mark.parametrize("field", [
    "cap_interval", "absent_alarm_seconds", "phone_seconds", "phone_window_seconds",
    "prone_sleep_seconds", "state_ttl_seconds", "vehicle_occlusion_seconds",
])
def test_trigger_durations_must_be_positive(field):
    assert getattr(GuardBehaviorSitePolicySchema(**{field: 0.1}), field) == 0.1
    for invalid in (0, -1, "1", True, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            GuardBehaviorSitePolicySchema(**{field: invalid})


@pytest.mark.parametrize("field", [
    "guard_hold_seconds", "phone_grace_seconds", "phone_near_person_px", "phone_near_head_px",
    "static_motion_threshold", "vehicle_near_px", "vehicle_reassociate_seconds",
])
def test_grace_periods_and_distances_accept_zero_but_not_negative(field):
    assert getattr(GuardBehaviorSitePolicySchema(**{field: 0}), field) == 0
    for invalid in (-1, "1", True, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            GuardBehaviorSitePolicySchema(**{field: invalid})


@pytest.mark.parametrize("field", ["phone_min_hits_in_window", "prone_consecutive_frames"])
def test_hit_counts_require_positive_integers(field):
    assert getattr(GuardBehaviorSitePolicySchema(**{field: 1}), field) == 1
    for invalid in (0, -1, 1.2, "1", True):
        with pytest.raises(ValueError):
            GuardBehaviorSitePolicySchema(**{field: invalid})


def test_vehicle_direction_and_camera_ids_are_strict():
    for value in ("any", "left", "right", "up", "down"):
        assert GuardBehaviorSitePolicySchema(vehicle_exit_direction=value).vehicle_exit_direction == value
    for value in ("ANY", "other", "", 1, None):
        with pytest.raises(ValueError):
            GuardBehaviorSitePolicySchema(vehicle_exit_direction=value)
    for value in (0, -1, "cam1", "1", True):
        with pytest.raises(ValueError):
            GuardBehaviorSitePolicySchema(vehicle_inspection_enabled=True, vehicle_camera_id=value)


@pytest.mark.parametrize("roi", [[], [[0, 0], [1, 0], [0, 1]], [[0.1, 0.2], [0.8, 0.2], [0.8, 0.9], [0.1, 0.9]]])
def test_roi_accepts_only_normalized_polygon_or_empty(roi):
    assert GuardBehaviorCameraRoiUpdate(vehicle_roi_pos=roi).vehicle_roi_pos == roi


@pytest.mark.parametrize("roi", [
    None, "[]", {}, {"points": [[0, 0], [1, 0], [0, 1]]},
    [[0, 0]], [[0, 0], [1, 1]], [[0, 0], [640, 0], [0, 480]],
    [[-0.1, 0], [1, 0], [0, 1]], [[0, 0], [1.1, 0], [0, 1]],
    [["0", 0], [1, 0], [0, 1]], [[True, 0], [1, 0], [0, 1]],
    [[0, 0, 0], [1, 0], [0, 1]], [[0, 0], [1, 0], [float("nan"), 1]],
    ((0, 0), (1, 0), (0, 1)), [[0, 0], [0.5, 0.5], [1, 1]],
])
def test_roi_rejects_bad_structure_pixels_strings_and_out_of_range(roi):
    with pytest.raises(ValueError):
        GuardBehaviorCameraRoiUpdate(vehicle_roi_pos=roi)


def test_unknown_fields_null_updates_and_invalid_alarm_values_are_rejected():
    for schema, payload in (
        (GuardBehaviorSiteUpdate, {"department": "general_electric"}),
        (GuardBehaviorSiteUpdate, {"enabled": None}),
        (GuardBehaviorSiteUpdate, {"description": "removed"}),
        (GuardBehaviorSitePolicySchema, {"device": "cpu"}),
        (GuardBehaviorSitePolicySchema, {"video_json": {}}),
        (GuardBehaviorAlarmPolicyUpdate, {"alarm_interval": 0}),
        (GuardBehaviorAlarmPolicyUpdate, {"alarm_interval": None}),
        (GuardBehaviorAlarmPolicyUpdate, {"horn_id": True}),
        (GuardBehaviorAlarmPolicyUpdate, {"wechat_enable": "true"}),
        (GuardBehaviorAlarmPolicyUpdate, {"wechat_user": "x" * 256}),
    ):
        with pytest.raises(ValueError):
            schema.model_validate(payload)


def test_data_package_import_does_not_register_feature_alarm_types_or_start_models(tmp_path):
    program = textwrap.dedent("""
        import importlib.abc
        import multiprocessing.process
        import socket
        import sys
        import threading
        import sqlalchemy

        def forbid(*args, **kwargs):
            raise AssertionError('data package import must not perform external operations')
        sqlalchemy.create_engine = forbid
        threading.Thread.start = forbid
        multiprocessing.process.BaseProcess.start = forbid
        socket.socket.connect = forbid

        class ImportBoundary(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.startswith('AiVision.integrations.') or fullname.split('.')[0] in {'torch', 'timm', 'ultralytics'}:
                    raise AssertionError('forbidden dependency: ' + fullname)
        sys.meta_path.insert(0, ImportBoundary())
        from AiVision.features.guard_behavior import constants, orm, schema, service, tracking
        from AiVision.features.guard_behavior.spec import SPEC
        from AiVision.core import db
        from AiVision.features.registry import all_specs
        from AiVision.alarms.types import VIOLATION_TYPE_META
        from AiVision.inference.runtime_manager import InferenceRuntimeManager
        assert 'guard_behavior' not in all_specs()
        assert set(VIOLATION_TYPE_META) == set(range(1, 8))
        assert SPEC.name == 'guard_behavior' and SPEC.alarm_types == (8, 9, 10, 11)
        assert SPEC.required_models == ('yolo_guard_person_phone', 'guard_uniform')
        assert SPEC.optional_models == ('yolo_guard_pose', 'yolo_vehicle')
        manager = InferenceRuntimeManager()
        future = {'guard_uniform', 'yolo_guard_pose', 'yolo_guard_person_phone', 'yolo_vehicle'}
        assert not manager._required_model_names().intersection(future)
        assert not manager._declared_model_names().intersection(future)
        assert not manager._workers and not db._engine and not db._session_factory
        assert service.GuardBehaviorService()
    """)
    result = subprocess.run([sys.executable, "-c", program], cwd=tmp_path,
                            env=isolated_environment(tmp_path), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_data_package_contains_only_expected_modules_and_no_retired_dependencies():
    directory = Path(__file__).resolve().parents[1] / "features" / "guard_behavior"
    assert {path.name for path in directory.glob("*.py")} == {
        "__init__.py", "constants.py", "orm.py", "schema.py", "service.py", "spec.py",
        "consumer.py", "state.py", "behavior.py", "pose_features.py", "tracking.py",
    }
    forbidden = ("AiVision.integrations.guard_room", "GuardRoomSite", "GuardRoomCamera", "GuardRoomSiteConfig", "AppConfig")
    for path in directory.glob("*.py"):
        source = path.read_text()
        assert not any(name in source for name in forbidden)
        imports = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
        assert not any((node.module or "").startswith("AiVision.features.logistics_channel") for node in imports)


def test_camera_feature_schema_contains_only_enable_and_vehicle_roi():
    from AiVision.features.guard_behavior.schema import GuardBehaviorCameraConfigSchema

    assert GuardBehaviorCameraConfigSchema().model_dump() == {"enable": False, "value": {"vehicle_roi_pos": []}}
    assert GuardBehaviorCameraConfigSchema.model_validate({"enable": True, "value": {"vehicle_roi_pos": []}}).enable
    for payload in ({"roi_pos": []}, {"policy": {}}, {"value": {"cap_interval": 1}},
                    {"value": {"vehicle_roi_pos": [[20, 30], [40, 30], [40, 50]]}}):
        with pytest.raises(ValueError):
            GuardBehaviorCameraConfigSchema.model_validate(payload)
