"""
features/_shared/：检测功能的公共基础设施

这个目录复用配置、取帧、ROI、推理通信和告警衔接，减少各功能重复维护相同流程。
具体功能仍负责业务判定，模型加载由 inference/ 管理，视频采集由 cameras/ 管理。
本文件只作讲解，不集中导入功能，也不启动 Consumer。

一、每个文件负责什么

    spec.py：FeatureSpec，冻结的功能声明，连接 Consumer、ORM、Schema 和模型依赖。
        model_names 合并必需与可选模型并去重；功能注册由 ../registry.py 完成。
    orm.py：功能配置的公共数据库结构，具体功能在自己的 orm.py 中定义配置表。
    config_manager.py：FeatureConfigManager，按功能声明管理逐摄像头配置，
        衔接结构校验、数据库保存、缓存和配置变更通知。
    alarm_schema.py：公共报警配置契约，供需要普通告警配置的功能复用。
    defaults.py：公共配置默认值，避免同一参数在多个功能中各自硬编码。
    roi.py：归一化 ROI、警戒线及像素坐标转换的公共契约。
    consumer.py：BaseFunctionConsumer，功能级线程及其管理的多台摄像头状态。
    tracking.py：IouTracker 等目标关联能力，综合框重叠、中心距离和面积关系。
    dwell_consumer.py：DwellDetectionConsumer，人脸和人员共用的逗留跟踪与计时。

二、BaseFunctionConsumer 负责哪些步骤

    start()/stop()：控制功能线程和推理结果接收等运行资源。
    update_config()/update_status()/remove_camera()：更新或移除摄像头的功能状态。
    _run()：按配置和采样条件处理画面，衔接子类检测、标注及告警。
    _get_roi()：从画面还原归一化 ROI、裁剪并处理区域掩码。
    dispatch_inference_sync()：构造请求、投递模型队列、按 request_id 等待对应结果，
        结果接收复用 inference/result_router.py，处理队列满、超时和模型不可用。
    _handle_alarm()：将子类结果与配置组合成 AlarmRequest，交给统一分发器。
    inference_status()：暴露推理健康状态，业务异常和模型故障有不同含义。

三、子类应该在哪些地方扩展

    _process(roi, camera_id)：解释图片或模型结果，返回业务结果。
    post_process(camera_id, result)：生成标注帧和所需监控数据。
    _should_alarm()：需要额外告警时序时扩展，例如门检测的首次持续等待。
    _alarm_context()：补充告警主体、原因和业务元数据。
    _process_static_frames()：需要持续计时的功能决定静态画面是否仍要处理。
    _on_roi_changed()/_clear_camera_state()：清除受配置变化影响的轨迹和历史状态。
    单路 Consumer 只发布快照的功能，可由其业务 Runtime 统一决定报警。

四、逗留公共层为什么单独存在

    FaceConsumer 和 HumanConsumer 的模型、过滤参数不同，但目标关联和逗留规则相同。
    DwellDetectionConsumer 先校验结果，再跟踪目标并累计有效观测时间。
    推理失败暂停计时并保留轨迹，恢复后的首个观测不补计故障期间时间。
    当前只有成功匹配到的轨迹参与告警；重复通知再由 alarm_interval 控制。
    把失败当作零目标会错误改变轨迹，把故障时间计入逗留会导致误报。

五、一次普通检测的完整链路

    配置缓存＋最新帧 → 采样条件 → ROI → 子类 _process()
        → 模型任务与匹配结果 → 子类判定/标注 → 监控帧与 AlarmRequest。
    配置修改 → 服务提交 → 缓存刷新和运行通知 → Consumer 更新本地状态。
    ROI 内坐标与原帧坐标要明确，标注和业务几何计算不能混用。

六、修改后怎么验证

    公共流程修改应检查实际受影响的功能，覆盖取帧、配置更新、停止、超时和结果匹配。
    ROI 验证坐标还原，跟踪验证丢失恢复，逗留验证故障期间计时暂停。
    仅改包说明时比较文档字符串之外的 AST 即可，不需要启动 Consumer 线程。
"""
