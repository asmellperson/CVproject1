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
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """
    数据库连接配置。

    必填项（无默认值，缺失时启动报错）: url、user、password、name。
    对应环境变量见各字段 alias。
    """
    enable: bool      = Field(True,      alias="SQL_ENABLE")
    url: str          = Field(...,        alias="MYSQL_DB_URL")
    port: int         = Field(3306,       alias="MYSQL_DB_PORT")
    user: str         = Field(...,        alias="MYSQL_DB_USER")
    password: str     = Field(...,        alias="MYSQL_DB_PASSWORD")
    name: str         = Field(...,        alias="MYSQL_DB_NAME")
    charset: str      = Field("utf8mb4",  alias="MYSQL_DB_CHARSET")
    # True 时若目标数据库不存在则自动 CREATE DATABASE（见 core.db._ensure_database_exists）
    auto_create: bool = Field(False,      alias="AUTO_CREATE_DB")

    @property
    def sqlalchemy_url(self) -> str:
        """拼装 SQLAlchemy 连接 URL，供 create_engine() 直接使用。"""
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.url}:{self.port}/{self.name}?charset={self.charset}"
        )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class StorageSettings(BaseSettings):
    """
    本地文件存储配置。

    data_path           : 违规截图等文件的根目录（必填）。
    max_event_count     : 异步写入器单批最大入库数量。
    flush_interval_seconds: 写入任务的批量落盘间隔（秒）。
    alarm_media_retention_days: 报警图片保留天数。
    alarm_media_max_gb  : 报警图片目录容量上限（GB）。
    alarm_media_cleanup_interval_minutes: 清理任务运行间隔（分钟）。
    """
    data_path: str              = Field(...,  alias="DATA_PATH")
    max_event_count: int        = Field(30,   alias="MAX_EVENT_COUNT")
    flush_interval_seconds: int = Field(5,    alias="INTERVAL")
    alarm_media_retention_days: int = Field(7, alias="ALARM_MEDIA_RETENTION_DAYS")
    alarm_media_max_gb: float = Field(10.0, alias="ALARM_MEDIA_MAX_GB")
    alarm_media_cleanup_interval_minutes: int = Field(
        60,
        alias="ALARM_MEDIA_CLEANUP_INTERVAL_MINUTES",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AlarmSettings(BaseSettings):
    """
    全局告警通道开关与凭据。

    Note:
        此处为系统级总开关；每个摄像头的功能配置中还有各自的细粒度开关，
        两者均启用时告警才真正触发。
        微信凭据留空时，WeChatNotifier 会静默跳过推送（见 core.alarm.wechat）。
    """
    horn_enable: bool       = Field(True,       alias="HORN_ENABLE")
    horn_url: str           = Field("http://localhost:8000/", alias="HORN_URL")
    wechat_enable: bool     = Field(True,        alias="WECHAT_ENABLE")
    wechat_corp_id: str     = Field("",          alias="WECHAT_CORP_ID")
    wechat_corp_secret: str = Field("",          alias="WECHAT_CORP_SECRET")
    wechat_agent_id: int    = Field(1000050,     alias="WECHAT_AGENT_ID")
    wechat_card_base_url: str = Field("https://aicv.fudar.com", alias="WECHAT_CARD_BASE_URL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class ApiSettings(BaseSettings):
    """
    FastAPI 服务器配置。

    cors_origins: 允许跨域的来源列表，默认 ["*"] 表示不限制；
                  生产环境建议收窄为实际前端域名。
    """
    host: str              = Field("0.0.0.0", alias="API_HOST")
    port: int              = Field(7862,       alias="API_PORT")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], alias="CORS_ORIGINS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class RuntimeSettings(BaseSettings):
    """
    AiVision 主进程的图像处理运行参数。

    OpenCV 默认按宿主机全部 CPU 创建内部线程池。在多摄像头、多 Consumer
    场景中，应用层已经存在并发，继续按全机核心数并行会造成线程争抢。
    """
    opencv_threads: int = Field(4, ge=1, alias="OPENCV_NUM_THREADS")
    slow_frame_log_seconds: float = Field(1.0, gt=0, alias="FRAME_SLOW_LOG_SECONDS")
    logistics_status_stale_seconds: float = Field(
        5.0,
        ge=0,
        alias="LOGISTICS_STATUS_STALE_SECONDS",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ManagedVisualServiceSettings(BaseSettings):
    """由 AiVision 同一进程承载的扩展视觉能力配置。"""

    repository_root: Path = Field(
        _REPOSITORY_ROOT,
        alias="VISUAL_SERVICES_REPOSITORY_ROOT",
    )
    guard_room_config_path: Path = Field(
        _REPOSITORY_ROOT / "guard_room" / "config" / "config.yaml",
        alias="GUARD_ROOM_CONFIG_PATH",
    )
    security_vlm_config_path: Path = Field(
        _REPOSITORY_ROOT / "security_vlm" / "configs" / "config.yaml",
        alias="SECURITY_VLM_CONFIG_PATH",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class ModelPathSettings(BaseSettings):
    """
    本机模型路径配置。

    模型文件路径只从此配置读取，不回退数据库 ai_model.path。
    这样同一套数据库可以部署到不同服务器，只需要调整本机配置文件。
    """
    config_path: str = Field("config/model_paths.yaml", alias="MODEL_PATHS_CONFIG")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class Settings:
    """
    配置聚合根，将各子配置组合为单一访问点。

    通过模块级单例 settings 访问，无需直接实例化本类：
        from core.settings import settings
        settings.db.sqlalchemy_url
        settings.alarm.horn_enable
    """
    def __init__(self):
        self.db      = DatabaseSettings()
        self.storage = StorageSettings()
        self.alarm   = AlarmSettings()
        self.api     = ApiSettings()
        self.runtime = RuntimeSettings()
        self.visual_services = ManagedVisualServiceSettings()
        self.model_paths = ModelPathSettings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    返回全局 Settings 单例（lru_cache 保证只实例化一次）。

    测试时若需覆盖配置，可调用 get_settings.cache_clear() 后再修改环境变量重新获取。
    """
    return Settings()


# 模块级单例，全项目统一从此处导入
settings = get_settings()
