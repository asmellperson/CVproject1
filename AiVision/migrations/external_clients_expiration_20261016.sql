-- NULL 表示凭证永不过期；保留已有凭证的到期时间和全部授权信息。
ALTER TABLE auth_external_clients MODIFY COLUMN expires_at DATETIME(6) NULL;
