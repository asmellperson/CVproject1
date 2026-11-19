-- 将使用 det_10g.onnx 的人脸检测默认值及已有摄像头配置统一为 0.8。
-- 请在停止 AiVision 后端及相关配置写入后执行；语句可重复执行。

ALTER TABLE `ai_camera_config_detect_face`
    ALTER COLUMN `FACE_SCORE_THR` SET DEFAULT 0.8;

ALTER TABLE `ai_camera_config_recognize_face`
    ALTER COLUMN `detection_threshold` SET DEFAULT 0.8;

ALTER TABLE `ai_camera_config_security_fence`
    ALTER COLUMN `detection_threshold` SET DEFAULT 0.8;

UPDATE `ai_camera_config_detect_face`
SET `FACE_SCORE_THR` = 0.8;

UPDATE `ai_camera_config_recognize_face`
SET `detection_threshold` = 0.8;

UPDATE `ai_camera_config_security_fence`
SET `detection_threshold` = 0.8;
