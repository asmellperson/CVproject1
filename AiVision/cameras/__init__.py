"""
cameras/：摄像头配置、视频采集和最新帧读取

这个目录把摄像头视频源变成其他模块可以使用的 NumPy 图像。
Camera 负责“摄像头怎么配置、怎么拉流、画面怎么交给别人”；模型推理由 inference/
负责，检测规则由 features/ 或物流通道模块负责，告警记录与证据由 alarms/records/ 和 alarms/evidence/ 处理。
本文件只作讲解，导入本包不会在这里连接摄像头或启动采集进程。

一、先分清配置、运行和业务功能

    CameraConfigManager：数据库里这台摄像头应该是什么配置。
    CameraRuntimeManager：哪些摄像头应该采集，当前管理哪些采集进程。
    CameraRuntime：一台摄像头实际怎么连接视频源、读取画面、写共享内存。
    FrameReaderRegistry：在 AiVision 主进程中统一读取各摄像头的最新帧。

    摄像头总开关：数据库 AiCameraConfig.enable，对外返回字段叫 enabled。
    功能开关：各 feature 配置表中，这台摄像头对应配置行的 enable。
    运行开关：Orchestrator 根据总开关和功能开关，计算交给 Runtime 的 enable。
        当前规则是：摄像头总开关开启，并且至少有一个检测功能启用，才需要采集。
        因此“摄像头记录已创建”不等于“已经拉流”，还要检查功能绑定和运行状态。

    一台摄像头可以同时服务多个检测功能，大家共用一份采集结果，
    不需要每个 Consumer 各自连接 RTSP，也不需要为每个功能再建一条摄像头记录。

二、每个文件负责什么

    orm.py：数据库模型，回答“摄像头主表长什么样”。
        AiCameraConfig 对应 ai_camera_config，一行是一台摄像头的基础配置。
        保存 id、name、url、shm_name、fps、max_restart、enable、department 等字段。
        各检测功能的 ROI、阈值、告警配置主要放在各自的 feature 配置表中。
        get_camera_by_key()：统一解析摄像头查询 key。
            整数直接查数据库主键；字符串依次匹配 shm_name、展示名称，
            最后尝试数字 ID 或 camera_<id> 别名，避免不同模块各写一套查询规则。

    config_manager.py：CameraConfigManager，摄像头配置的增删改查服务。
        list_cameras() / get_camera()：读基础配置，并汇总各功能的启用状态。
        create_camera()：创建摄像头，同时为所有已注册功能建立默认禁用配置。
        create_camera_for_feature()：在同一事务中创建摄像头并启用指定普通检测功能。
        create_camera_record()：供上述流程和物流通道服务复用的底层建档步骤；
            使用调用方提供的 session，不自行提交事务或发布通知。
        update_camera()：更新基础信息，不修改各功能的 ROI、阈值等配置。
        delete_camera()：在同一事务中删除各 feature 配置行和摄像头主记录。
        写入提交后刷新 config_cache，并通过 config_event_bus 通知运行模块。
        创建流程对 MySQL 死锁、锁等待超时有有限次事务重试。
        normalize_shm_names()：为历史数据补齐缺失的共享内存标识。
        ensure_feature_configs()：补齐缺失的功能配置行，默认禁用，保留已有启用状态。

    probe.py：视频源探测，回答“能否取得有效的视频尺寸”。
        probe_video_shape(url)：启动独立 ffprobe，读取第一路视频流的宽、高，
            返回 (H, W, 3)；当前探测默认超时为 8 秒，RTSP 使用 TCP。
        CameraProbeError：统一表示程序缺失、探测超时、无效输出等失败。
        探测错误文本中的 RTSP 账号密码会脱敏。
        探测只读取元数据；能取得尺寸，不代表后续持续采集一定稳定。

    runtime.py：CameraRuntime，一台摄像头的采集运行时。
        构造时探测实际尺寸；数据库里的 shape 默认值不能证明摄像头已连通。
        start()：创建 Python 采集子进程，等待第一张完整帧写入共享内存后才算就绪。
        _start_ffmpeg()：子进程内启动 ffmpeg，按 fps 和尺寸输出 rawvideo / bgr24。
        _read_frame()：分段读取完整一帧，并定期检查停止信号。
        _capture_loop()：读取图像、按配置检查异常画面、交替写入两块共享内存，
            更新 active_index 和 frame_seq，再继续下一帧。
        CameraStreamError：管道关闭、读取失败等流异常，可尝试只重启 ffmpeg。
        其他采集程序异常会记录并退出，由外层管理器发现后恢复。
        stop()：通知采集子进程退出；必要时 terminate / kill，并回收进程组及共享内存。
        ffmpeg 由采集子进程持有，正常退出时在其 finally 中清理，父进程提供兜底。

    runtime_manager.py：CameraRuntimeManager，所有摄像头采集进程的生命周期管理。
        initialize_configs()：把配置转成 Manager.dict，并建立跨进程索引和帧序号。
        start_all() / stop_all()：批量启动、停止采集和 Watchdog。
        start_camera() / stop_camera()：操作指定 shm_name 的采集运行时。
        _start_one()：按配置创建 CameraRuntime，等待首帧，注册共享内存读取视图。
            实际尺寸会写入共享运行配置，供 FrameReader 创建正确的 NumPy 视图。
        update_camera_config()：更新期望配置；CameraRuntime 持有配置快照，
            新值在下次创建运行时生效，是否重启由 Orchestrator 的变更处理决定。
        remove_camera_config()：连同运行配置一起移除，避免删除后被 Watchdog 再拉起。
        Watchdog：检查采集进程退出、画面长期停更，以及应该运行却尚未启动的摄像头。
        运行异常经队列和回调交给 Orchestrator，并按冷却时间限制重复通知。

    frame_reader.py：FrameReaderRegistry，主进程里的共享内存读取器集合。
        register()：附加 <shm_name>_0 / <shm_name>_1，创建两块 NumPy 图像视图。
        start_all()：每台已注册摄像头启动一个读取线程；集合运行中新增注册也会开线程。
        _read_loop()：只在 frame_seq 表示有新帧时复制图像，复制后复查索引和序号；
            发现期间发生切换就丢弃这次读取，等待下一轮。
        latest_frames[shm_name]：最新一张完整图像，发布前标为只读。
        latest_frame_times[shm_name]：最近成功读取新帧的时间，用来判断是否停更。
        latest_frame_seq[shm_name]：最近发布的帧序号，用来识别新帧。
        unregister() / stop_all()：停止读取、清理快照和元数据、关闭共享内存连接。
        Consumer、API、证据记录器共用快照；画框或修改像素前应先 frame.copy()。

三、一台摄像头有哪些进程、线程和内存

    AiVision 主进程
        ├─ CameraRuntimeManager：管理采集运行时和 Watchdog
        ├─ FrameReaderRegistry：每台摄像头一个读帧线程
        └─ CameraRuntime 创建的 Python 采集子进程
               └─ ffmpeg 子进程：连接 RTSP，解码并输出 BGR 原始像素

    ffprobe 是探测阶段临时启动的独立程序，探测结束就退出。
    “FrameReader”在这里指读取线程及其管理逻辑，不是另一层采集子进程。

    视频帧数据链：
        RTSP → ffmpeg → stdout 中的 raw BGR frame → Python 采集子进程
            → 共享内存 buffer 0 / buffer 1 交替写入
            → active_index 表示最新完整帧在哪块，frame_seq 表示是否产生新帧
            → 主进程读帧线程 copy → latest_frames[shm_name]
            → Consumer / 物流通道 / API 预览 / 证据记录器

    一张 BGR 图像的形状是 (H, W, 3)，每通道为 uint8，一帧字节数是 H * W * 3。
    双缓冲负责跨进程传图，latest_frames 是主进程里的独立快照；
    不要把它当成完整录像缓存，慢读者可能跳过中间帧，只获取当时最新的画面。

四、和其他模块怎么联系

    api/routes/cameras.py → CameraConfigManager → 数据库 / Cache / Event：
        GET /api/cameras、GET /api/cameras/{key}：查询列表和单台配置。
        POST /api/cameras、PATCH /api/cameras/{key}、DELETE /api/cameras/{key}：
            管理员新增、修改和删除摄像头；普通用户读取时按部门权限过滤并隐藏视频源。
        当前帧接口经 Orchestrator 取得新鲜的原始帧或指定功能的标注帧，再编码为 JPEG。

    api/routes/features.py、features/_base/config_manager.py：
        管理摄像头与普通检测功能的绑定、ROI、阈值和告警配置。
        FeatureSpec 描述有哪些功能及其 ORM，CameraConfigManager 按 all_specs() 建默认行。
        “停用这台摄像头的某个功能”修改功能配置，不等于删除摄像头主记录。

    core/events.py、core/cache.py、runtime/orchestrator.py：
        配置提交 → 刷新缓存 → camera_added / camera_updated / camera_removed 事件
            → Orchestrator 接收 → 更新 Consumer 和 CameraRuntimeManager。
        新增：按最新配置决定是否启动采集。
        修改：url、fps、max_restart、enabled 等运行字段变化时重建或停止采集；
            仅改 name、department 通常刷新业务配置，不重启采集进程。
        删除：移除 Consumer 的摄像头状态，刷新物流业务，移除采集配置并回收资源。
        功能启停：重新计算这台摄像头是否仍需采集；其他功能仍使用时保留采集进程。

    features/、inference/：
        Consumer 从 latest_frames 取图、裁 ROI，再经推理队列交给模型 Worker。
        摄像头可采集与模型可推理是两种状态，检测功能还需要自己的模型等依赖可用。

    features/detect_logistics_single_person/：
        复用摄像头采集和最新帧，管理通道成员及通道检测；成员的新增、绑定、移除
        使用通道服务，不能用普通功能新增接口代替通道的建档和绑定事务。

    alarms/evidence/evidence_recorder.py：
        通过帧读取层取得原始画面，维护告警前后的视频证据；Camera 本身不管理告警录像。

五、摄像头 ID、共享内存名和部门的区别

    camera_id：数据库整数主键，feature 配置等关联记录通过它引用摄像头。
    name：给人看的展示名称，可以通过配置接口修改。
    shm_name：运行层稳定标识，关联共享内存、帧字典和采集运行时，必须唯一。
        服务层未收到 shm_name 时，会生成 camera_<数据库 id>。
        配置返回值中的 id 为兼容前端使用的是字符串 key，整数主键另放在 camera_id；
        不要仅凭字段名 id 就假设它一定是数据库整数。

    camera.department：摄像头明确归属的事业部。
    FeatureSpec.departments：该功能声明适用的事业部。
    user.departments：当前账号被授权访问的事业部列表。
        camera_access_departments() 优先使用摄像头的明确归属；历史记录没有归属时，
        才根据它已启用功能的部门集合推导。API 再与用户授权部门比对。
        只修改前端显示或摄像头名称不会改变权限归属。

六、如果我要新增、修改或删除摄像头

    新增：
        1. 使用对应检测功能的现有“新增摄像头”入口，填写名称、视频源、帧率和部门。
           普通功能走 POST /api/features/{feature}/cameras，建档同时只启用目标功能。
           单部门功能可自动使用该部门，多部门功能需要明确选择合法归属。
           该接口可省略 shm_name，由服务层生成；直接 POST /api/cameras 时，
           当前 CameraCreateRequest 仍要求传入 shm_name，而且所有功能默认禁用。
        2. 物流摄像头通过对应通道的新增/绑定流程加入，保证摄像头与通道关系一起保存。
        3. 配置功能所需的 ROI、阈值和告警项；确认总开关、目标功能及检测运行已开启。
        4. 检查采集就绪、新帧持续更新，再检查模型结果和业务判定。
           API 保存成功只说明配置已写入，不能代替实际视频源连通性检查。

    修改：
        通过 PATCH /api/cameras/{key} 或页面保存基础配置；ROI、业务阈值走功能配置。
        运行参数变化经事件触发采集重建，名称或部门等展示/归属变化走配置刷新。
        现有 PATCH 请求模型不提供 shm_name 和 max_restart 字段；服务内部支持的字段
        不一定全部对 HTTP 接口开放，扩展接口前要同步检查请求模型和测试。
        绕过服务层直接改数据库，不会自动刷新 Cache 或发布热更新事件。

    暂停使用：
        只停某项检测，关闭该摄像头的对应功能；整台停用，关闭摄像头 enabled。
        单独调用运行管理器的 stop_camera() 只停当前进程，期望配置仍启用时
        Watchdog 可能再次拉起，因此持久停用要走配置保存流程。

    删除：
        管理员通过 DELETE /api/cameras/{key} 删除整台摄像头及所有 feature 配置，
        提交后由删除事件通知运行层清理 Consumer、采集进程和共享内存读取状态。
        仅从某个功能停用，或从物流通道移除成员时，应使用相应业务入口，
        先区分操作对象是“功能绑定”“通道成员”还是“整台摄像头”。

七、如果摄像头没有画面，沿哪条链排查

    1. 查配置和权限：记录、shm_name、部门、总开关、功能启用状态是否符合预期。
    2. 查 probe.py 的探测结果：ffprobe 是否可用，视频源是否能返回有效尺寸。
    3. 查 CameraRuntime：采集子进程和 ffmpeg 是否存活，是否已产生首帧，是否反复断流。
    4. 查 FrameReader：共享内存是否已注册，frame_seq 和最新帧时间是否持续变化。
       is_active() 表示读取视图已注册，不保证画面一直更新；还要结合新鲜度判断。
    5. 有原始画面但无检测结果时，再检查 Consumer、模型状态、ROI 和推理结果。

    自动恢复有两层：
        内层 CameraRuntime：流异常时在时间窗口内有限次重启 ffmpeg，耗尽后退出采集。
        外层 CameraRuntimeManager：采集进程退出或画面长期停更时重建整个运行时，
            对期望启用但未运行的摄像头也会定期重试。
        max_restart 是内层窗口内的重启限制，不是整个系统永久停止恢复的总次数。

八、修改后怎么验证

    在项目根目录、已配置测试环境的 aivision Python 环境中运行：
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_camera_probe.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_camera_frame_response.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_orchestrator_camera_update.py
        python -m pytest -q -c AiVision/pyproject.toml AiVision/tests/test_orchestrator_camera_frame.py
    如果涉及摄像头建档、事务、功能绑定或物流成员，还要运行
    test_logistics_channel_service.py 和 test_logistics_channel_api.py 中的相关测试。
    自动化测试使用替身、临时数据库或共享内存；真实视频源仍需在部署机器验证首帧、
    连续取帧、断流恢复，以及停止/删除后的资源回收。
"""
