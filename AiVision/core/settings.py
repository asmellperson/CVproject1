# 文件说明：实现配置相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

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


# 功能：数据库连接配置；输入与输出详见下方说明
# 参数：
#   - `enable`（bool）：`enable` 对应的业务输入值
#   - `url`（str）：目标接口、媒体流或页面地址
#   - `port`（int）：`port` 对应的业务输入值
#   - `user`（str）：当前用户或待处理用户对象
#   - `password`（str）：`password` 对应的业务输入值
#   - `name`（str）：业务对象名称
#   - `charset`（str）：`charset` 对应的业务输入值
#   - `auto_create`（bool）：`auto_create` 对应的业务输入值
# 返回：DatabaseSettings；返回新建的 `DatabaseSettings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `Settings::__init__` 实例化本符号
#   - 内部调用：`Field`、`SettingsConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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

    # 功能：拼装 SQLAlchemy 连接 URL，供 create_engine() 直接使用；输入与输出详见下方说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：str；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
    # 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
    @property
    def sqlalchemy_url(self) -> str:
        """拼装 SQLAlchemy 连接 URL，供 create_engine() 直接使用。"""
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.url}:{self.port}/{self.name}?charset={self.charset}"
        )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 功能：本地文件存储配置；输入与输出详见下方说明
# 参数：
#   - `data_path`（str）：`data_path` 对应的业务输入值
#   - `max_event_count`（int）：`max_event_count` 对应的数量或大小
#   - `flush_interval_seconds`（int）：`flush_interval_seconds` 对应的时间间隔或时长
#   - `alarm_media_retention_days`（int）：`alarm_media_retention_days` 对应的业务输入值
#   - `alarm_media_max_gb`（float）：`alarm_media_max_gb` 对应的业务输入值
#   - `alarm_media_cleanup_interval_minutes`（int）：`alarm_media_cleanup_interval_minutes` 对应的时间间隔或时长
#   - `alarm_clip_enabled`（bool）：`alarm_clip_enabled` 对应的业务输入值
#   - `alarm_clip_pre_seconds`（float）：`alarm_clip_pre_seconds` 对应的时间间隔或时长
#   - `alarm_clip_post_seconds`（float）：`alarm_clip_post_seconds` 对应的时间间隔或时长
#   - `alarm_clip_fps`（float）：`alarm_clip_fps` 对应的业务输入值
#   - `alarm_clip_max_width`（int）：`alarm_clip_max_width` 对应的业务输入值
# 返回：StorageSettings；返回新建的 `StorageSettings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `Settings::__init__` 实例化本符号
#   - 内部调用：`Field`、`SettingsConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
    alarm_clip_enabled: bool = Field(True, alias="ALARM_CLIP_ENABLED")
    alarm_clip_pre_seconds: float = Field(10.0, ge=0, alias="ALARM_CLIP_PRE_SECONDS")
    alarm_clip_post_seconds: float = Field(10.0, ge=0, alias="ALARM_CLIP_POST_SECONDS")
    alarm_clip_fps: float = Field(5.0, gt=0, alias="ALARM_CLIP_FPS")
    alarm_clip_max_width: int = Field(960, ge=160, alias="ALARM_CLIP_MAX_WIDTH")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 功能：全局告警通道开关与凭据；输入与输出详见下方说明
# 参数：
#   - `horn_enable`（bool）：`horn_enable` 对应的业务输入值
#   - `horn_url`（str）：`horn_url` 对应的业务输入值
#   - `wechat_enable`（bool）：`wechat_enable` 对应的业务输入值
#   - `wechat_corp_id`（str）：`wechat_corp_id` 对应业务对象的唯一标识
#   - `wechat_corp_secret`（str）：`wechat_corp_secret` 对应的业务输入值
#   - `wechat_agent_id`（int）：`wechat_agent_id` 对应业务对象的唯一标识
#   - `wechat_card_base_url`（str）：`wechat_card_base_url` 对应的业务输入值
# 返回：AlarmSettings；返回新建的 `AlarmSettings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `Settings::__init__` 实例化本符号
#   - 内部调用：`Field`、`SettingsConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：FastAPI 服务器配置；输入与输出详见下方说明
# 参数：
#   - `host`（str）：`host` 对应的业务输入值
#   - `port`（int）：`port` 对应的业务输入值
#   - `cors_origins`（list[str]）：`cors_origins` 对应的业务输入值
# 返回：ApiSettings；返回新建的 `ApiSettings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `Settings::__init__` 实例化本符号
#   - 内部调用：`Field`、`SettingsConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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


# 功能：AiVision 主进程的图像处理运行参数；输入与输出详见下方说明
# 参数：
#   - `opencv_threads`（int）：`opencv_threads` 对应的业务输入值
#   - `slow_frame_log_seconds`（float）：`slow_frame_log_seconds` 对应的时间间隔或时长
#   - `logistics_status_stale_seconds`（float）：`logistics_status_stale_seconds` 对应的时间间隔或时长
#   - `inference_alert_consecutive_failures`（int）：`inference_alert_consecutive_failures` 对应的业务输入值
#   - `inference_alert_cooldown_seconds`（float）：`inference_alert_cooldown_seconds` 对应的时间间隔或时长
#   - `model_worker_ready_timeout_seconds`（float）：`model_worker_ready_timeout_seconds` 对应的时间间隔或时长
#   - `model_worker_watchdog_interval_seconds`（float）：`model_worker_watchdog_interval_seconds` 对应的时间间隔或时长
#   - `model_worker_restart_max_attempts`（int）：`model_worker_restart_max_attempts` 对应的业务输入值
#   - `model_worker_restart_backoff_seconds`（float）：`model_worker_restart_backoff_seconds` 对应的时间间隔或时长
#   - `model_worker_restart_max_backoff_seconds`（float）：`model_worker_restart_max_backoff_seconds` 对应的时间间隔或时长
#   - `model_worker_restart_reset_seconds`（float）：`model_worker_restart_reset_seconds` 对应的时间间隔或时长
# 返回：RuntimeSettings；返回新建的 `RuntimeSettings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `Settings::__init__` 实例化本符号
#   - 内部调用：`Field`、`SettingsConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
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
    inference_alert_consecutive_failures: int = Field(
        3,
        ge=1,
        alias="INFERENCE_ALERT_CONSECUTIVE_FAILURES",
    )
    inference_alert_cooldown_seconds: float = Field(
        300.0,
        ge=0,
        alias="INFERENCE_ALERT_COOLDOWN_SECONDS",
    )
    model_worker_ready_timeout_seconds: float = Field(
        60.0,
        ge=0,
        alias="MODEL_WORKER_READY_TIMEOUT",
    )
    model_worker_watchdog_interval_seconds: float = Field(
        5.0,
        gt=0,
        alias="MODEL_WORKER_WATCHDOG_INTERVAL_SECONDS",
    )
    model_worker_restart_max_attempts: int = Field(
        3,
        ge=0,
        alias="MODEL_WORKER_RESTART_MAX_ATTEMPTS",
    )
    model_worker_restart_backoff_seconds: float = Field(
        5.0,
        ge=0,
        alias="MODEL_WORKER_RESTART_BACKOFF_SECONDS",
    )
    model_worker_restart_max_backoff_seconds: float = Field(
        60.0,
        ge=0,
        alias="MODEL_WORKER_RESTART_MAX_BACKOFF_SECONDS",
    )
    model_worker_restart_reset_seconds: float = Field(
        300.0,
        ge=0,
        alias="MODEL_WORKER_RESTART_RESET_SECONDS",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_AIVISION_ROOT = Path(__file__).resolve().parents[1]


# 功能：由 AiVision 同一进程承载的扩展视觉能力配置；输入与输出详见下方说明
# 参数：
#   - `guard_room_config_path`（Path）：`guard_room_config_path` 对应的业务输入值
#   - `security_vlm_config_path`（Path）：`security_vlm_config_path` 对应的业务输入值
# 返回：ManagedVisualServiceSettings；返回新建的 `ManagedVisualServiceSettings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `Settings::__init__` 实例化本符号
#   - 内部调用：`Field`、`SettingsConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ManagedVisualServiceSettings(BaseSettings):
    """由 AiVision 同一进程承载的扩展视觉能力配置。"""

    guard_room_config_path: Path = Field(
        _AIVISION_ROOT / "integrations" / "guard_room" / "config" / "config.yaml",
        alias="GUARD_ROOM_CONFIG_PATH",
    )
    security_vlm_config_path: Path = Field(
        _AIVISION_ROOT / "integrations" / "security_vlm" / "configs" / "config.yaml",
        alias="SECURITY_VLM_CONFIG_PATH",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 功能：本机模型路径配置；输入与输出详见下方说明
# 参数：
#   - `config_path`（str）：`config_path` 对应的业务输入值
# 返回：ModelPathSettings；返回新建的 `ModelPathSettings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `Settings::__init__` 实例化本符号
#   - 内部调用：`Field`、`SettingsConfigDict`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class ModelPathSettings(BaseSettings):
    """
    本机模型路径配置。

    模型文件路径只从此配置读取，不回退数据库 ai_model.path。
    这样同一套数据库可以部署到不同服务器，只需要调整本机配置文件。
    """
    config_path: str = Field("config/model_paths.yaml", alias="MODEL_PATHS_CONFIG")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 功能：配置聚合根，将各子配置组合为单一访问点；输入与输出详见下方说明
# 参数：无。
# 返回：Settings；返回新建的 `Settings` 实例。
# 调用关系：
#   - 调用方：`AiVision/core/settings.py` 的 `get_settings` 实例化本符号
#   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
class Settings:
    """
    配置聚合根，将各子配置组合为单一访问点。

    通过模块级单例 settings 访问，无需直接实例化本类：
        from core.settings import settings
        settings.db.sqlalchemy_url
        settings.alarm.horn_enable
    """
    # 功能：初始化或配置 `__init__` 对应的配置逻辑；输入由参数提供，处理结果见返回值说明
    # 参数：
    #   - `self`（未显式标注）：当前类实例
    # 返回：None；初始化当前实例，不返回业务数据。
    # 调用关系：
    #   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
    #   - 内部调用：`DatabaseSettings`、`StorageSettings`、`AlarmSettings`、`ApiSettings`、`RuntimeSettings`、`ManagedVisualServiceSettings`、`ModelPathSettings`。
    # 副作用/注意事项：会更新当前实例的运行状态。
    def __init__(self):
        self.db      = DatabaseSettings()
        self.storage = StorageSettings()
        self.alarm   = AlarmSettings()
        self.api     = ApiSettings()
        self.runtime = RuntimeSettings()
        self.visual_services = ManagedVisualServiceSettings()
        self.model_paths = ModelPathSettings()


# 功能：返回全局 Settings 单例（lru_cache 保证只实例化一次）；输入与输出详见下方说明
# 参数：无。
# 返回：Settings；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`Settings`、`lru_cache`。
# 副作用/注意事项：无明显外部副作用；参数非法或下层调用失败时可能继续抛出异常。
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    返回全局 Settings 单例（lru_cache 保证只实例化一次）。

    测试时若需覆盖配置，可调用 get_settings.cache_clear() 后再修改环境变量重新获取。
    """
    return Settings()


# 模块级单例，全项目统一从此处导入
settings = get_settings()
