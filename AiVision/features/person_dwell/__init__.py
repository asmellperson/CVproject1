"""
features/person_dwell/：人员违规逗留检测

这个功能用人体检测结果关联人员轨迹，累计有效观测时间，达到阈值后产生逗留告警。
HumanConsumer 只提供人体检测和关联参数，公共逗留流程与人脸逗留共用。
本文件只作讲解，功能声明位于 spec.py，注册入口为 features/registry.py。

一、功能标识与模型依赖

    业务标识 detect_human，显示名称“人员违规逗留检测”，报警类型为 5。
    使用 yolo_human；实际权重路径和检测类别由 inference/ 的模型配置决定。
    person_dwell 是源码目录，数据库、队列和前端请求使用 detect_human。

二、每个文件负责什么

    spec.py：绑定 HumanConsumer、HumanConfigORM、HumanConfigSchema 和模型依赖。
    orm.py：保存每台摄像头的人员逗留配置。
    schema.py：校验检测、ROI、轨迹匹配、逗留及告警字段。
    consumer.py：HumanConsumer，继承 DwellDetectionConsumer。
        _detection_options() 提供 CONF_THRESHOLD、MIN_BOX_AREA、ASPECT_RATIO_RANGE，
        以及中心距离、面积比例、匹配分数和平滑等参数。
        检测过滤与目标关联是两个步骤，模型置信度不能替代跟踪匹配阈值。

三、检测与计时的流程

    Camera 最新帧 → ROI → yolo_human → 过滤人体框 → 匹配或创建轨迹
        → 有效观测计时 → 达到 MAX_TIME → 监控快照、标注及告警。
    达到阈值的轨迹保持告警状态直到轨迹删除，当前帧仅已匹配轨迹参与报警。
    推理故障暂停计时，不把模型停顿算作人员逗留，也不立即删除已有轨迹。
    重复通知由报警冷却控制，轨迹计时与通知间隔不是同一个参数。

四、和其他模块怎么联系

    _shared/dwell_consumer.py 维护公共检测和计时，_shared/tracking.py 执行目标关联。
    公共功能 API 读写配置，前端 HumanDetectionSection 与 human_dwell/ 组件显示监控。
    AlarmDispatcher 负责记录和通知；人员离开或摄像头配置变更时由运行逻辑清理状态。

五、修改与验证

    参数增删同步 Schema、默认值、Consumer 读取和前端配置，不在 Worker 内判断逗留。
    验证人体大小过滤、多人交错、短暂丢失、静止人员、故障恢复及 ROI 热更新。
    公共逗留规则变化还需检查 face_dwell；仅改包说明检查语法和差异即可。
"""
