"""
runtime/：启动初始化、资源编排和运行状态

这个目录负责把摄像头、推理 Worker、Consumer 和告警设施组织成可运行的系统。
具体检测规则位于 features/，模型实现位于 inference/，这里协调它们的生命周期。
本文件只作讲解，导入本包不会在这里建表、结束进程或启动检测。

一、每个文件负责什么

    bootstrap.py：bootstrap_database() 导入业务 ORM，将缺失表创建到数据库，
        再核验正式配置及业务表结构。已有表结构不符时需要显式离线迁移，
        create_all() 不会自动替已有表补列或转换历史数据。
    orchestrator.py：Orchestrator 总编排器，持有摄像头管理器、各 Consumer、
        物流通道运行时和保安室运行时，并衔接共享推理、帧读取、告警实例。
        init_orchestrator() 创建全局实例；get_orchestrator() 获取已初始化实例。
        start()/stop() 组织启停，配置事件处理器刷新受影响的运行对象。
        runtime_status() 及监控读取方法向 API 提供当前快照。
    overview.py：build_overview() 从本进程服务和运行状态组织总览响应。
        按账号权限筛选资源，按物理摄像头统计，避免多功能重复计数。
    process_cleanup.py：启动前匹配并清理 Linux 上的摄像头、模型及采集管线残留。
        这是会结束匹配进程的运维动作，不是状态查询，也不清理告警媒体。

二、启动时的主要顺序

    main.py 加载环境与 Settings → bootstrap_database() → multiprocessing.Manager
        → init_orchestrator() → Orchestrator.start()。
    start() 准备摄像头和功能配置、缓存及异常通知，清理匹配的残留进程，
        启动摄像头采集、共享帧读取、证据录制和告警写入，配置告警分发依赖，
        再衔接保安室运行时、推理队列和 Worker、物流通道及各功能 Consumer。
    正式入口随后启动 Uvicorn；创建 FastAPI 对象本身不会完成上述资源准备。

三、配置变化怎样到达运行实例

    配置服务完成持久化 → config_event_bus → _handle_runtime_config_change()
        → 摄像头启停/重启、Consumer 配置刷新或业务 Runtime 更新。
    影响采集源的修改与仅改变检测阈值的修改处理方式不同，不能一律重启摄像头。
    摄像头总开关与功能需求共同决定采集是否运行，功能分配权限不等于检测开关。
    模型路径重载由 InferenceRuntimeManager 管理，喇叭设备由自己的管理器同步。

四、停止与异常处理

    stop() 先停止 Consumer 和业务汇总，再关闭推理、通知、证据与记录写入，
        最后回收帧读取、采集等资源；main.py 还负责共享 Manager 的关闭。
    摄像头和模型管理器可回报运行异常，Consumer 线程监控也由编排器衔接。
    系统异常通知读取 core/system_config.py 的策略，并按对象与异常类型控制重复。
    单个子模块的 stop()、资源清理及部分启动失败，需要各自明确处理和验证。

五、如果我要接入新的运行资源

    明确由谁创建、谁持有、先于谁启动、晚于谁停止，以及配置修改后如何刷新。
    普通检测功能优先通过 FeatureSpec 注册，复用 Consumer 启动路径。
    新增业务 ORM 要检查 bootstrap 的导入与结构核验，不能只创建 Python 类文件。
    新增监控状态时同步 API 响应和前端显示，不把内部对象直接当作可序列化结果。

六、修改后怎么验证

    检查正常启停、重复调用、依赖启动失败、配置热更新和停止后的资源回收。
    总览修改要覆盖同摄像头多功能、权限过滤、离线及 AGV 待机/检测状态。
    本说明的语法检查不需要启动真实采集，也不应触发残留进程清理。
"""
