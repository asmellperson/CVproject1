"""
features/guard_behavior/：保安行为规范检测

这个功能按保安室 Site 管理多台摄像头，检测离岗、玩手机、趴睡和车辆漏检等行为。
单摄 Consumer 产生感知事实与局部状态，Site Runtime 汇总证据后决定正式业务告警。
功能已在 features/registry.py 注册，本文件只作讲解，不启动模型或保安室运行线程。

一、功能、模型和报警类型

    业务标识 guard_behavior，SPEC 位于 spec.py。
    必需模型：yolo_guard_person_phone 检测人体/手机，guard_uniform 判断制服概率。
    可选模型：yolo_guard_pose 提供姿态，yolo_vehicle 提供车辆检测。
        对应模型缺失影响相关子规则，应在业务状态中表达，不能直接等同于正常。
    constants.py 的 GUARD_ALARM_TYPES 对应离岗 8、手机 9、趴睡 10、车辆漏检 11。
    摄像头配置、保安室规则和各报警类型的通知策略分别保存。

二、每个文件负责什么

    spec.py：声明 Consumer、配置 ORM/Schema、必需和可选模型及报警类型。
    constants.py：保安室、规则、成员上限和各类告警的默认参数。
    orm.py/schema.py：Site、成员、规则、报警策略和摄像头配置的数据契约。
    service.py：保安室与配置持久化、成员关系和业务校验。
    consumer.py：GuardBehaviorConsumer，执行逐路感知、制服分类、手机/姿态/车辆推理，
        将局部结果变成快照，标注帧另行提供给运行层。
    tracking.py：CameraByteTracker 等单摄目标跟踪。
    state.py：纯数据快照及 GuardTrackMemory，缓存制服概率和确认时间。
    pose_features.py：从姿态关键点提取行为判断需要的特征。
    behavior.py：LocalBehaviorState，处理本路手机与趴睡的时序确认。
    site_rules.py：多摄像头证据汇总、可用性与离岗规则。
    vehicle_episode.py：VehicleEpisodeTracker，按框和时间维护车辆事件及检查情况。
    runtime.py：GuardBehaviorSiteRuntime，调度 Site 汇总、告警、证据和监控状态。

三、单摄感知怎样变成保安室告警

    最新帧 → 人体检测与跟踪 → 制服概率及身份保持 → 手机/姿态/车辆局部分析
        → GuardCameraSnapshot → Site 成员可用性与快照新鲜度检查
        → 离岗/行为/车辆规则 → 对应报警策略 → AlarmDispatcher 与证据录制。
    负面存在判断需要完整证据，例如不能因为摄像头失联就断言整个保安室无人。
    明确的正面异常证据可按汇总规则生效，其他摄像头降级不一定抹掉该证据。
    车辆事件在单摄像头内关联，不凭不同摄像头的框推断同一辆车或同一个人。

四、配置和前端怎么联系

    api/routes/guard_behavior.py 管理保安室、成员、策略和状态。
    前端 GuardBehaviorSection 及 guard_behavior/ 组件呈现 Site 配置和监控。
    Orchestrator 持有 Service/Runtime 并衔接配置刷新；Consumer 由正式注册表创建。
    通知开关与检测规则分别作用于结果分发和判定，不应相互代替。

五、修改与验证

    感知处理放 Consumer，纯时序放 behavior/vehicle_episode，多摄汇总放 site_rules/runtime。
    增加子规则时同步模型依赖、报警类型、Schema、策略默认值和前端状态表达。
    验证制服短暂丢失、手机/趴睡持续条件、全成员离岗证据、断流和过期快照。
    车辆规则覆盖进入、遮挡、关联、离开与证据取消；仅改包说明不运行真实模型。
"""
