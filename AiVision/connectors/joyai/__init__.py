"""
connectors/joyai/：JoyAI Adapter HTTP 接入

这个目录向 Adapter 提交带时间范围的单张 JPEG 和提示词，取得视觉语言响应。
连续采样、视频提问排队和事件保存由 visual_language_detection 业务模块负责。
本文件只作讲解；客户端实现位于 client.py，导入本包不发起 HTTP 请求。

一、client.py 中的主要对象

    JoyAIClient：读取 settings.joyai，管理模型名称缓存和 Adapter 请求。
        _model_name()：读取 /v1/models，要求服务公布一个有效主模型，并加锁缓存名称。
        observe()：调用 /v1/chat/completions，每次包含一个 JPEG、提示词和时间范围，
            通过 x-streaming-session 标识会话，使用非流式响应。
        reset()：调用 /v1/streaming/reset，并检查会话清理是否成功。
    JoyAIResult：包含清洗后的 text 和模型推理耗时 latency_seconds。
    JoyAIError：可向业务层展示的脱敏通信或响应校验错误。
    visible_text()：处理 </silence> 与 </response> 标记，静默响应返回 None。

二、一次观察的流程

    业务层提供 JPEG、prompt、session_id、时间范围和采样参数
        → 获取或复用模型名称 → POST 观察请求 → 校验 Chat Completions 响应
        → 清理协议标记 → 返回可见文本及 streamingharness 中的模型耗时。
    text=None 表示协议约定的静默结果，不应自动生成一条空事件。
    session_id 的创建、复用和失效由调用方安排，客户端不会管理摄像头生命周期。

三、连接配置与边界

    Adapter 地址和超时来自 core/settings.py 的 joyai 分组。
    请求直连配置的服务，不读取系统 HTTP 代理，也不自动跟随重定向。
    HTTP 非 200、超时、无效 JSON 或响应字段不符合契约均转换为 JoyAIError。
    这个客户端不启动 Adapter 或模型服务，也不把完整视频作为单次请求上传。

四、修改与验证

    变更协议时同步业务调用参数、返回类型和可见文本处理，不把协议标记交给前端。
    验证模型发现缓存、单帧请求结构、会话重置、静默结果、超时和损坏响应。
    真实推理效果需在 Adapter 可用时联调；仅改说明无需启动模型或联网。
"""
