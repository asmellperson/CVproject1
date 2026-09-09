"""
core/alarm/ — 告警通道模块
包含喇叭（音频告警）、微信通知、SQL 记录等多种告警通道，以及统一分发器。

这个包回答“业务已经确认违规之后，如何限制重复告警、调用通知和记录通道”。
识别人、手机、区域入侵以及判断违规持续时间，仍由 features/ 或物流通道业务处理。
SQL 写入和证据录像由 platform/violation/ 实现，本包通过注入的对象调用它们。

一、包入口与职责边界

    本文件末尾保留包级导出：AlarmDispatcher、alarm_dispatcher、Horn、WeChatNotifier。
    AlarmRequest 定义在 dispatcher.py 中，调用方可从该子模块显式导入。
    导入本包会加载这些子模块，创建分发器单例、队列和锁，并加载其 settings/logger
    依赖；不会在此时启动微信发送线程、创建现场 Horn 连接或发送告警。
    线程启停与依赖注入由 platform/orchestrator.py 的运行生命周期负责。

    core/alarm/horn.py：单台设备的 HTTP 协议与连接状态。
    platform/alarm_device/：设备数据库 CRUD、绑定有效性校验和多个设备的运行管理。
    core/alarm/dispatcher.py：某次告警使用什么通道、向哪台设备发送什么任务。
    platform/violation/：保存告警记录、截图和视频证据，并向查询 API 提供数据。

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
        缩略图 /api/public/alarms/{id}/image；前端详情页的 alarmId 使用 aivision:{id}。
    _wechat_loop()：从队列取请求，生成卡片 URL，再调用 WeChatNotifier.send()。
        当前这一步不再将 frame 编码成 JPEG 上传企业微信；图片由平台 URL 提供。
        没有保存成功的记录 ID 或有效站点地址时，URL 不完整，发送器会明确跳过卡片。

三、horn.py：单个 IP 喇叭的登录、保活与播放

    Horn(config, connect_on_init=True)：保存 horn_url、username、password 等连接参数。
        直接构造默认立即尝试 connect()；运行管理器与连接测试使用 False 延迟联网。
        不负责查数据库，设备配置由 platform/alarm_device/ 转换后传入。

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

四、wechat.py：企业微信消息协议

    WeChatNotifier：保存企业 ID、应用密钥、应用 ID；构造本身不发送网络请求。
        凭据按构造参数、settings.alarm、环境变量等既有回退规则取值。
    _get_token()：校验凭据，请求 access_token，检查 HTTP 状态、业务错误码和响应。
        当前已经缓存 token 和过期时间，使用 monotonic 时钟及锁避免并发重复刷新，
        并按接口响应的 expires_in 提前刷新；不是每次发送都重新获取 token。
    _EVENT_DISPLAY：把内部 Feature 名称转换为通知展示名称，未收录名称保持原值。
    send()：用于检测业务告警，需要接收人、缩略图 URL 和详情 URL。
        当前只走单条 news 图文卡片；缺少 URL 时记录原因并返回 False，
        不再执行旧说明中提到的“上传图片 / 文本加图片降级”流程。
    _send_news_card()：组织标题、说明、图片 URL、跳转 URL，调用企业微信 message/send。
        检查 HTTP 和企业微信业务错误码，返回本次发送是否成功。
    send_text()：发送 Markdown 文本，用于摄像头、模型、Consumer 或 API 的系统异常通知。
        与业务告警图文卡片是不同入口，系统异常不必构造 AlarmRequest。

五、普通检测与物流怎样进入同一条链

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

六、修改时从哪里入手、怎样验证

    改业务何时触发：修改具体 Consumer / 物流规则；改设备选择与绑定：修改配置服务。
    改通道分发、冷却、写入参数：检查 dispatcher.py 及 SQL/证据/微信回归测试。
    改设备协议：检查 horn.py 的登录失败恢复、心跳、停止门控、无声测试和播放冷却。
    改消息内容或 token：检查 wechat.py、卡片 URL 与系统异常纯文本两种入口。
    不要把管理员设备 CRUD 或前端表单逻辑加入 Dispatcher，也不要在 Consumer 中直连设备。

    在项目根目录、已配置测试环境的 Python 中运行：
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_alarm_horn.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_horn_binding.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_wechat_news_card.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_alarm_config_hot_update.py
    涉及运行实例启停还要跑 test_horn_runtime_manager.py；涉及物流主体与拼接证据，
    还要跑 test_logistics_channel_runtime.py 和相应告警 API、证据测试。
"""

# 从子模块中导入核心类与单例对象，统一暴露为包级接口
from .dispatcher import AlarmDispatcher, alarm_dispatcher  # 告警分发器类 & 全局单例
from .horn import Horn                                      # 喇叭（音频/蜂鸣）告警通道
from .wechat import WeChatNotifier                          # 微信消息推送通道

__all__ = ["AlarmDispatcher", "alarm_dispatcher", "Horn", "WeChatNotifier"]
