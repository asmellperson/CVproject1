"""
core/settings.py
统一配置入口 — Pydantic Settings,替代散落的 os.getenv 调用。

由主入口或 CLI 加载 AiVision/.env，保留已有环境变量；Settings 只读取环境变量和字段默认值。

使用:
    from AiVision.core.settings import settings
    settings.db.url      # 数据库地址
    settings.alarm.horn_enable
"""
from __future__ import annotations

from functools import lru_cache
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseSettings):
    """
    数据库连接配置。

    必填项（无默认值，缺失时启动报错）: url、user、password、name。
    alias：这个Python字段对应哪个环境变量
    比如settings.db.url实际上读取的是MySQL_DB_URL=xxxxxxx
    """
    enable: bool      = Field(True,      alias="SQL_ENABLE")          # 数据库功能总开关
    url: str          = Field(...,        alias="MYSQL_DB_URL")       # MySQL主机地址
    port: int         = Field(3306,       alias="MYSQL_DB_PORT")      # MySQL默认端口
    user: str         = Field(...,        alias="MYSQL_DB_USER")      # 数据库用户名
    password: str     = Field(...,        alias="MYSQL_DB_PASSWORD")  # 数据库密码
    name: str         = Field(...,        alias="MYSQL_DB_NAME")      # 数据库名
    charset: str      = Field("utf8mb4",  alias="MYSQL_DB_CHARSET")   # 字符集，默认utf8mb4，可以支持中文、Emoji、Unicode
    # 连接池等待、建连和 socket 读写均需有限时；业务层的逻辑超时不能中断被驱动卡住的线程。
    pool_timeout_seconds: int = Field(8, alias="MYSQL_DB_POOL_TIMEOUT_SECONDS", ge=1, le=60)
    connect_timeout_seconds: int = Field(8, alias="MYSQL_DB_CONNECT_TIMEOUT_SECONDS", ge=1, le=60)
    read_timeout_seconds: int = Field(8, alias="MYSQL_DB_READ_TIMEOUT_SECONDS", ge=1, le=60)
    write_timeout_seconds: int = Field(8, alias="MYSQL_DB_WRITE_TIMEOUT_SECONDS", ge=1, le=60)

    
    auto_create: bool = Field(False,      alias="AUTO_CREATE_DB")     # 如果数据库不存在，不要自动创建

    @property                                     # 访问时settings.db.sqlalchemy_url
    def sqlalchemy_url(self) -> str:
        """按数据库部署字段组合 SQLAlchemy 连接字符串；返回值含认证信息，不应直接写入日志。"""
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.url}:{self.port}/{self.name}?charset={self.charset}"
        )

    model_config = SettingsConfigDict(extra="ignore")

class StorageSettings(BaseSettings):
    """
    本地文件、告警配置、告警视频等存储相关配置。

    data_path           : 违规截图等文件的根目录（必填）。
    max_event_count     : 异步写入器单批最大入库数量。
    flush_interval_seconds: 写入任务的批量落盘间隔（秒）。  即使还没攒够max_event_count,多久也要强制刷一次
    alarm_media_retention_days: 报警媒体、识别截图与安检会话共用的保留天数，至少 31 天。
    alarm_media_max_gb  : 报警媒体和人脸识别截图的合计容量告警阈值（GB），不会触发提前删除。
    alarm_media_cleanup_interval_minutes: 清理任务运行间隔（分钟）。
    """
    data_path: str              = Field(...,  alias="DATA_PATH")
    max_event_count: int        = Field(30,   alias="MAX_EVENT_COUNT")
    flush_interval_seconds: int = Field(5,    alias="INTERVAL")
    recognition_record_queue_size: int = Field(32, ge=1, alias="RECOGNITION_RECORD_QUEUE_SIZE")
    alarm_db_write_attempts: int = Field(3, ge=1, alias="ALARM_DB_WRITE_ATTEMPTS")
    alarm_db_retry_backoff_seconds: float = Field(0.5, ge=0, alias="ALARM_DB_RETRY_BACKOFF_SECONDS")
    alarm_media_retention_days: int = Field(31, ge=31, alias="ALARM_MEDIA_RETENTION_DAYS")
    alarm_media_max_gb: float = Field(10.0, ge=0, alias="ALARM_MEDIA_MAX_GB")
    alarm_media_cleanup_interval_minutes: int = Field(
        60,
        alias="ALARM_MEDIA_CLEANUP_INTERVAL_MINUTES",
    )                                                                  # 每60分钟运行一次告警媒体清理
    alarm_clip_enabled: bool = Field(True, alias="ALARM_CLIP_ENABLED") # 告警视频开关
    alarm_clip_pre_seconds: float = Field(10.0, ge=0, alias="ALARM_CLIP_PRE_SECONDS")  # 告警发生前保留多少秒视频
    alarm_clip_post_seconds: float = Field(10.0, ge=0, alias="ALARM_CLIP_POST_SECONDS") # 报警之后再录10秒（一个报警片段大概前十秒 + 报警点 + 后十秒，大概20秒左右）
    alarm_clip_fps: float = Field(5.0, gt=0, alias="ALARM_CLIP_FPS")   # 告警视频输出FPS
    alarm_clip_max_width: int = Field(960, ge=160, alias="ALARM_CLIP_MAX_WIDTH")      # 告警录像最大宽度默认960像素
    alarm_clip_workers: int = Field(2, ge=1, le=2, alias="ALARM_CLIP_WORKERS")
    alarm_clip_max_tasks: int = Field(32, ge=1, alias="ALARM_CLIP_MAX_TASKS")  # 含采帧中、排队中和写入中的录像

    model_config = SettingsConfigDict(extra="ignore")

class AlarmSettings(BaseSettings):
    """
    全局告警通道开关与凭据。

    Note:
        此处为系统级总开关；每个摄像头的功能配置中还有各自的细粒度开关，
        两者均启用时告警才真正触发。
        微信凭据留空时，WeChatNotifier 会静默跳过推送（见 alarms.notifications.wechat）。
    """
    horn_enable: bool       = Field(True,       alias="HORN_ENABLE")              # 喇叭
    horn_url: str           = Field("http://localhost:8000/", alias="HORN_URL")
    horn_request_timeout_seconds: float = Field(5.0, gt=0, alias="HORN_REQUEST_TIMEOUT_SECONDS")
    horn_heartbeat_interval_seconds: float = Field(60.0, gt=0, alias="HORN_HEARTBEAT_INTERVAL_SECONDS")
    horn_play_cooldown_seconds: float = Field(1.0, ge=0, alias="HORN_PLAY_COOLDOWN_SECONDS")
    horn_queue_size: int = Field(100, gt=0, alias="HORN_QUEUE_SIZE")
    horn_queue_ttl_seconds: float = Field(10.0, gt=0, alias="HORN_QUEUE_TTL_SECONDS")
    horn_reconcile_interval_seconds: float = Field(5.0, gt=0, alias="HORN_RECONCILE_INTERVAL_SECONDS")
    horn_playback_workers: int = Field(4, ge=1, le=16, alias="HORN_PLAYBACK_WORKERS")
    horn_audio_max_bytes: int = Field(10 * 1024 * 1024, gt=0, alias="HORN_AUDIO_MAX_BYTES")
    horn_audio_max_seconds: float = Field(60.0, gt=0, le=300, alias="HORN_AUDIO_MAX_SECONDS")
    horn_audio_convert_timeout: float = Field(20.0, gt=0, alias="HORN_AUDIO_CONVERT_TIMEOUT")
    horn_sip_call_timeout: float = Field(10.0, gt=0, le=30, alias="HORN_SIP_CALL_TIMEOUT")
    horn_audio_ffmpeg: str = Field("ffmpeg", alias="HORN_AUDIO_FFMPEG")
    wechat_enable: bool     = Field(True,        alias="WECHAT_ENABLE")           # 企业微信
    wechat_corp_id: str     = Field("",          alias="WECHAT_CORP_ID")          # 企业ID
    wechat_corp_secret: str = Field("",          alias="WECHAT_CORP_SECRET")      # 应用Secrect
    wechat_agent_id: int    = Field(1000050,     alias="WECHAT_AGENT_ID")         # AgentID
    wechat_card_base_url: str = Field("https://aicv.fudar.com", alias="WECHAT_CARD_BASE_URL")
    wechat_thumbnail_ttl_seconds: int = Field(86400, ge=60, le=604800, alias="WECHAT_THUMBNAIL_TTL_SECONDS")

    model_config = SettingsConfigDict(extra="ignore")

class ApiSettings(BaseSettings):
    """
    FastAPI 服务器配置。

    cors_origins: 允许跨域的来源列表，默认 ["*"] 表示不限制；
                  生产环境建议收窄为实际前端域名。
    """
    host: str              = Field("0.0.0.0", alias="API_HOST")             # 监听本机所有网卡
    port: int              = Field(7862,       alias="API_PORT")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], alias="CORS_ORIGINS")     # 允许所有来源

    model_config = SettingsConfigDict(extra="ignore")


class CameraZoomSettings(BaseSettings):
    """镜头控制只使用服务器配置的管理端口，每次动作有固定时限。"""

    scheme: Literal["http", "https"] = Field("http", alias="CAMERA_ZOOM_SCHEME")
    port: int = Field(80, ge=1, le=65535, alias="CAMERA_ZOOM_PORT")
    request_timeout_seconds: float = Field(2.0, ge=0.2, le=5, alias="CAMERA_ZOOM_REQUEST_TIMEOUT_SECONDS")
    step_seconds: float = Field(0.25, ge=0.05, le=0.5, alias="CAMERA_ZOOM_STEP_SECONDS")
    speed_fraction: float = Field(0.2, gt=0, le=1, alias="CAMERA_ZOOM_SPEED_FRACTION")
    capability_cache_seconds: float = Field(30.0, ge=0, le=60, alias="CAMERA_ZOOM_CAPABILITY_CACHE_SECONDS")

    model_config = SettingsConfigDict(extra="ignore")


class PreviewSettings(BaseSettings):
    """普通监控使用原始视频，安检保留名单设置；媒体服务只允许部署在本机。"""

    base_url: str = Field("http://127.0.0.1:1984", alias="GO2RTC_BASE_URL")
    camera_key: str = Field("", alias="GO2RTC_PREVIEW_CAMERA_KEY")
    feature: str = Field("security_fence", min_length=1, alias="GO2RTC_PREVIEW_FEATURE")
    auth_check_seconds: float = Field(5.0, ge=1, le=5, alias="GO2RTC_AUTH_CHECK_SECONDS")

    @field_validator("camera_key")
    @classmethod
    def normalize_camera_keys(cls, value: str) -> str:
        """空名单关闭视频，非空名单逐项校验，避免空项意外放宽匹配范围。"""
        if not value.strip():
            return ""
        keys = [item.strip() for item in value.split(",")]
        if any(not re.fullmatch(r"camera_[1-9][0-9]*", key) for key in keys):
            raise ValueError("GO2RTC_PREVIEW_CAMERA_KEY 必须是逗号分隔的规范 camera_N，不能包含空项")
        return ",".join(dict.fromkeys(keys))

    @field_validator("feature")
    @classmethod
    def normalize_features(cls, value: str) -> str:
        """配置层仅验证标识格式，实际功能注册和用户授权仍由请求入口校验。"""
        features = [item.strip() for item in value.split(",")]
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", feature) for feature in features):
            raise ValueError("GO2RTC_PREVIEW_FEATURE 必须是逗号分隔的功能标识，不能包含空项")
        return ",".join(dict.fromkeys(features))

    @property
    def camera_keys(self) -> frozenset[str]:
        return frozenset(self.camera_key.split(",")) if self.camera_key else frozenset()

    @property
    def features(self) -> frozenset[str]:
        return frozenset(self.feature.split(","))

    @field_validator("base_url")
    @classmethod
    def require_loopback(cls, value: str) -> str:
        """禁止把数据库里的摄像头凭据发送给外部媒体服务或代理。"""
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username
                or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("GO2RTC_BASE_URL 必须是 http://127.0.0.1 的本机服务地址")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("GO2RTC_BASE_URL 端口无效")
        return value.rstrip("/")

    model_config = SettingsConfigDict(extra="ignore")


class RuntimeSettings(BaseSettings):
    """
    AiVision 主运行进程、推理Worker、运行时监控的一系列参数。

    OpenCV 默认按宿主机全部 CPU 创建内部线程池。在多摄像头、多 Consumer
    场景中，应用层已经存在并发，继续按全机核心数并行会造成线程争抢。
    """
    opencv_threads: int = Field(4, ge=1, alias="OPENCV_NUM_THREADS")      # 限制OpenCV自己内部最多开多少CPU线程
    # 覆盖最长 60 秒检测窗口和 10 秒回调，退出时先完成已接收的请求。
    shutdown_grace_seconds: int = Field(75, ge=1, le=600, alias="SHUTDOWN_GRACE_SECONDS")
    # 限制同时探测和等待首帧的路数，避免离线设备串行拖慢整个平台启动。
    camera_start_workers: int = Field(4, ge=1, le=16, alias="CAMERA_START_WORKERS")
    # 先统一通知退出，再有限并行回收，避免逐路累加 ffmpeg 的退出等待。
    camera_stop_workers: int = Field(8, ge=1, le=16, alias="CAMERA_STOP_WORKERS")
    qwen_max_concurrent_requests: int = Field(3, ge=1, le=16, alias="QWEN_MAX_CONCURRENT_REQUESTS")
    # 为其他功能保留共享模型队列空间，安检最多提前投递四路。
    security_inspection_inflight: int = Field(4, ge=1, le=4, alias="SECURITY_INSPECTION_INFLIGHT")
    # 输入队列刚满时短暂等待 Worker 取件，避免 20ms 瞬时拥塞直接丢弃当前帧。
    inference_queue_submit_wait_seconds: float = Field(
        0.1, ge=0.01, le=1.0, alias="INFERENCE_QUEUE_SUBMIT_WAIT_SECONDS",
    )
    # 非闯闸的人体任务共享这一普通通道，闯闸仍有独立保留通道。
    human_ordinary_queue_capacity: int = Field(
        16, ge=4, le=64, alias="HUMAN_ORDINARY_QUEUE_CAPACITY",
    )
    assistant_workers: int = Field(1, ge=1, le=4, alias="ASSISTANT_WORKERS")
    assistant_queue_capacity: int = Field(16, ge=1, le=64, alias="ASSISTANT_QUEUE_CAPACITY")
    assistant_max_rounds: int = Field(24, ge=1, le=48, alias="ASSISTANT_MAX_ROUNDS")
    # 规划、专家交接和工具循环共享整轮期限，不能随专家数量重新计时。
    assistant_task_timeout_sec: float = Field(300.0, ge=10, le=1800, alias="ASSISTANT_TASK_TIMEOUT_SEC")
    assistant_max_changes: int = Field(100, ge=1, le=200, alias="ASSISTANT_MAX_CHANGES")
    assistant_history_turns: int = Field(6, ge=0, le=20, alias="ASSISTANT_HISTORY_TURNS")
    assistant_history_max_chars: int = Field(8000, ge=1000, le=32000, alias="ASSISTANT_HISTORY_MAX_CHARS")
    assistant_plan_max_tokens: int = Field(1024, ge=256, le=4096, alias="ASSISTANT_PLAN_MAX_TOKENS")
    fence_inference_timeout_seconds: float = Field(5.0, gt=0, le=30, alias="FENCE_INFERENCE_TIMEOUT_SECONDS")
    # 每个模型分别限制在途请求，慢人脸不占用人体检测名额。
    fence_inflight: int = Field(4, ge=1, le=4, alias="FENCE_INFLIGHT")
    fence_horn_retry_seconds: float = Field(1.0, ge=0.1, le=30, alias="FENCE_HORN_RETRY_SECONDS")
    slow_frame_log_seconds: float = Field(1.0, gt=0, alias="FRAME_SLOW_LOG_SECONDS")   # 一次获取摄像头画面超过多少秒，就记慢请求日志
    # 物流通道状态多久没更新，就认为他过旧
    logistics_status_stale_seconds: float = Field(
        5.0,
        ge=0,
        alias="LOGISTICS_STATUS_STALE_SECONDS",
    ) 
    # 推理Worker连续失败几次以后才发系统异常告警
    inference_alert_consecutive_failures: int = Field(
        3,
        ge=1,
        alias="INFERENCE_ALERT_CONSECUTIVE_FAILURES",
    )
    # 推理异常报警冷却时间
    inference_alert_cooldown_seconds: float = Field(
        300.0,
        ge=0,
        alias="INFERENCE_ALERT_COOLDOWN_SECONDS",
    )
    # 启动模型Woker后，最多等多久认为它应该已经准备好
    model_worker_ready_timeout_seconds: float = Field(
        60.0,
        ge=0,
        alias="MODEL_WORKER_READY_TIMEOUT",
    )
    # watchdog多久检查一次Worker状态
    model_worker_watchdog_interval_seconds: float = Field(
        5.0,
        gt=0,
        alias="MODEL_WORKER_WATCHDOG_INTERVAL_SECONDS",
    )
    # Worker崩了以后，最多自动重启几次
    model_worker_restart_max_attempts: int = Field(
        3,
        ge=0,
        alias="MODEL_WORKER_RESTART_MAX_ATTEMPTS",
    )
    # 第一次重启前至少等多久
    model_worker_restart_backoff_seconds: float = Field(
        5.0,
        ge=0,
        alias="MODEL_WORKER_RESTART_BACKOFF_SECONDS",
    )
    # 重启失败后通常会逐渐延长等待时间，这里设置最大的等待时间
    model_worker_restart_max_backoff_seconds: float = Field(
        60.0,
        ge=0,
        alias="MODEL_WORKER_RESTART_MAX_BACKOFF_SECONDS",
    )
    # Worker如果稳定运行了足够久，就把以前的连续重启失败清掉
    model_worker_restart_reset_seconds: float = Field(
        300.0,
        ge=0,
        alias="MODEL_WORKER_RESTART_RESET_SECONDS",
    )

    model_config = SettingsConfigDict(extra="ignore")

class ModelPathSettings(BaseSettings):
    """
    本机模型路径配置。

    模型文件路径只从此配置读取，不回退数据库 ai_model.path。
    这样同一套数据库可以部署到不同服务器，只需要调整本机配置文件。
    """
    # 本机模型真实路径配置文件的位置
    config_path: str = Field("config/model_paths.yaml", alias="MODEL_PATHS_CONFIG")

    model_config = SettingsConfigDict(extra="ignore")


class JoyAISettings(BaseSettings):
    """外部视觉语言服务；业务请求只使用 Adapter 地址。"""

    adapter_url: str = Field("", alias="JOYAI_ADAPTER_URL")
    request_timeout_seconds: float = Field(45.0, ge=1, le=180, alias="JOYAI_REQUEST_TIMEOUT_SECONDS")
    max_workers: int = Field(4, ge=1, le=32, alias="JOYAI_MAX_WORKERS")
    question_timeout_seconds: float = Field(90.0, ge=1, le=600, alias="JOYAI_QUESTION_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(extra="ignore")


class Settings:
    """
    配置聚合根，将各子配置组合为单一访问点。

    通过模块级单例 settings 访问，无需直接实例化本类：
        from AiVision.core.settings import settings
        settings.db.sqlalchemy_url
        settings.alarm.horn_enable
    """
  
    def __init__(self):
        """从当前环境构造各配置分组；任何必填项缺失或类型校验失败都会中止构造。"""
        self.db      = DatabaseSettings()
        self.storage = StorageSettings()
        self.alarm   = AlarmSettings()
        self.api     = ApiSettings()
        self.camera_zoom = CameraZoomSettings()
        self.preview = PreviewSettings()
        self.runtime = RuntimeSettings()
        self.model_paths = ModelPathSettings()
        self.joyai = JoyAISettings()

# Settings只创建一次，后面重复调用直接返回缓存对象
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回 lru_cache 缓存的 Settings 实例。

    测试可清除缓存并在调整环境后重新获取；已有模块持有的 settings 引用不会
    因清缓存自动替换，生产环境修改环境变量通常需要重启进程。
    """
    return Settings()


# 模块级单例，全项目统一从此处导入
settings = get_settings()
