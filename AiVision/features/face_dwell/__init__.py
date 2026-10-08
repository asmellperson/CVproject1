"""
features/face_dwell/：人脸逗留检测

这个功能用人脸检测框跟踪目标，判断同一轨迹是否停留超过配置时长。
这里只关注人脸位置和逗留，不提取身份特征，也不查询人员底库或授权名单。
本文件只作说明；SPEC 在 spec.py 中定义，由 features/registry.py 统一注册。

一、功能标识与模型依赖

    业务标识 detect_face，显示名称“人脸逗留检测”，报警类型为 4。
    使用 insightface_detection，返回 type 为 face 的检测框。
    它与 recognize_face 身份识别是独立功能，不能互相替代配置或结果。

二、每个文件负责什么

    spec.py：绑定 FaceConsumer、FaceConfigORM、FaceConfigSchema 和人脸检测模型。
    orm.py：保存逐摄像头人脸逗留配置。
    schema.py：校验 ROI、人脸分数阈值、跟踪、逗留和报警配置。
    consumer.py：FaceConsumer，继承 _shared/dwell_consumer.py 的公共逗留流程。
        REQUIRED_DETECTION_TYPE 限定 face；_detection_options() 提供 FACE_SCORE_THR
        等检测选项，其余目标关联、有效计时和告警交给父类。

三、一张人脸怎样形成逗留告警

    最新帧 → ROI → insightface_detection → 检测结果校验和过滤
        → IouTracker 匹配轨迹 → 累计有效观测时间 → 达到 MAX_TIME
        → 当前匹配轨迹参与告警 → 统一分发器控制重复通知。
    轨迹丢失次数和清理按公共跟踪规则处理，不能只按一帧没有人脸就判断离开。
    模型失败时暂停逗留计时并保留轨迹，恢复首帧不补计故障间隔。

四、和其他模块怎么联系

    face_detector.py 执行模型检测，_shared/dwell_consumer.py 解释时间与轨迹。
    api/routes/features.py 提供公共功能配置和监控，前端 FaceDetectionSection 展示。
    与 person_dwell 共用逗留层，因此修改公共计时规则会同时影响两种功能。

五、修改与验证

    只改人脸过滤时在本目录调整；修改共用关联或故障计时应在 _shared/ 中维护。
    验证低分框、多脸、短暂遮挡、模型超时、恢复首帧及 ROI 改变后的轨迹清理。
    检查监控计时与实际告警一致；仅改本说明时检查语法和差异。
"""
