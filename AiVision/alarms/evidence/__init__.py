"""
alarms/evidence/：告警视频证据

这个目录从已有画面中缓存报警前的帧，收集报警后的帧，异步编码成视频。
它负责“视频怎么留下来”，告警是否成立、何时触发由 Consumer 或业务 Runtime 决定。
本文件只作讲解；录制器在 evidence_recorder.py 中定义，由运行编排层衔接。

一、先分清视频来源和录像任务

    source_key：画面来源标识，可以对应摄像头，也可对应业务生成的组合画面。
    帧缓存：按来源保存近期 JPEG 数据，为触发告警时提供前录画面。
    录像任务：保存视频目标、结束时刻和需要编码的帧；创建任务不代表视频已完成。
    参数来自 core/settings.py 的 storage 配置，也可由构造参数显式传入。

二、evidence_recorder.py 负责什么

    AlarmEvidenceRecorder：帧采样、来源缓存、任务生命周期和后台写入的管理器。
        start(frame_provider)：连接最新帧提供函数，开启采样和写入流程。
        should_sample()/record_frame()：供业务按来源控制采样、补充业务画面。
        start_alarm()：创建包含前录缓存和后续录制时段的告警片段。
        begin_episode()/finish_episode()/cancel_episode()：显式管理业务事件片段，
            用于结束时间由业务过程决定的证据；长事件帧可借助临时 spool 保存。
        clear_source()：清理指定来源的关联状态。
        set_status_callback()：把视频完成或失败状态通知记录层。
        stop()：停止采样并处理录制与写入资源的退出。
    _ClipTask：一个录制任务的内部状态，不是数据库中的报警记录。

三、一次告警录像的流程

    FrameReader 最新帧 / 业务组合画面 → 缩放、JPEG 编码 → 来源滚动缓存
        → 告警触发 → 取前录帧并继续收集 → 后台写视频
        → core/video_encoding.py 检查浏览器兼容格式 → 回调更新视频状态。
    前录和后录时长、采样帧率、最大宽度及启用开关按实际配置读取。
    视频路径已分配、记录已存在、文件已可播放是三个不同阶段。

四、和其他模块怎么联系

    runtime/orchestrator.py 提供帧来源，并把状态回调连接到违规记录写入器。
    alarms/dispatcher.py 和通道、保安室等业务运行时决定何时创建或结束证据。
    alarms/records/ 保存视频引用及状态，API 根据记录提供证据访问。
    历史媒体保留和删除由记录层配合 core/media_cleanup.py 管理。

五、修改与验证

    扩展新来源时确保 source_key 稳定且不会与其他业务混用，并配套退出清理。
    调整录像时验证前后时段、重复触发、事件取消、停止时收尾和编码失败回调。
    实际播放验证需要可用的 OpenCV、ffmpeg/ffprobe 和可写媒体目录；
    仅修改包说明时检查语法和差异，不需要创建视频或启动后台线程。
"""
