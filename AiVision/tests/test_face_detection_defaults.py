"""det_10g.onnx 人脸检测阈值默认值回归。"""


def test_det_10g_detection_threshold_defaults_are_unified(monkeypatch, tmp_path):
    """三个使用 det_10g.onnx 的功能必须使用同一检测置信度默认值。"""
    for name, value in {
        "MYSQL_DB_URL": "127.0.0.1",
        "MYSQL_DB_USER": "face_defaults_test",
        "MYSQL_DB_PASSWORD": "face_defaults_test",
        "MYSQL_DB_NAME": "face_defaults_test",
        "DATA_PATH": str(tmp_path),
        "AUTH_SECRET": "face-defaults-test-signing-key-0000000000",
    }.items():
        monkeypatch.setenv(name, value)

    from AiVision.features._shared.defaults import FACE_SCORE_THR
    from AiVision.features.face_dwell.orm import FaceConfigORM
    from AiVision.features.face_dwell.schema import FaceValueSchema
    from AiVision.features.face_recognition.orm import FaceRecognitionConfig
    from AiVision.features.face_recognition.schema import FaceRecognitionValue
    from AiVision.features.security_fence.orm import FenceConfigORM
    from AiVision.features.security_fence.schema import FenceValue
    from AiVision.inference.model_registry import MODEL_SPECS

    assert FACE_SCORE_THR == 0.8
    assert FaceValueSchema().FACE_SCORE_THR == 0.8
    assert FaceRecognitionValue().detection_threshold == 0.8
    assert FenceValue().detection_threshold == 0.8
    assert MODEL_SPECS["insightface_detection"].conf == 0.8
    assert MODEL_SPECS["insightface"].conf == 0.8
    assert str(FaceConfigORM.__table__.c.FACE_SCORE_THR.server_default.arg) == "0.8"
    assert str(FaceRecognitionConfig.__table__.c.detection_threshold.server_default.arg) == "0.8"
    assert str(FenceConfigORM.__table__.c.detection_threshold.server_default.arg) == "0.8"
