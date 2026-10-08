"""
features/phone_detection/：手机使用检测

这个功能在手机候选框基础上进行人体关联、连续命中和持续时间确认，降低孤立物体误报。
检测到手机框不等于业务告警成立，最终结论由 PhoneConsumer 的过滤和轨迹状态决定。
本文件只作说明，SPEC 在 spec.py 中定义，统一注册入口为 features/registry.py。

一、功能标识与实际模型调用

    业务标识 detect_phone，显示名称“手机使用检测”，报警类型为 3。
    spec.py 的 required_models 声明 yolo_phone。
    Consumer 另有 PERSON_MODEL_NAME="yolo_human"；开启人体关联且该模型队列可用时，
        还会发起人体推理。检查依赖时必须同时看声明和 Consumer 的实际投递。
    当前人体模型不可用时，enforce_person 不启用，不能据此假设每次都已完成人体关联。

二、每个文件负责什么

    spec.py：绑定 PhoneConsumer、PhoneConfigORM、PhoneConfigSchema 和手机模型。
    orm.py：保存逐摄像头手机检测配置。
    schema.py：手机/人体推理阈值、关联过滤、跟踪确认、ROI 和告警参数。
    consumer.py：PhoneConsumer，维护每台摄像头自己的手机轨迹和 ID。
        _process() 执行模型请求，筛选候选并更新轨迹。
        _qualified_phone_detections() 组合框过滤、人体关联和时序确认。
        _is_near_person_hand_region() 按人体框的相对区域过滤手机候选。
        _update_track()/_prune_tracks() 处理连续观测和过期轨迹。
        post_process() 绘制检测结果，ROI 变化时清理旧轨迹。

三、一帧结果怎样变成告警

    ROI → yolo_phone → 可选 yolo_human → 框坐标还原与候选过滤
        → 手机与人体区域关系 → 轨迹关联 → 连续命中和时长确认
        → 业务告警 → 公共分发器的记录、证据与通知。
    手机置信度、人体关联、轨迹确认和报警冷却分别作用于不同阶段。
    同一物理权重可以支持不同逻辑模型，但 Consumer 仍发起各自的推理任务。

四、和其他模块怎么联系

    _shared/consumer.py 负责取帧、任务匹配和告警衔接，inference/ 负责模型加载。
    公共功能配置 API 供前端 PhoneDetectionSection 使用。
    删除或改名 yolo_human 时也要检查本功能，不能只搜索 required_models。

五、修改与验证

    覆盖孤立手机、人体附近手机、手机短暂出现、多目标、轨迹过期和 ROI 修改。
    调整人体关联时核对开关、队列不可用和推理失败的实际行为，避免注释强于实现。
    仅改本说明时检查语法和差异，不需要运行真实模型。
"""
