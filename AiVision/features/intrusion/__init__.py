"""
features/intrusion/：区域入侵检测

这个功能检测 ROI 内的人体，以人体框靠近脚底的位置判断人员是否位于警戒线的入侵侧。
当前判断的是“指定一侧存在人员”，不要求先跟踪到一次跨线动作。
本文件只作讲解，功能声明在 spec.py，统一注册在 features/registry.py。

一、功能标识与模型依赖

    业务标识 blocks，显示名称“区域入侵检测”，正式报警类型为 1。
    使用 yolo_human 检测人体，权重和模型运行状态由 inference/ 管理。
    intrusion 是源码包名，配置和 API 查询使用 blocks。

二、每个文件负责什么

    spec.py：SPEC 绑定 BlocksConsumer、BlocksConfigORM、BlocksConfigSchema 和模型。
    orm.py：逐摄像头的功能配置表。
    schema.py：检测阈值、ROI、警戒线、入侵方向和 foot_ratio 等配置校验。
    consumer.py：BlocksConsumer，继承公共 BaseFunctionConsumer。
        _process() 执行人体推理，将 ROI 检测框平移回原帧，计算脚底代表点，
            再用有向直线与点的关系判断是否落在 alarm_side。
        post_process() 在监控画面上绘制警戒线、方向、检测框和代表点。

三、一帧图片的业务流程

    最新帧 → 公共层裁剪 ROI → yolo_human → 原帧检测框
        → 按 foot_ratio 计算脚底点 → 判断警戒线一侧 → 入侵结果与标注
        → 公共告警入口 → AlarmDispatcher 冷却、证据和通知。
    ROI 决定参与检测的区域，警戒线和方向决定区域内哪些人体属于入侵。
    线段端点顺序、alarm_side 与前端展示必须保持一致，否则会判到相反一侧。

四、和其他模块怎么联系

    _shared/roi.py 提供警戒线契约，_shared/consumer.py 提供取帧、推理和告警骨架。
    api/routes/features.py 管理公共配置和监控，前端 IntrusionDetectionSection 展示。
    修改业务标识或报警类型时还要检查权限、数据库记录和前端映射。

五、修改与验证

    调整判定优先修改几何函数与 Schema，不在模型 Worker 中写入侵规则。
    验证线两侧、在线上、ROI 偏移、不同画面尺寸和多个目标，核对画面箭头与告警一致。
    仅修改本说明时检查语法和差异，实际算法验证再使用受控图片或视频。
"""
