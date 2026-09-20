-- 停止 AiVision 后，对已存在的 AGV 配置表执行一次；新库使用 schema_mysql.sql。
ALTER TABLE ai_camera_config_agv_person_check
    ADD COLUMN alarm_interval FLOAT COMMENT '告警间隔(秒)',
    ADD COLUMN sql_enable BOOL COMMENT 'SQL告警启用',
    ADD COLUMN horn_enable BOOL COMMENT '喇叭告警启用',
    ADD COLUMN horn_id INTEGER COMMENT '喇叭设备ID',
    ADD COLUMN horn_event_id INTEGER COMMENT '告警音ID',
    ADD COLUMN wechat_enable BOOL COMMENT '微信告警启用',
    ADD COLUMN wechat_user VARCHAR(255) COMMENT '微信用户列表',
    ADD FOREIGN KEY (horn_id) REFERENCES ai_horn_config (id) ON DELETE SET NULL;

UPDATE ai_camera_config_agv_person_check
SET alarm_interval = 5.0, sql_enable = FALSE, horn_enable = FALSE, wechat_enable = FALSE;
