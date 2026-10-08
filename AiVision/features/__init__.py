"""
features/：检测功能与业务规则

模型回答“图里有什么”，这里回答“这些结果是否构成业务异常、怎样计时和告警”。
每个功能把声明、配置结构、数据库映射和 Consumer 放在自己的目录中，
复杂业务再拆分 service、runtime 和纯状态模块。本文件不自动发现或注册功能。

一、先分清包名和业务标识

    Python 包名用于组织源码；FeatureSpec.name 用于数据库、缓存、队列和 API。
    intrusion → blocks：区域入侵。
    door_state → detect_door：大门开关检测。
    face_dwell → detect_face：人脸逗留。
    person_dwell → detect_human：人员违规逗留。
    phone_detection → detect_phone：手机使用检测。
    face_recognition → recognize_face：人脸身份识别及授权判断。
    logistics_channel → detect_logistics_single_person：物流通道单人检测。
    guard_behavior、security_inspection、agv_person_check、visual_language_detection
        的包名与业务标识相同，分别对应保安行为、安检、AGV 和指令驱动智慧安防。
    前端页面 ID 还有自己的命名，接口参数应使用正式业务标识。

二、公共入口和每类文件负责什么

    registry.py：唯一显式注册入口，将各目录 spec.py 的 SPEC 汇入 _BUILTIN_SPECS。
        all_specs() 返回注册表副本，get_spec(name) 查询功能，未找到返回 None。
        list_orm_classes() 提供功能配置 ORM；构建时校验功能名与报警类型的唯一性。
    _shared/spec.py：冻结的 FeatureSpec，声明 Consumer、ORM、Schema、
        required_models、optional_models 和 alarm_types。
    _shared/：公共配置服务、帧处理、ROI、推理通信、告警衔接与逗留跟踪。
    各功能的 spec.py：定义 SPEC；仅导入目录的 __init__.py 不会替代显式注册。
    各功能的 orm.py/schema.py：持久化和参数契约，不能只改页面字段而漏掉这里。
    各功能的 consumer.py：消费画面并形成结果；复杂汇总交给所属 runtime/state。

三、几种不同的运行方式

    普通检测：Consumer 读取帧、裁 ROI、调用模型、解释结果并提交告警。
    门状态：直接比较图像，不依赖推理 Worker。
    物流通道/保安室：Consumer 发布单路快照，业务 Runtime 汇总多摄像头结论。
    安检：人体检测形成交互会话，后台任务调用千问判定采样关键帧。
    AGV：摄像头可待机，HTTP 请求到来才进行短时多帧检测。
    指令驱动智慧安防：业务调度调用外部 JoyAI Adapter，不在本地 Worker 加载主模型。

四、和其他模块怎么联系

    runtime/orchestrator.py 按注册表创建 Consumer，并注入共享帧、队列和业务依赖。
    inference/ 管理模型，cameras/ 提供画面，alarms/ 处理证据和通知。
    core/cache.py 与配置服务按 SPEC 找配置表，api/routes/ 提供公共及专属接口。
    departments/ 的功能分配控制访问权限，运行启停仍取决于具体检测配置。

五、如果我要增加或删除功能

    增加功能：确定业务标识，准备 ORM、Schema、Consumer 和 SPEC，再显式加入 registry。
    声明所需模型及正式报警类型，检查 bootstrap、权限、功能分配和前端调用。
    特殊业务对象放独立 service/runtime，不把所有状态塞进公共 Consumer。
    删除功能：先处理运行实例、数据库数据、分配与页面引用，再移除注册项；
        同时确认其模型和报警类型是否仍被其他业务使用。

六、修改后怎么验证

    验证注册、默认配置、读写校验、权限、Consumer 生命周期和实际规则分支。
    涉及模型时区分空检测与推理失败；涉及计时和多摄像头时覆盖断流与过期快照。
    仅改本文件说明时检查语法及 Git 差异，不需要启动全部检测功能。
"""
