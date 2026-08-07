from types import SimpleNamespace

import numpy as np
import pytest

from features._base.logistics_single_person_consumer import (
    LogisticsSinglePersonConsumerBase,
    build_monitor_snapshot,
)
from features.detect_logistics_single_person.consumer import LogisticsSinglePersonConsumer
from features.detect_logistics_single_person_electrical_components.consumer import (
    LogisticsSinglePersonElectricalComponentsConsumer,
)
from features.detect_logistics_single_person_electronics_electrician.consumer import (
    LogisticsSinglePersonElectronicsElectricianConsumer,
)
from features.detect_logistics_single_person_precious_metal_recycling.consumer import (
    LogisticsSinglePersonPreciousMetalRecyclingConsumer,
)


LOGISTICS_CONSUMER_CLASSES = (
    LogisticsSinglePersonConsumer,
    LogisticsSinglePersonElectronicsElectricianConsumer,
    LogisticsSinglePersonElectricalComponentsConsumer,
    LogisticsSinglePersonPreciousMetalRecyclingConsumer,
)


class RuntimeSpy:
    def __init__(self, *, should_run=True):
        self.should_run = should_run
        self.schedule_calls = []
        self.snapshot_calls = []
        self.evaluate_calls = []

    def camera_should_run(self, feature_name, camera_id):
        self.schedule_calls.append((feature_name, camera_id))
        return self.should_run

    def update_camera_snapshot(self, feature_name, snapshot, annotated_frame):
        self.snapshot_calls.append((feature_name, snapshot, annotated_frame))

    def evaluate_after_camera_update(self, feature_name, camera_id):
        self.evaluate_calls.append((feature_name, camera_id))


def build_consumer(consumer_class, *, runtime=None):
    consumer = object.__new__(consumer_class)
    consumer.spec = SimpleNamespace(required_models=("person-detector",))
    consumer.feature_name = "detect_logistics_single_person"
    consumer.logistics_runtime = runtime
    consumer.config_cache = {
        7: {
            "name": "Camera 7",
            "shm_name": "cam-7",
            "value": {
                "CONF_THRESHOLD": 0.4,
                "IOU_THR": 0.3,
                "MIN_BOX_AREA": 0,
                "ASPECT_RATIO_RANGE": [0, 10],
            },
        }
    }
    consumer.frame_cache = {}
    consumer.monitor_status = {}
    consumer._masks = {}
    consumer._roi_polygon_cache = {}
    consumer.is_camera_active = lambda _camera_key: True
    return consumer


@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_share_the_common_implementation(consumer_class):
    assert issubclass(consumer_class, LogisticsSinglePersonConsumerBase)
    assert "_process" not in consumer_class.__dict__
    assert "post_process" not in consumer_class.__dict__


@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_publish_details_without_camera_alarm(consumer_class):
    consumer = build_consumer(consumer_class)
    consumer.dispatch_inference_sync = lambda *_args, **_kwargs: [
        {
            "roi_id": 0,
            "detections": [
                {"type": "person", "bbox": [1, 2, 21, 62], "confidence": 0.9},
                {"type": "human", "bbox": [30, 2, 50, 62], "confidence": 0.8},
            ],
        }
    ]

    result = consumer._process([np.zeros((64, 64, 3), dtype=np.uint8)], camera_id=7)

    assert all(alarm is False for alarm, _detail in result)
    assert sum(len(detail["detections"]) for _alarm, detail in result) == 2
    assert result[0][1]["reason"] == "multiple"
    assert result[0][1]["person_count"] == 2


def test_process_preserves_model_and_camera_filter_configuration():
    consumer = build_consumer(LogisticsSinglePersonConsumer)
    dispatched = {}

    def dispatch(camera_id, model_name, roi_list, task_meta):
        dispatched.update(
            camera_id=camera_id,
            model_name=model_name,
            roi_list=roi_list,
            task_meta=task_meta,
        )
        return [
            {
                "roi_id": 0,
                "detections": [
                    {"type": "vehicle", "bbox": [0, 0, 50, 50], "confidence": 0.9},
                    {"type": "person", "bbox": [0, 0, 1, 1], "confidence": 0.9},
                    {"type": "person", "bbox": [2, 2, 22, 62], "confidence": 0.8},
                ],
            }
        ]

    consumer.config_cache[7]["value"]["MIN_BOX_AREA"] = 100
    consumer.dispatch_inference_sync = dispatch
    roi = np.zeros((64, 64, 3), dtype=np.uint8)

    result = consumer._process([roi], camera_id=7)

    assert dispatched == {
        "camera_id": 7,
        "model_name": "person-detector",
        "roi_list": [roi],
        "task_meta": {"conf": 0.4, "iou": 0.3},
    }
    assert [item["bbox"] for item in result[0][1]["detections"]] == [[2, 2, 22, 62]]


def test_post_process_deduplicates_overlapping_rois_and_publishes_snapshot():
    runtime = RuntimeSpy()
    consumer = build_consumer(LogisticsSinglePersonConsumer, runtime=runtime)
    consumer.frame_cache[7] = np.zeros((100, 100, 3), dtype=np.uint8)
    consumer._roi_polygon_cache[7] = [
        [[0, 0], [60, 0], [60, 90], [0, 90]],
        [[10, 10], [70, 10], [70, 100], [10, 100]],
    ]
    consumer._masks[7] = [
        (None, 0, 90, 0, 60),
        (None, 10, 100, 10, 70),
    ]
    result = [
        (
            False,
            {
                "reason": "normal",
                "person_count": 1,
                "detections": [
                    {"type": "person", "bbox": [20, 20, 50, 80], "confidence": 0.9}
                ],
            },
        ),
        (
            False,
            {
                "reason": "normal",
                "person_count": 1,
                "detections": [
                    {"type": "person", "bbox": [10, 10, 40, 70], "confidence": 0.8}
                ],
            },
        ),
    ]

    annotated = consumer.post_process(7, result)

    assert annotated.shape == (100, 100, 3)
    assert np.any(annotated)
    assert len(runtime.snapshot_calls) == 1
    feature_name, snapshot, published_frame = runtime.snapshot_calls[0]
    assert feature_name == consumer.feature_name
    assert snapshot.camera_id == 7
    assert snapshot.camera_name == "Camera 7"
    assert snapshot.count == 1
    assert snapshot.online is True
    assert snapshot.updated_at > 0
    assert published_frame is annotated
    assert consumer.get_monitor_status("cam-7")["count"] == 1


def test_missing_roi_result_publishes_unknown_snapshot():
    runtime = RuntimeSpy()
    consumer = build_consumer(LogisticsSinglePersonConsumer, runtime=runtime)
    consumer.frame_cache[7] = np.zeros((40, 40, 3), dtype=np.uint8)
    consumer._roi_polygon_cache[7] = [
        [[0, 0], [20, 0], [20, 20], [0, 20]],
        [[20, 20], [40, 20], [40, 40], [20, 40]],
    ]
    consumer._masks[7] = [
        (None, 0, 20, 0, 20),
        (None, 20, 40, 20, 40),
    ]

    consumer.post_process(
        7,
        [
            (False, {"reason": "empty", "person_count": 0, "detections": []}),
            (False, {"reason": "unknown", "person_count": None, "detections": []}),
        ],
    )

    assert runtime.snapshot_calls[0][1].count is None
    assert consumer.get_monitor_status("cam-7")["reason"] == "unknown"


def test_schedule_and_channel_evaluation_are_delegated_to_runtime():
    runtime = RuntimeSpy(should_run=False)
    consumer = build_consumer(LogisticsSinglePersonConsumer, runtime=runtime)

    assert consumer._should_process_now(7, consumer.config_cache[7]) is False
    consumer._handle_alarm(7, [(False, {})], None)

    assert runtime.schedule_calls == [(consumer.feature_name, 7)]
    assert runtime.evaluate_calls == [(consumer.feature_name, 7)]


@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_require_channel_runtime(consumer_class):
    spec = SimpleNamespace(
        name=f"test_{consumer_class.__name__}",
        required_models=("person-detector",),
    )

    with pytest.raises(RuntimeError, match=consumer_class.__name__) as raised:
        consumer_class(
            spec=spec,
            infer_dict={},
            result_queue=None,
            latest_frames={},
            is_camera_active=lambda _camera_key: True,
        )

    assert "LogisticsChannelRuntime" in str(raised.value)


@pytest.mark.parametrize("consumer_class", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_accept_injected_channel_runtime(consumer_class):
    runtime = RuntimeSpy()
    spec = SimpleNamespace(
        name=f"test_{consumer_class.__name__}",
        required_models=("person-detector",),
    )

    consumer = consumer_class(
        spec=spec,
        infer_dict={},
        result_queue=None,
        latest_frames={},
        is_camera_active=lambda _camera_key: True,
        logistics_runtime=runtime,
    )

    assert consumer.logistics_runtime is runtime


def test_monitor_snapshot_sums_known_roi_counts_and_preserves_alarm():
    snapshot = build_monitor_snapshot(
        [
            (False, {"reason": "normal", "person_count": 1}),
            (True, {"reason": "multiple", "person_count": 2}),
        ],
        updated_at=100.0,
    )

    assert snapshot == {
        "count": 3,
        "alarm": True,
        "reason": "multiple",
        "updated_at_s": 100.0,
    }
