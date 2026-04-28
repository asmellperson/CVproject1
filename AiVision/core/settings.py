"""
core/settings.py
统一配置入口 — Pydantic Settings,替代散落的 os.getenv 调用。

加载顺序: 环境变量 > .env 文件 > 字段默认值

使用:
    from core.settings import settings
    settings.db.url      # 数据库地址
    settings.alarm.horn_enable
"""
from __future__ import annotations
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """数据库连接配置"""
    enable: bool = Field(True, alias="SQL_ENABLE")
    url: str = Field(..., alias="MYSQL_DB_URL")
    port: int = Field(3306, alias="MYSQL_DB_PORT")
    user: str = Field(..., alias="MYSQL_DB_USER")
    password: str = Field(..., alias="MYSQL_DB_PASSWORD")
    name: str = Field(..., alias="MYSQL_DB_NAME")
    charset: str = Field("utf8mb4", alias="MYSQL_DB_CHARSET")
    auto_create: bool = Field(False, alias="AUTO_CREATE_DB")

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.url}:{self.port}/{self.name}?charset={self.charset}"
        )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class StorageSettings(BaseSettings):
    """文件存储配置"""
    data_path: str = Field(..., alias="DATA_PATH")
    max_event_count: int = Field(30, alias="MAX_EVENT_COUNT")
    flush_interval_seconds: int = Field(5, alias="INTERVAL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AlarmSettings(BaseSettings):
    """全局告警通道开关(每摄像头还有自己的细粒度开关)"""
    horn_enable: bool = Field(True, alias="HORN_ENABLE")
    horn_url: str = Field("http://localhost:8000/", alias="HORN_URL")
    wechat_enable: bool = Field(True, alias="WECHAT_ENABLE")
    wechat_corp_id: str = Field("", alias="WECHAT_CORP_ID")
    wechat_corp_secret: str = Field("", alias="WECHAT_CORP_SECRET")
    wechat_agent_id: int = Field(1000050, alias="WECHAT_AGENT_ID")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class ApiSettings(BaseSettings):
    """API 服务器配置"""
    host: str = Field("0.0.0.0", alias="API_HOST")
    port: int = Field(7862, alias="API_PORT")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], alias="CORS_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class Settings:
    """聚合根 — 一个对象访问所有配置组"""
    def __init__(self):
        self.db = DatabaseSettings()
        self.storage = StorageSettings()
        self.alarm = AlarmSettings()
        self.api = ApiSettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
