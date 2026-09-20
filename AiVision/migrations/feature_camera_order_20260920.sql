-- 停止 AiVision 并备份数据库后执行一次；全新数据库使用 schema_mysql.sql。

-- 以现有平台顺序初始化，各功能后续独立保存，不修改检测参数、ROI 和启用状态。

ALTER TABLE ai_camera_config_blocks
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_blocks AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;

ALTER TABLE ai_camera_config_detect_door
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_detect_door AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;

ALTER TABLE ai_camera_config_detect_face
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_detect_face AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;

ALTER TABLE ai_camera_config_detect_human
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_detect_human AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;

ALTER TABLE ai_camera_config_detect_phone
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_detect_phone AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;

ALTER TABLE ai_camera_config_recognize_face
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_recognize_face AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;

ALTER TABLE ai_camera_config_security_inspection
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_security_inspection AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;

ALTER TABLE ai_camera_config_agv_person_check
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0 COMMENT '功能内摄像头展示排序';

UPDATE ai_camera_config_agv_person_check AS config
JOIN ai_camera_config AS camera ON camera.id = config.camera_id
SET config.sort_order = camera.sort_order;
