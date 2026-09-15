"""告警领域：分发协调、报警设备及通知发送。

本包仅作职责说明，不集中导入实现，不连接数据库、设备或启动后台任务。
检测触发条件由 features/ 与物流业务判断；SQL、截图和视频证据仍由
platform/violation/ 实现，经 Orchestrator 注入分发器。

一、入口与职责边界

    alarms/dispatcher.py：AlarmRequest、AlarmDispatcher 与 alarm_dispatcher 单例。
    alarms/devices/：设备配置、绑定校验、运行管理与 horn.py 的设备通信。
    alarms/notifications/：wechat.py 的发送协议与 notification_image.py 的缩略图签名。
    调用方从上述实现子模块显式导入；分发器单例仅在 dispatcher.py 中创建。
    导入实现可创建队列、锁等进程内对象，外部访问和线程启停由显式生命周期调用控制。

二、dispatcher.py：一次违规的统一分发入口

    AlarmRequest：一次业务告警的数据载体。
        feature_name、violation_type 表示检测功能与违规类型。
        camera_id、camera_name、camera_key 表示摄像头及共享内存标识。
        frame 是违规时的 BGR NumPy 图像，供截图保存或证据流程使用。
        alarm_config 携带 horn、wechat、sql 各自的 enable / parm。
        subject_type、subject_id、subject_name 支持摄像头或物流通道这样的不同主体；
            物流使用 subject_type="logistics_channel"，不能把通道 ID 当成摄像头主键。
        department、reason、metadata 携带归属、异常原因和通道成员等附加信息。

    AlarmDispatcher / alarm_dispatcher：分发器类与进程内全局单例。
        configure()：由 Orchestrator 注入 HornRuntimeManager、WeChatNotifier、
            violation_writer、evidence_recorder，并启动微信后台发送线程。
        maybe_dispatch(request, alarm_interval)：按主体和 Feature 检查业务冷却，
            冷却通过后调用 _execute()；返回 True 表示已进入分发，不保证每个通道成功。
        _cooldown_key()：使用 (subject_type, subject_id, feature_name)，
            普通摄像头未单独传 subject_id 时回退到 camera_id 的字符串。
        reset_cooldown() / reset_subject_cooldown()：配置变化等情况下清理对应冷却。
        stop()：通知微信发送线程退出并限时等待；设备运行管理器由 Orchestrator 另行停止。

    _execute() 的实际顺序与判断：
        1. 读取 SQL、微信配置，判断是否需要持久化告警；需要时请求创建视频证据任务。
        2. horn.enable=True 时，把 horn_id 和 horn_event_id 交给管理器非阻塞入队。
           未绑定完整、管理器未就绪、设备停用/不存在或无法入队时记录明确原因。
        3. 保存 SQL 告警：开启微信且 writer 支持 save_now() 时同步保存取得记录 ID；
           其余需要持久化的场景调用 writer.enqueue()，由写入器异步处理。
        4. 将 (AlarmRequest, 接收人, 告警记录) 放入微信队列，网络发送在后台执行。

        SQL 显式关闭且微信也不发送时，不执行这条持久化/证据创建流程。
        微信图文卡片需要数据库记录 ID，因此微信开启且接收人、客户端可用时，
        即使独立 sql.enable=False，也需要保存记录。
        旧请求没有提供有效 sql 配置或没有 enable 字段时，保留原有写入兼容行为。
        各通道异常分别处理；喇叭网络慢或失败不会阻塞微信队列和 SQL 通道。
        SQL 的 save_now() 仍是同步操作，不能把整条 _execute() 理解为完全异步。

    _write_violation()：组织截图、主体、部门、原因、metadata、视频路径等写入参数；
        根据 writer 方法签名过滤不支持的参数，兼容尚未接收全部新字段的写入适配器。
    _alarm_card_urls()：使用数据库告警 ID 和 WECHAT_CARD_BASE_URL 生成：
        缩略图 /api/public/alarms/{id}/image；人员报警附带仅授权该缩略图的短期签名。
        前端详情页的 alarmId 使用 aivision:{id}，详情和视频仍要求登录及事业部权限。
    _wechat_loop()：从队列取请求，生成卡片 URL，再调用 WeChatNotifier.send()。
        当前这一步不再将 frame 编码成 JPEG 上传企业微信；图片由平台 URL 提供。
        没有保存成功的记录 ID 或有效站点地址时，URL 不完整，发送器会明确跳过卡片。

三、普通检测与物流怎样进入同一条链

    普通检测：
        FeatureConfig 保存 horn_enable / horn_id / horn_event_id 等扁平字段
            → ConfigCache → BaseFunctionConsumer._handle_alarm()
            → 组装 alarm.horn = {enable, parm: {horn_id, horn_event_id}}
            → AlarmRequest → alarm_dispatcher.maybe_dispatch()。

    物流通道：
        LogisticsChannel 保存自己的通道告警配置
            → LogisticsChannelRuntime._build_alarm_request()
            → 将原生 {enabled, horn_id, horn_event_id} 转为分发器需要的嵌套格式
            → 使用物流主体、拼接画面、成员统计信息构造 AlarmRequest → 同一分发器。

    后续分支：
        喇叭：HornRuntimeManager 后台队列 → 对应 Horn.play(horn_event_id) → 现场设备。
        持久化：platform/violation/service.py → 告警记录、截图及相关元数据。
        证据：platform/violation/evidence_recorder.py → 告警前后录像任务。
        微信：_wechat_queue → _wechat_loop() → WeChatNotifier → 企业微信图文卡片。
        查询：api/alarms.py 与前端告警页使用已保存的记录和媒体，不依赖喇叭是否发声。

    Guard Behavior、Security VLM 使用各自的业务告警实现，目前没有进入本包这条
    AlarmDispatcher → HornRuntimeManager 播放链，不能只加界面绑定就宣称支持喇叭。

四、修改时从哪里入手、怎样验证

    改业务何时触发：修改具体 Consumer / 物流规则；改设备选择与绑定：修改配置服务。
    改通道分发、冷却、写入参数：检查 dispatcher.py 及 SQL/证据/微信回归测试。
    改设备协议：检查 devices/horn.py 的登录失败恢复、心跳、停止门控、无声测试和播放冷却。
    改消息内容或 token：检查 notifications/wechat.py、卡片 URL 与系统异常纯文本两种入口。
    不要把管理员设备 CRUD 或前端表单逻辑加入 Dispatcher，也不要在 Consumer 中直连设备。

    在项目根目录、已配置测试环境的 Python 中运行：
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_alarm_horn.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_horn_binding.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_wechat_news_card.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_alarm_config_hot_update.py
    涉及运行实例启停还要跑 test_horn_runtime_manager.py；涉及物流主体与拼接证据，
    还要跑 test_logistics_channel_runtime.py 和相应告警 API、证据测试。
"""
