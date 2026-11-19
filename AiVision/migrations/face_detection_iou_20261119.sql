-- 设置人脸逗留检测列的默认值，已有摄像头配置继续使用各自保存的值。
ALTER TABLE `ai_camera_config_detect_face`
    ALTER COLUMN `DETECTION_IOU_THR` SET DEFAULT 0.45;
