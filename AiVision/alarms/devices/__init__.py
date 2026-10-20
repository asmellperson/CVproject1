"""
alarms/devices/：喇叭设备配置、检测绑定校验、运行管理与设备通信

这个包管理“现场有哪些喇叭、配置保存在哪里、哪些设备需要运行”。
真正的设备 HTTP 协议由 alarms/devices/horn.py 实现，某次违规应该通知哪些通道，
由 alarms/dispatcher.py 决定。本文件只作说明，不导入服务、不启动线程。

一、先分清设备、检测绑定和运行实例

    AiHornConfig：数据库中的一台全局设备，保存地址、账号、密码和设备 enable。
    FeatureConfig / LogisticsChannel：保存“这项检测使用哪台设备、哪个语音任务”。
    Horn：一台设备当前的登录会话、心跳线程、连接状态与播放能力。
    HornRuntimeManager：按数据库设备 id 管理这些 Horn 实例及后台播放队列。

    设备 enable：这台全局喇叭是否允许投入运行，影响所有引用它的检测配置。
    绑定 horn_enable：当前“摄像头 × Feature”或当前物流通道是否使用喇叭告警。
    绑定 horn_id：AiHornConfig.id，不是摄像头 ID，也不是语音文件编号。
    绑定 horn_event_id：设备自身预先配置的语音任务 ID，不是平台告警记录 ID。

    一台 Horn 可以被多个 Feature、多台摄像头、多个物流通道共同使用。
    关闭某项检测的 horn_enable 不会停用全局设备，也不会自动清空两个 ID。
    管理器只为全局 enable=True 的设备创建运行实例，不要求设备先被检测配置引用。

二、每个文件以及内部关键对象负责什么

    horn.py：单台设备的登录、心跳、重连、播放与停止门控，详见第六节。

    orm.py：设备主表的 SQLAlchemy 映射。
        AiHornConfig 对应 ai_horn_config，一行是一台设备。
        id 为整数主键；name 为唯一名称；url 为设备 HTTP/HTTPS 地址。
        username、password 用于设备登录；enable 控制设备启停；description 为备注。
        created_at / updated_at 记录建档、修改时间；__repr__ 不输出账号密码。
        username 可默认 admin，但 password 没有隐式默认密码，新增必须明确填写。
        password 当前是数据库字符串列；API 隐藏密码不等于数据库已经加密保存。
        ORM 不负责连接设备、播放声音或管理线程。

    schema.py：API 与服务写入时使用的数据结构和字段校验。
        HornFields：公共校验，限制名称、用户名非空和设备地址格式，拒绝多余字段。
            地址不能夹带账号密码、查询参数或片段；凭据应通过独立字段传入。
            write_values() 只导出调用方实际提供的字段，在内部写入时取出 SecretStr。
        HornCreate：新增设备请求，密码必填，包含名称、地址、账号、启用状态、备注。
        HornUpdate：局部更新请求；未提供的字段不改，空密码由服务层解释为保留原值。
        HornConnectionTest：无声连接测试请求，可引用已保存设备并临时覆盖连接字段。
        HornRuntimeStatus：状态、online、heartbeat_alive、last_error、last_seen_at。
        HornResponse：公开设备响应，只有 password_set，不提供真实 password。
        HornConnectionResult：测试是否成功及测试得到的运行状态。
        SecretStr 用于限制模型表示中的泄露；API 路由另行处理错误响应中的原始输入。

    service.py：HornService，数据库设备 CRUD 与提交后热同步。
        list_horns(enabled_only=False) / get_horn(id)：查询设备，返回安全的公开字典。
        _to_dict()：统一移除真实密码；历史 URL 中的认证信息、查询参数也不公开返回。
        create_horn()：校验请求，写入数据库，成功提交后通知运行管理器。
        update_horn()：锁定设备行，只修改明确传入的字段；password 为空或 None 时保留。
            URL、用户名或密码变化会在提交后重建运行实例；名称和备注变化可复用实例。
        delete_horn()：先检查所有已注册 Feature 的配置表及 LogisticsChannel.horn_id。
            即使引用方的 horn_enable=False，只要 horn_id 仍指向该设备，也禁止删除。
            HornInUseError 表示设备仍被引用，api/routes/horns.py 将其转换为 HTTP 409。
        runtime_configs()：仅供运行管理器和连接测试读取真实连接凭据，不能直接回给前端。
        _sync_after_commit()：事务成功退出后调用 runtime.sync(id)。flush 不等于 commit；
            提交失败时不能提前把新配置放进运行态。
        horn_service：模块级服务单例，创建对象本身不查询数据库、不连接设备。

    binding.py：普通 Feature 和物流通道共用的最终绑定校验。
        validate_horn_binding(session, enabled, horn_id, event_id)：使用调用方事务，
            只校验数据库与字段，不建立设备连接，不自行 commit。
        两个 ID 非空时必须是 1 到 MAX_HORN_ID 之间的整数；不接受布尔值、浮点或字符串。
            MAX_HORN_ID 与现有数据库有符号 Integer 的上限对应。
        启用喇叭告警时，设备 ID 和语音任务 ID 都必须提供，设备必须存在且已启用。
        关闭喇叭告警时，可以保留一个已停用但仍存在的设备；不存在的 ID 仍拒绝保存。
        校验查询锁定设备行，避免写入关系前设备被并发删除。
        普通 Feature 的 config_manager.py 和物流 service.py 都调用这里，
            前端组件的校验只是提前提示，不能代替后端最终校验。
        本函数不查询设备上的任务目录，任务是否已在设备中创建仍需现场核对。

    runtime_manager.py：HornRuntimeManager，进程内设备生命周期和异步播放。
        _entries：{设备 id: (数据库配置快照, Horn 实例)}，按设备而非 Feature 建实例。
        _retired：已关闭入口、等待在途操作结束的旧实例；_failures 记录同步失败的设备。
        start()：启动一个播放线程、一个配置对账线程，并立即读取数据库同步设备。
            每台启用设备还由 Horn.start_heartbeat() 建立自己的心跳线程。
        sync(id=None)：指定 id 时同步单台，不传时全量对账；同步操作串行化。
            新增/重新启用：创建 Horn(connect_on_init=False)，由后台心跳完成连接。
            地址/账号/密码变化：先关闭旧实例入口，再创建新实例。
            仅名称/备注变化：更新配置快照，继续使用现有连接。
            停用/删除：移出可用实例表，调用 request_stop()，旧实例不会再次复活。
            管理器尚未 start 时不创建运行实例，下次 start 会读取最新已提交配置。
        _reconcile_loop()：定期重新读取配置，补偿同步失败等情况；失败时先关闭旧实例，
            避免数据库已停用的设备仍按旧状态运行，再等待下一轮重试。
        enqueue_play(id, event_id)：只查当前实例并非阻塞入队，不执行设备 HTTP。
            管理器未运行、设备不可用或队列已满时返回 False，由 Dispatcher 明确记录。
        _play_loop()：播放前复查实例身份和任务有效期，再调用 Horn.play(event_id)。
            因修改配置、停用、删除而失效的旧实例任务，以及过期任务，不再执行。
        status(config)：合并管理器状态与 Horn.snapshot()，返回不含凭据的状态信息。
        test_connection(config)：凭据与现有实例相同时复用其会话，否则创建临时探测实例；
            只登录/检查在线，不保存配置、不播放、不额外启动心跳，结束后关闭临时实例。
        stop()：关闭入队和设备入口，清理待执行队列，限时等待后台线程退出。
            已发出的 HTTP 需要结束或超时才能彻底退出，因此可能短暂处于 stopping。
        horn_runtime_manager：模块级单例，由 Orchestrator 统一 start / stop。

三、和 API、前端、检测模块怎样连接

    管理设备：
        HornDeviceManager → unified_frontend/src/lib/horns.ts → api/routes/horns.py
            → HornService → 数据库 commit → HornRuntimeManager.sync()。
        当前 /api/horns 下的查询、写入、状态、测试连接接口都要求管理员权限。
        GET /api/horns、GET /api/horns/{id}：配置及运行状态。
        POST /api/horns、PATCH /api/horns/{id}、DELETE /api/horns/{id}：设备 CRUD。
        GET /api/horns/{id}/status：运行状态；POST /api/horns/test-connection：无声测试。

    保存检测绑定：
        HornAlarmBinding → AlarmPushConfig → 普通 Feature / 物流各自的保存接口。
        普通 Feature：alarm.horn = {enable, parm: {horn_id, horn_event_id}}。
        物流通道：alarm.horn = {enabled, horn_id, horn_event_id}。
        前端物流适配器负责界面格式转换，后端分别写入自己的配置表，不共用配置行。

    真正播放：
        普通 Consumer / LogisticsChannelRuntime → AlarmRequest
            → AlarmDispatcher 检查当前绑定开关和 ID
            → HornRuntimeManager.enqueue_play(horn_id, horn_event_id)
            → 后台 Horn.play(horn_event_id) → 设备 /run_task。
        一个设备故障不会把设备网络等待放回微信、SQL、证据处理的调用线程。
        Guard Behavior 与安检流程检测沿用同一设备绑定和播放链路。

四、设备状态与日常操作

    online：最近一次设备请求成功；offline：心跳或播放失败，等待后续连接恢复。
    connecting：正在登录；failed：登录失败或运行配置同步失败。
    disabled：设备配置停用；not_started：设备启用但运行管理器未启动。
    pending：等待运行同步；stopping：停止门控已关闭、旧操作尚在退出；stopped：已停止。
    保存成功只说明配置已提交；online 也不是“现场已经听到了声音”的回执。

    新增：在公共“喇叭配置”中填写设备资料和密码，启用后观察在线状态。
    绑定：在目标摄像头的报警推送或物流通道配置中，选择启用设备并填写已有任务 ID。
    临时关闭某项报警：关闭该配置的 horn_enable，设备和任务 ID 保留。
    全局停用：修改设备 enable=False，所有引用该设备的检测都会失去可用播放实例。
    删除：先解除所有配置的设备引用；只关闭 horn_enable 不算解除引用，仍会返回 409。
    测试连接：确认地址和认证可用，不能代替语音任务存在性和现场音量的检查。

五、后续维护和验证

    新增设备字段：同步检查 orm.py、schema.py、service.py、API 与公共设备管理组件。
    修改绑定规则：从 binding.py 入手，同时检查普通 Feature、物流原生格式及前端适配。
    修改设备协议：到 alarms/devices/horn.py；生命周期、热同步、队列策略在本包管理器中。
    不要在每个 Consumer 内各建 Horn，否则同一设备会出现重复登录、心跳和冷却状态。

    在部署环境确认设备连通性、认证、绑定、任务 ID 与发声效果。
六、horn.py：单个 IP 喇叭的登录、保活与播放

    Horn(config, connect_on_init=True)：保存 horn_url、username、password 等连接参数。
        直接构造默认立即尝试 connect()；运行管理器与连接测试使用 False 延迟联网。
        不负责查数据库，设备配置由 alarms/devices/ 转换后传入。

    connect()：POST 设备 /login，提交 user/password；成功响应需要包含
        access_key 和 access_id，之后保存认证会话并标记 online。
        登录失败标记 failed 并记录原因，不把设备请求异常抛回业务检测循环。
    start_heartbeat() / _heart_loop()：启动单台设备的心跳线程，周期调用 _send_heart()。
        周期间隔来自 settings.alarm，使用可被停止信号唤醒的 Event.wait()。
    _send_heart()：未登录时先 connect()，再 POST /online 维持会话。
        请求失败标记 offline；后续心跳或 play() 会重新尝试登录。
    play(event_id, expires_at=None)：检查停止信号、任务有效期、登录态和设备级冷却，
        再 POST /run_task，JSON 的 id 字段就是调用方传入的 horn_event_id。
        这里只调用设备中已有任务，不上传音频、不生成语音、不管理设备任务目录。
    _serialized：让同一 Horn 的登录、心跳、测试和播放串行访问设备，
        获取锁后再次检查停止门控，避免旧实例排队操作在停用后继续请求。
    request_stop()：立即关闭新操作入口、清除本地登录态，不等待在途 HTTP 结束。
    stop_heartbeat()：发停止信号并限时等待心跳线程退出；已停用实例不能重新启动。
    snapshot() / _set_state()：维护并返回在线标志、详细状态、最后错误、最近在线时间，
        区分正在退出的 stopping 和已无在途操作/心跳的 stopped，不公开登录凭据。
    check_connection()：仅登录和检查在线；不保存、不播放、不启动新的心跳线程。

    两层冷却含义不同：
        Dispatcher 冷却：同一摄像头/通道 × Feature 的业务重复告警控制。
        Horn 冷却：同一设备短时间内的播放保护，多个 Feature 共用设备时也共用它。
        所以多个告警可以引用同一台 Horn，但短时间内的每个告警不一定都实际发声。

"""
