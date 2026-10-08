"""
features/logistics_channel/：物流通道单人检测

这个目录把多台摄像头组织为一个物流通道，逐路检测人数后汇总通道状态。
Consumer 负责单路推理，LogisticsChannelRuntime 负责联合判定、持续计时和通道告警。
本文件只作说明，功能在 spec.py 声明，再由 features/registry.py 显式注册。

一、先分清功能、通道和成员

    功能标识 detect_logistics_single_person，使用 yolo_human，报警类型为 6。
    通道：拥有自己的运行时段、共享检测策略和报警配置。
    成员：关联摄像头、启用状态和顺序，单路仍保留自己的检测 ROI。
    CameraSnapshot：某台摄像头在某时刻的人数及在线状态，不是跨摄像头人员身份。
    各路人数不能直接相加作为通道人数，同一人员可能出现在多个镜头中。

二、每个文件负责什么

    spec.py：绑定 LogisticsSinglePersonConsumer、逐摄像头配置 ORM 和 Schema。
    orm.py/schema.py：通道、成员、配置与接口数据契约。
    constants.py：通道人数检测等公共常量。
    service.py：LogisticsChannelService，通道 CRUD、成员加入/移动/排序、启用及 ROI。
        完成业务约束和事务保存后，再发布对应运行通知。
    membership_transaction.py：成员写入的预查询、固定加锁顺序和完整事务重试，
        业务归属、容量等校验仍由 Service 执行。
    consumer.py：逐路取 ROI、人体推理、框过滤、坐标还原和去重，发布人数快照。
        通过注入的 Runtime 接口读取通道策略并请求汇总，不独立重复发人数告警。
    state.py：不可变快照、纯联合判定、异常持续状态机及线程安全快照存储。
    runtime.py：LogisticsChannelRuntime，组合配置、时段、在线状态与快照，
        维护通道事件、证据来源、监控状态和统一告警。
    compositor.py：将成员画面按通道展示需要合成监控与证据图片。

三、多摄像头如何得到一个通道结论

    启用成员逐路检测 → 过滤并去重后的本路人数 → 带时间戳的快照
        → Runtime 检查运行时段及新鲜度 → classify_channel() → ChannelPresenceState。
    任一有效摄像头检测到至少两人，判为 multiple；否则有一路一人，判为 normal。
    没有上述证据但存在离线、过期或无效快照时，判为 unknown；全部有效且无人为 empty。
    无成员为 unconfigured，非活动状态为 inactive。
    empty/multiple 分别累计持续时间；正常、未知或停用等状态会重置异常计时。

四、和 API、前端及告警怎么联系

    api/routes/logistics_channels.py 提供通道和成员的专属配置与监控接口。
    前端 logistics_single_person/ 组件维护通道选择、成员和配置草稿。
    Orchestrator 注入帧来源、在线判断和告警依赖，Runtime 组织组合证据与 AlarmRequest。
    摄像头、通道与功能开关作用不同，修改成员后需要同步更新运行配置。

五、修改与验证

    新增共享策略字段时同步 Schema、Service、Runtime 和 Consumer 读取，避免每路各用一份值。
    成员操作验证跨通道移动、并发写入、容量、事业部归属及提交后的通知。
    判定验证多人优先、单人加离线、全部无人、过期快照、时段切换和计时重置。
    组合画面验证顺序及缺失画面；仅修改本说明检查语法和差异即可。
"""
