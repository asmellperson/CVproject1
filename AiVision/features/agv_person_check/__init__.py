"""
features/agv_person_check/：AGV 无人运货检测

这个功能由 HTTP 请求触发，在指定摄像头 ROI 内完成短时多帧人体检测。
任一有效帧有人即可确认有人；只有完成配置的有效采样次数仍无人，才返回无人。
无画面、推理失败和超时属于请求失败，不能作为“无人”的证明。
本文件只作说明，功能声明在 spec.py，包导入不会发起检测或 HTTP 回调。

一、功能标识与模型依赖

    业务标识 agv_person_check，报警类型为 13，依赖 yolo_human。
    摄像头采集与请求检测分别管理：摄像头可以在线待机，没有请求时不持续执行人体判定。
    同一摄像头同时只接受一个尚未释放的请求，全局待处理数量也有上限。

二、每个文件负责什么

    spec.py：绑定 AgvPersonCheckConsumer、配置 ORM、Schema 与人体模型。
    orm.py/schema.py：保存并校验 ROI、采样间隔、次数、超时、人体阈值及 HTTP 协议。
        PersonCheckResult 表达内部布尔判定，对外结果值由协议配置映射。
    consumer.py：从共享缓存读取新鲜画面，复用公共 ROI 和推理队列。
        submit() 校验功能与摄像头运行状态；_sample() 采样并检查请求配置有效性。
        _on_result() 在有人时提交告警，通知失败不会改写已完成的检测结论。
        配置变更、状态切换和停止会衔接请求取消与资源清理。
    service.py：AgvPersonCheckService、CheckRequest 和 PersonCheckError。
        维护每请求的配置快照、截止时间、采样计数和 Future，在 Consumer 线程内调度。
        detecting_camera_ids() 只统计尚未完成判定的请求，供总览使用。
    http_adapter.py：render_body() 映射结果、camera_key 和 request_id 模板变量；
        send_callback() 执行一次配置的 HTTP 回调，不自动重试，不跟随重定向。

三、一次请求的完整流程

    POST /api/public/agv/person-check/{camera_key} → Consumer.submit()
        → Service 保存请求快照 → 按间隔获取不同的新鲜帧 → ROI 人体推理
        → 有人提前结束 / 采样完成确认无人 / 失败结束 → Future 完成。
    同步模式等待结果并返回配置模板；回调模式先返回 202 和 request_id，
        后台等待有效结果后发送回调，最后释放请求。
    判定已完成但还在等待回调时，总览不再把摄像头计为“正在检测”。

四、和其他模块怎么联系

    api/routes/agv_person_check.py 负责公开触发、HTTP 错误映射和回调调度。
    参数维护沿用公共 Feature 配置 API，前端 AgvPersonCheckSection 提供配置与监控。
    FrameReader 提供帧与采集时间，InferenceRuntimeManager 管理 yolo_human，
        AlarmDispatcher 处理有人告警；本功能不另建摄像头连接或模型进程。

五、修改与验证

    检测规则放 Consumer/Service，对外协议放 http_adapter，避免在路由里复制采样循环。
    验证单帧有人、足量无人、重复旧帧、超时、推理失败、同摄像头并发和配置取消。
    回调验证成功与失败、请求释放以及结果模板类型；仅改说明无需触发真实 AGV 请求。
"""
