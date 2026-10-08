"""
alarms/records/：告警记录、查询、处置和关联媒体

这个目录把已判定的告警写入数据库、保存截图，并为列表、统计和人工处置提供数据。
告警判定在 features/，通知调度在 alarms/dispatcher.py，视频录制在 evidence/。
本文件只作说明，不在这里创建写入线程、查询数据库或执行媒体清理。

一、每个文件负责什么

    orm.py：AiAlarmEvent 告警主记录和 AiAlarmDisposition 处置记录。
        告警保存发生时的主体、事业部、类型和证据引用，处置保存处理状态和历史。
    service.py：AsyncViolationWriter 与共享写入实例。
        enqueue() 将截图及记录工作交给后台队列，按批量或时间条件提交。
        save_now() 提供需要立即取得保存结果的入口。
        update_video_status() 接收视频录制回调，更新关联记录。
        start()/stop() 管理写入和媒体清理调度，写入失败按配置重试并保留失败信息。
    queries.py：告警查询、权限过滤、响应字段整理和统计。
        alarm_query()/require_alarm_access() 处理列表与单条访问的授权。
        event_dict()/alarm_items() 整理记录，alarm_statistics() 汇总统计。
    dispositions.py：处置列表、单条查询和事务保存。
        update_disposition() 先锁定报警，再更新处置状态、操作者和有界历史。
    schema.py：处置输入、输出及状态等数据约定。
    cleanup.py：ViolationMediaCleaner，为通用媒体清理器提供报警记录和文件引用。

二、一次报警从产生到查看

    Consumer / 业务 Runtime → AlarmRequest → AlarmDispatcher
        → 写入器保存截图、提交 AiAlarmEvent → API 查询列表及证据。
    视频可稍后完成：EvidenceRecorder → update_video_status() → 更新记录状态。
    人工处置：前端 → alarm_dispositions 路由 → 权限校验 → 锁定记录 → 事务保存。
    队列接收成功不等于数据库已经提交；视频路径存在也不等于文件可播放。

三、媒体清理为什么需要记录引用

    截图、视频和数据库记录需要一起维护，不能只按文件时间直接删除整个目录。
    ViolationMediaCleaner 复用 core/media_cleanup.py 的保留时间和容量策略，
        在删除记录时重新检查引用，并衔接其他业务媒体引用。
    人脸识别记录由自身模块维护，其媒体可纳入统一清理调度。
    处置记录有独立查询规则，管理员与普通用户对过期报警处置的可见范围不同。

四、如果我要扩展记录或处置字段

    同步 ORM、Schema、写入参数、查询序列化和前端类型，并准备数据库迁移。
    添加一种报警类型时还需检查 alarms/types.py、FeatureSpec 和权限映射。
    涉及新媒体目录时补齐引用与清理规则，避免误删仍被使用的文件。

五、修改后怎么验证

    覆盖异步提交、队列满、数据库失败、视频状态回调，以及列表和单条的权限一致性。
    处置验证并发保存和历史上限；清理使用临时数据验证引用保护与过期删除。
    仅改说明时检查语法和差异，不启动写入器或清理真实证据。
"""
