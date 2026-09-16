"""
AiVision 核心包
core/：配置、数据库、缓存、事件、日志和告警等公共基础能力

这些文件被 API、platform 服务、Consumer、运行管理器等模块共同使用。
core 提供基础能力，platform 负责组织资源与生命周期，features 负责具体检测业务，
api 负责 HTTP 请求与权限；不要因为名称叫 core，就把所有业务都堆到这个目录。
本文件只提供阅读说明，不聚合导入各子模块、不连接数据库、不启动进程或线程。
实际使用时从相应文件导入，例如 from AiVision.core.cache import config_cache。

一、先分清系统里的几类“配置”

    部署配置：settings.py 从环境变量 / .env 读取，例如数据库连接、存储路径、超时。
    系统业务配置：system_config.py 从 ai_system_config 读取，例如系统异常微信通知。
    资源与检测配置：各 platform 服务、FeatureConfig 读写自己的数据库表，
        例如摄像头、喇叭、物流通道、某台摄像头某项功能的 ROI 和报警绑定。
    固定定义：Department 名称来自 department_registry.py，功能来自 FeatureSpec，
        摄像头归属来自 Camera.department，模型定义来自 model_registry.py。
    本机模型文件位置：inference/model_paths.py 管理的 YAML 路径配置。
    配置缓存：cache.py 保存摄像头及 Feature 配置的运行副本，不是新的主数据来源。

    不同配置的更新方式不同：改数据库、改环境变量、改注册表、改 YAML，
    不能假设它们都会被同一个事件或同一次页面保存自动刷新。

二、settings.py：部署参数的统一读取入口

    通过 Pydantic BaseSettings 校验环境变量和 .env，再由 Settings 聚合为 settings。
    各字段的 alias 对应环境变量名；子配置通常忽略不属于自身的额外环境配置。

    DatabaseSettings / settings.db：数据库开关、主机、端口、账号、密码、库名、字符集，
        sqlalchemy_url 属性拼出 SQLAlchemy 连接字符串；AUTO_CREATE_DB 控制可选建库。
    StorageSettings / settings.storage：DATA_PATH、批量写入数量和间隔、媒体保留策略，
        以及告警视频的启用、前后时长、帧率、最大宽度。
    AlarmSettings / settings.alarm：企业微信凭据、卡片站点地址，喇叭 HTTP 超时、
        心跳间隔、播放冷却、队列容量、队列有效期和运行配置对账间隔。
        WECHAT_ENABLE 决定常规启动流程是否创建微信客户端，也用于 API 异常通知门控。
        当前喇叭运行链读取 AiHornConfig.enable 和检测绑定的 horn_enable；
        本文件虽仍声明 HORN_ENABLE / HORN_URL，现有管理器与分发器没有读取它们，
        不要把这两个旧字段当作当前全局设备的实际开关或地址来源。
    ApiSettings / settings.api：API 监听地址、端口及 CORS 来源配置。
    RuntimeSettings / settings.runtime：OpenCV 线程数、慢帧日志阈值、物流状态新鲜度、
        推理异常告警阈值，以及模型 Worker 就绪超时、Watchdog 周期与重启退避参数。
    ManagedVisualServiceSettings / settings.visual_services：Guard Room 与 Security VLM
        这两类集成视觉服务的配置文件位置，默认路径基于 AiVision/ 目录计算。
    ModelPathSettings / settings.model_paths：模型路径 YAML 的位置，由 MODEL_PATHS_CONFIG
        指定；具体逻辑模型和实际权重路径不在此文件逐项声明。

    Settings：组合上述子配置；get_settings() 通过 lru_cache 缓存；模块级 settings
    在导入 settings.py 时创建，因此必填数据库配置、DATA_PATH 缺失会在此时校验失败。
    Engine 是延迟创建的，但“导入配置时做校验”和“实际连接数据库”仍是两件事。
    修改环境变量或 .env 不会自动替换已导入的 settings 对象，部署时通常需要重启。
    测试中清除 get_settings 缓存也不会自动替换其他模块已经持有的 settings 引用。

三、db.py：共享 ORM 基类、数据库连接池和事务工具

    Base：所有本套 AiVision ORM 的声明基类，Base.metadata 汇总已导入的表定义。
    get_engine()：首次使用时创建 SQLAlchemy Engine，使用连接池、存活检测和回收策略；
        AUTO_CREATE_DB 开启时先尝试确保目标库存在。
    get_session_factory()：缓存 Session 工厂，关闭自动提交和自动 flush，
        expire_on_commit=False 让提交后的 ORM 已加载字段仍可使用。
    get_session()：创建一次 Session，调用方负责关闭；不要跨线程共用同一个 Session。
    session_scope()：提供 with 事务上下文，正常退出 commit，异常 rollback 并重新抛出，
        最后关闭 Session；适合服务层写操作。
    _ensure_database_exists()：校验库名、字符集，用临时服务器级连接执行可选建库，
        完成后释放临时 Engine；它和“在已有库中建表”是不同步骤。
    dispose()：释放当前 Engine 的连接池并重置全局工厂引用，供退出与测试清理使用。
        这不是强制终止所有正在使用的 Session，业务仍需先完成自己的资源关闭。

    事务顺序要明确：session.flush() 只是把 SQL 发给数据库，事务仍可能回滚。
    只有 session_scope 成功退出、提交完成后，才应刷新运行缓存和通知热更新。
    创建表依赖 ORM 已导入；只新增一个 ORM 文件却从未导入，不会自动登记到 metadata。
    启动时的业务 ORM 注册、缺失表创建与结构核验由 runtime/bootstrap.py 负责；
    db.py 不导入业务 ORM，也不向运行编排层反向导入。已有表不自动修补。

四、cache.py：摄像头与 Feature 配置的进程内读取副本

    ConfigCache / config_cache：缓存类与模块级单例，用来减少检测循环反复查询数据库。
    _camera_cache：按 camera_id 保存摄像头基础配置。
    _function_cache：按 (camera_id, feature_name) 保存功能配置，同摄像头各 Feature 独立。
    init()：先 _load_cameras()，再 _load_function_configs()，重复初始化由标志位控制。
    _load_function_configs()：遍历 features.registry.all_specs()，通过 spec.orm_class 查询配置表，
        新功能完成注册后即可被覆盖，不需要在缓存文件中硬编码每张功能表。
    _orm_to_dict()：仅把 ORM 表列转成字典，不附带 ORM Session 或关系加载对象。
    _enrich_function_config()：向功能字典注入 name、shm_name、camera_enable、department，
        让 Consumer 能直接定位视频帧、读取总开关和显示名称。
    get_camera_config() / get_function_config()：读取缓存，未命中返回 None。
    get_all_function_configs()：仅复制外层字典，内部配置仍是共享引用，不应原地修改。
    refresh_camera()：刷新摄像头及已缓存功能中的基础字段；摄像头被删除时移除关联缓存。
    refresh_function()：刷新单个摄像头的单项功能；数据库配置不存在时移除对应条目。
    reload()：清空后全量重读；当前不是跨两张缓存的原子快照替换。

    这是当前进程的普通 Python 字典，不是 Redis，也不是跨进程共享内存。
    它不缓存视频帧、不加载模型，不承担 Horn 实例表或物流通道自身运行配置的管理。
    读接口不主动查询数据库或订阅事件；是否刷新由服务层和运行事件处理流程明确调用。
    直接修改数据库不会自动让 Consumer 看到新值，直接修改缓存也不会持久化到数据库。

五、events.py：进程内配置变更通知

    ConfigChangeEvent：事件对象，包含 change_type、camera_id、camera_name、
        old_value、new_value；具体 payload 的含义由事件发布方和订阅方约定。
    ConfigEventBus / config_event_bus：事件总线类与单例，不是外部消息中间件。
    subscribe()：订阅精确事件；subscribe_prefix()：订阅一组名称前缀；
        subscribe_wildcard()：订阅所有事件；对应的三种 unsubscribe 方法负责解绑。
    publish()：锁内复制监听器，锁外同步回调，顺序为精确、前缀、通配符，
        同一回调被多种匹配命中时去重；某个监听器失败会记日志并继续后续监听器。

    publish 返回前，匹配的同步回调已经被调用；总线本身不创建消费线程。
    慢操作应由具体监听器安排到自己的后台执行器，避免拖住配置保存请求。
    总线不会自动 commit、自动刷新 ConfigCache，也不保证跨进程通知或持久化重试。
    常见链路是：服务先 commit → 刷新缓存 → publish → Orchestrator / Consumer 热更新。
    喇叭设备 CRUD 当前直接在提交后调用 HornRuntimeManager.sync()，不依赖这条事件总线。

六、logger.py：公共日志与功能级调试过滤

    logging.basicConfig()：配置标准日志格式；同时收窄部分第三方库的日志级别。
    _Logger / logger：项目日志包装器与单例，提供 debug/info/warning/error/exception。
        普通 aivision logger 默认 INFO；exception() 会记录异常堆栈。
    _parse_debug_features()：读取 DEBUG_FEATURES，支持逗号分隔的功能名或 all。
    set_debug_message(feature, msg)：只对名单中的功能打印高频调试信息，
        使用独立 debug logger，不要求把所有第三方和普通日志都调到 DEBUG。
    stacklevel=2：让日志中的文件和行号定位业务调用处，便于沿调用链排查。
    日志单例导入时读取调试白名单；它本身不提供后台动态重载白名单接口。

七、system_config.py：数据库中的系统异常通知配置

    AiSystemConfig：ai_system_config 表，key 为配置项名称，value 为 JSON 数据。
    SystemConfigService / system_config_service：访问服务与单例，目前主要管理 exception_alert。
    get_exception_alert()：读取微信开关、接收人、重复通知间隔；缺失时补默认字段。
    save_exception_alert()：规范化并保存配置，开启微信时必须有接收人。
    _normalize_exception_alert_interval()：约束重复间隔，当前范围 5 到 1440 分钟，
        默认 60 分钟；这不是摄像头 Feature 的 alarm_interval。
    _get_value() / _set_value()：封装查询及“存在则更新、缺失则新增”的事务写入。

    api/routes/exception_alerts.py 提供读写入口；Orchestrator 处理运行异常时读取它，
    api/app.py 处理 API 异常通知时也会读取它，再使用 WeChatNotifier.send_text()。
    凭据仍来自 settings，接收策略来自本表，实际重复告警时间记录由调用方维护。
    服务保存本表不会刷新摄像头缓存，也不会自行发布 ConfigChangeEvent。

八、runtime/process_cleanup.py（运行时目录）：启动前的 Linux 残留进程清理

    cleanup_aivision_residual_processes()：由 Orchestrator 在启动采集/推理前调用，
        输入当前配置的摄像头共享内存名、视频源地址和逻辑模型名。
    _find_residual_processes() / _read_cmdline()：扫描 /proc 的数字 PID 目录，读取命令行，
        跳过当前进程，以及读取时已退出或无权限读取的条目。
    _match_process()：匹配 Camera[shm_name]、ModelWorker[model_name]，或同时含有
        当前摄像头 URL、ffmpeg、rtsp_transport、rawvideo 的采集管线。
    _ProcessHit：保存匹配到的 PID、原因和命令行；_redact_cmdline() 脱敏后再输出日志。
    _safe_kill() / _is_alive()：先发 SIGTERM，限时等待；仍存活时再发 SIGKILL。
        最终返回匹配到的进程数量，不是逐个确认已成功退出的数量。
    这个模块实际会结束符合匹配规则的进程，不是只读状态检查，也不是持续 Watchdog。
    它不清理告警媒体和数据库；正常采集/推理退出及共享内存回收由各 Runtime 负责。

九、video_encoding.py：告警 MP4 的浏览器兼容处理

    VideoEncodingError：文件无效、程序缺失、探测/转码超时或失败时的统一异常。
    _run()：执行 ffprobe / ffmpeg，收集输出并限制超时，统一转换启动异常。
    _video_codec()：用 ffprobe 检查第一路视频的 codec_name 和 pix_fmt。
    ensure_browser_compatible_mp4(path)：检查文件存在且非空，取得进程内转码锁，
        已为 H.264 / yuv420p 时直接返回；其他或无法确认的编码尝试重新转码。
        ffmpeg 写入独立临时文件，使用 libx264、yuv420p、偶数尺寸和 faststart；
        该转码分支去除音轨，成功且输出非空后用 os.replace() 替换原文件，最后清理临时文件。
    _TRANSCODE_LOCK：同一进程内串行处理转码，并非整个部署的跨进程文件锁。

    调用方包括 alarms/evidence/evidence_recorder.py、api/routes/alarms.py 的视频访问，
    以及集成 Guard Room 的视频接口。它只处理已有视频，不负责采集原始摄像头画面，
    也不负责判断录像开始/结束时机，更不会把 Horn 的语音任务录成证据音轨。

十、与告警领域 AiVision.alarms 的协作

    alarms/__init__.py：告警职责及流程说明，不集中导入实现。
    alarms/dispatcher.py：AlarmRequest、业务冷却、证据入口及各通知通道协调。
    alarms/devices/：设备配置、绑定、运行管理及 horn.py 中的设备通信协议。
    alarms/notifications/：企业微信发送、token 缓存及通知缩略图签名。
    core 为告警模块提供 settings、logger、media_cleanup、video_encoding 等公共能力；
    告警记录与截图在 alarms/records/，视频证据在 alarms/evidence/，由 Orchestrator
    注入分发器，避免重复创建资源。

十一、把几个公共模块串起来看

    初始化：
        main → .env → settings → runtime/bootstrap.py 的 bootstrap_database()
            → mp.Manager → init_orchestrator → Orchestrator.start()
            → 摄像头和 Feature 配置准备 → config_cache.init()。
        开始运行时 → 清理匹配的残留进程 → 启动 Camera / Inference / Consumer / 物流
            等运行资源，并按 Orchestrator 的生命周期配置告警依赖。

    普通配置热更新：
        前端 → API 权限与结构校验 → Feature / Camera / Logistics 服务
            → session_scope 提交 → 缓存刷新 → ConfigChangeEvent
            → Orchestrator、Consumer 或物流运行时读取新配置。

    一次业务告警：
        Consumer / 物流检测规则 → AlarmRequest → AlarmDispatcher
            → 喇叭后台播放、告警数据库记录、截图/视频证据、微信卡片。

    一次系统异常：
        Camera / Inference / Consumer 监控或 API 异常处理
            → SystemConfigService 读取通知策略 → 调用方冷却控制
            → WeChatNotifier.send_text()；logger 同时记录排障信息。

    停止：
        Orchestrator 组织业务循环、运行实例、线程、写入与媒体任务退出，
        再释放数据库连接池；不要用 dispose() 代替这些模块各自的 stop()。

十二、后续修改与验证

    新增部署参数优先放 settings 对应分组；动态系统配置放 system_config 或所属服务。
    新增资源字段在所属 ORM/schema/service 中维护，不把 ConfigCache 当数据库写入口。
    新增配置事件要同时检查发布点、提交顺序、监听器注册与退出时解绑。
    新增检测功能先完成 FeatureSpec 注册，缓存会按注册表发现其 ORM。

    本目录改动可能影响启动、事务和所有检测功能，验证应按影响范围选择：
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_core_regressions.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_alarm_config_hot_update.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_wechat_news_card.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_horn_binding.py
    事务/启动等公共行为变化时，在项目根目录、已配置测试环境的 Python 中运行：
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests unified_backend/tests
    仅补充本文件说明时，检查 Python 语法及除文档字符串外的 AST 一致性即可；
    不需要为了验证注释而启动生产数据库、模型、摄像头或外部通知。
"""
