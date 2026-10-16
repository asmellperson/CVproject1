-- 外部系统凭证独立存储；也可由 bootstrap_database 创建此缺失表。
CREATE TABLE IF NOT EXISTS auth_external_clients (
    id VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    key_digest VARCHAR(64) NOT NULL,
    departments JSON NOT NULL,
    scopes JSON NOT NULL,
    enabled BOOL NOT NULL,
    expires_at DATETIME(6) NULL,
    created_by VARCHAR(64) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;
