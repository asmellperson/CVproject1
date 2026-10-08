"""
features/security_inspection/：安检流程规范检测

这个功能先用人体检测发现工位内的人员交互，再将会话关键帧交给内部千问服务判定。
本地感知、会话采样和外部模型任务分别管理，HTTP 推理不占用逐帧检测线程。
本文件只作说明，spec.py 定义功能，features/registry.py 显式注册。

一、功能标识与两类模型依赖

    业务标识 security_inspection，正式报警类型为 12。
    FeatureSpec.required_models 声明 yolo_human，用于本地人体感知和跟踪。
    千问通过 vlm.py 的 HTTP 客户端调用，不由本地 BaseModelWorker 加载。
    本地人体模型正常不代表千问服务可用，运行状态需要分别查看。

二、每个文件负责什么

    spec.py：绑定 InspectionConsumer、InspectionCameraConfig 和 InspectionConfig。
    orm.py/schema.py：摄像头、工位 ROI、服务参数、判定结果与会话历史契约。
    geometry.py：安检工位所需的区域几何处理。
    sessions.py：PairSessionManager，人员交互配对、外观指纹跟随及关键帧采样。
        TrackHist、PairSession、RoiState 保存本地会话状态，不管理网络或文件。
    consumer.py：本地人体推理、跟踪和会话推进，生成 InspectionTask 并处理完成结果。
        配置变更、画面尺寸变化或感知失效时更新代次、清理会话并取消旧任务。
        完成回调核对任务是否仍对应当前配置，避免旧结果写回新状态。
    runtime.py：InspectionRuntime，用有界队列按部门/摄像头调度外部请求，
        提供任务取消、服务健康、失败状态和停止流程。
    vlm.py：VlmClient，编码图像、检查服务并调用千问；parse_completion() 校验
        Chat Completions 响应及业务结果，失败不能当成一次合规判定。
    prompts.py：模型提示词，与业务结果 Schema 配合定义判定输出。
    service.py：InspectionService，保存设置、检查模型、记录并查询会话历史。
        逐摄像头功能配置仍由公共 FeatureConfigManager 管理。

三、一段安检过程的完整链路

    共享帧 → yolo_human → 单摄人体跟踪 → 工位 ROI 内交互配对
        → 会话持续与关键帧采样 → InspectionTask → 后台千问请求
        → 严格解析判定 → 核对任务代次 → 保存历史及需要的证据/告警。
    Consumer 使用全帧感知，再按配置的工位 ROI 组织会话，不等同于普通单 ROI 裁图检测。
    会话编号、摄像头和配置代次共同限定结果用途，停用后的迟到响应不能继续报警。

四、和平台其他模块怎么联系

    api/routes/security_inspection.py 提供设置、状态、模型检查和历史查询。
    前端 SecurityVlmSection 与 security-inspection/ 组件使用这些接口。
    摄像头、推理队列和正式告警仍复用平台设施，千问网络调用由专属 Runtime 管理。
    修改提示词或判定字段时，同时检查 Schema、历史记录、报警与前端显示。

五、修改与验证

    会话规则验证配对、离开、重新匹配、采样和多个工位；调度验证队列满、超时与公平轮询。
    配置修改或停止时检查旧任务取消及迟到结果隔离，服务失败不能写成正常安检结果。
    真实判定质量需要有代表性的视频和可用千问服务；仅改说明检查语法和差异即可。
"""
