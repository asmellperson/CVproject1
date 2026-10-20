"""
inference/：模型推理模块

Inference 将 Consumer 送来的图片交给模型推理，再把检测结果送回对应 Consumer。
这个目录负责“模型怎么加载、怎么推理、进程怎么运行”；检测结果是否构成违规、
持续多久才报警，由 features/ 下的 Consumer 或物流通道业务模块判断。
本文件只作讲解，导入本包不会在这里加载模型或启动 Worker。

一、先分清模型名称和模型文件

    逻辑模型：业务使用的固定名称，例如 yolo_human、yolo_phone、insightface_detection。
        名称、Worker 类、输出类型、类别过滤和默认推理参数写在 model_registry.py。

    物理权重：当前服务器上实际加载的模型文件，例如 /models/person_phone.pt。
        路径写在本机 YAML 中，由 model_paths.py 读取和保存。
        YAML 的 models.<name>.path 中，name 必须与注册表中的名称对应。

    一个逻辑模型一个输入队列，一个检测功能一个结果队列。
    相同 Worker 类使用同一个物理文件时，会共用一个 Worker 子进程。
    例如 yolo_human 和 yolo_phone 可以共用人体/手机权重，但分别过滤人体和手机类别。
    是否共享按 Worker 类和文件的设备号、inode 判断，符号链接、硬链接也能识别。

二、每个文件负责什么

    model_registry.py：固定模型注册表，回答“系统有哪些模型、用什么规则推理”。
        ModelSpec：一个逻辑模型的定义；冻结的数据类，字段不能在运行时修改。
        MODEL_SPECS：按模型名称索引的只读注册表。
        get_model_spec(name)：按名称取定义，未注册名称会抛出 KeyError。
        不做数据库配置 CRUD，也不保存本机权重路径。

        YOLO 模型使用 workers/yolo_detector.py 中的 YoloDetectorWorker：
            yolo_human：type_label="person"，class_filter=(0,)，conf=0.3。
            yolo_phone：type_label="phone"，class_filter=(1,)，conf=0.3。
        YOLO 默认 iou 是 0.5；class_filter=None 表示不按类别 ID 过滤。
        这些类别 ID 要与实际权重的训练类别一致，不能照搬到任意权重上。
        insightface_detection 使用 FaceDetectorWorker，只加载 det_10g.onnx 做人脸检测。
        insightface 使用 FaceRecognizerWorker，检测后提取特征并匹配人员索引。
        两者复用 InsightFaceDetector 代码，但 Worker 进程和检测 Session 各自独立；
        身份识别还持有 w600k_r50.onnx Session，照片特征任务也独立加载这两个模型。

    model_paths.py：本机路径配置，回答“这个模型的权重文件在哪里”。
        默认配置文件是 AiVision/config/model_paths.yaml，示例见同目录
        model_paths.example.yaml；MODEL_PATHS_CONFIG 环境变量可以更换配置位置。
        配置文件的相对路径以 AiVision/ 为根；权重路径要求为本机绝对文件路径。
        load_model_paths()：读取 YAML 并缓存结果，对外返回副本。
        validate_model_path()：检查权重是否为存在、非空且可读的普通文件。
        save_model_path()：校验模型名称和路径，加锁后原子保存，并清除读取缓存；
            尽量保留手写注释、其他模型项及文件权限。
        路径可读不代表权重能被模型加载器正确加载，最终还要看 Worker 的加载状态。

    runtime_manager.py：InferenceRuntimeManager，所有推理 Worker 的总调度器。
        initialize_queues()：按 MODEL_SPECS 建输入队列，按 all_specs() 建结果队列。
        start_all()：检查功能依赖的模型是否已注册，将相同物理权重分组，启动 Worker，
            等待就绪，然后开启 Watchdog；启动范围是所有 Feature.required_models 的并集。
            注册表中的其他模型仍可查询和配置路径，状态保持 not_started。
        stop_all()：停止监控并回收 Worker。
        Watchdog：发现退出、加载失败或超时后，按指数退避重试；次数耗尽时报告异常。
            重试次数、退避时间和就绪超时来自 core/settings.py 的运行配置。
        list_models() / runtime_status()：提供逻辑模型列表、路径、加载及自动恢复状态。
        update_model_path()：保存新路径；运行已启动且模型被 Feature 依赖时，异步重载受影响的 Worker 组。
            重载会处理旧、新共享关系，清掉受影响队列里的待处理任务，保留队列对象，
            让 Consumer 继续使用原来的队列；共享模型也可能一起暂停和重载。

    base_worker.py：BaseModelWorker，所有模型 Worker 的公共运行骨架。
        start()：创建独立子进程；stop()：通知退出，必要时 terminate / kill 并回收。
        _run()：先调用子类 load_model()，成功后标记 ready，再循环取任务并处理。
        _next_task()：轮流检查本 Worker 服务的逻辑模型队列，按来源补上 model_name。
        _execute_task()：调用 infer(model, frame, task_meta)，包装成功结果或异常结果。
        最后按 function_name 把结果放入对应 result_queue。

    workers/yolo_detector.py：YoloDetectorWorker，真正执行 YOLO 加载和推理。
        load_model()：用 YOLO(self.model_path) 加载当前服务器的权重。
        infer()：按 task_meta["model_name"] 读取对应 ModelSpec；任务中的 conf/iou
            可以覆盖默认值，可选 imgsz 只在任务显式提供时传入 model.predict(frame)。
        从预测结果提取 bbox、confidence、class_id，按 class_filter 过滤，
        优先使用 class_labels 中的类别标签，否则使用 type_label，返回 list[dict]。
        Worker 共享权重时，每次任务仍使用自己的逻辑模型参数和类别过滤规则。

    workers/yolo_pose.py：YoloPoseWorker，输出原图像素坐标中的人体框及 COCO 17 关键点。
    workers/uniform_classifier.py：UniformClassifierWorker，离线加载 ConvNeXtV2 Tiny，
        对输入的人体 crop 输出 uniform 正类概率，不包含业务阈值判断。

    workers/__init__.py：Worker 子包入口；具体 Worker 类在各实现文件中定义，
        固定模型与 Worker 的对应关系由 model_registry.py 声明。

    contracts.py：Consumer 和 Worker 共用的结果约定。
        build_inference_result() 保留 camera_id、roi_id、function_name、request_id、
        model_name，并附带 status、detections、错误信息和推理耗时。
        状态包含 ok、error、dropped、timeout、unavailable。
        Worker 负责产生推理成功或模型异常结果；请求方还会处理队列满、超时和不可用。
        “成功但没有目标”和“没有成功完成推理”含义不同，业务判断要先看 status。

三、和其他模块怎么联系

    runtime/orchestrator.py：负责整体启停，组织摄像头、推理 Worker、Consumer、
        物流通道和告警模块；把推理队列交给业务模块，并接收运行异常通知。
        RuntimeManager 负责建队列和管进程；每张图片通过队列直接送入 Worker。

    cameras/：CameraRuntime 读取 RTSP 并写共享内存；FrameReader 读取最新帧。
        模型 Worker 不负责连接 RTSP，收到的是业务模块准备好的 frame。

    features/_shared/spec.py 与 features/<功能>/__init__.py：
        FeatureSpec.required_models 声明功能使用的逻辑模型名，all_specs() 汇总功能。
        features/_shared/consumer.py 提供投递任务、等待结果等公共能力；具体 Consumer
        负责裁剪 ROI、设置任务参数、解释检测结果和判断告警。
        features/logistics_channel/consumer.py 逐路推理；通道 Runtime 只汇总快照。

    api/routes/models.py → InferenceRuntimeManager → model_paths.py / Worker：
        GET /api/models：读取固定模型的配置及运行状态。
        PATCH /api/models/{model_name}/path：管理员保存本机路径，并按运行状态触发重载。
        当前 API 没有动态创建模型、删除模型或启用/禁用单个模型的接口。

    unified_frontend/src/components/AiVisionModelConfig.tsx：
        通过 src/lib/aivision.ts 调用上述接口，按页面传入的 requiredModels 展示模型，
        提供路径保存和状态轮询。前端名称和后端 FeatureSpec 需要一起维护。

    core/settings.py：配置文件位置及 Watchdog 参数。
    core/logger.py：推理和进程日志。
    alarms/：由业务层衔接通知、截图、录像及违规记录。

四、一张图片的完整数据链

    RTSP 摄像头
        ↓ CameraRuntime 采集
    SharedMemory 共享内存
        ↓ FrameReader 读取最新帧
    Consumer / 物流通道业务模块
        ↓ 裁 ROI，构造带 model_name、function_name、request_id 等信息的 task
    infer_queues[逻辑模型名]
        ↓ BaseModelWorker._next_task() 取任务
    Worker 子进程中的 _execute_task()
        ↓ YoloDetectorWorker.infer() → model.predict(frame)
    contracts.build_inference_result() 包装统一结果
        ↓ result_queues[function_name]
    Consumer / 物流通道业务规则
        ↓ 目标关联、持续时间等判定
    告警通知、证据和违规记录

五、如果我要添加一个模型

    1. 先确定新增的是逻辑模型，还是只给已有模型换权重。
       已有模型只换权重路径，使用下面“更换权重”的流程即可。

    2. 在 model_registry.py 的 MODEL_SPECS 构造列表中增加 ModelSpec，名称保持唯一。
       例如新增一个兼容现有 YOLO 检测输出的模型，可参照现有三个注册项填写：
           ModelSpec("yolo_custom", YoloDetectorWorker, "custom", (0,), conf=0.5)
       示例中的类别 ID、输出类型和阈值都要按真实模型和业务调整。
       如果需要新的模型框架或输出处理，在 workers/ 下实现 BaseModelWorker 子类，
       实现 load_model() 和 infer(model, frame, task_meta)，在注册表中导入并绑定。
       新 Worker 返回的数据应兼容业务需要；公共结果封装继续由 BaseModelWorker 完成。

    3. 在本机 model_paths.yaml 的 models 下增加同名配置，例如：
           yolo_custom:
             path: /absolute/path/to/custom.pt
       同步补充 model_paths.example.yaml 中的示例；只改示例不会改变实际加载路径。
       只往 YAML 增加名称也不会注册新模型，注册表必须有对应项。

    4. 在使用它的 features/<功能>/__init__.py 中配置 required_models，
       并检查 Consumer 实际投递的模型名和对检测结果的处理方式。
       仅注册模型会让它参与启动，但不会自动创建检测业务。
       需要在前端页面展示时，同步调整 AiVisionModelConfig 的 requiredModels。

    5. 更新注册表、Worker 和相关业务/API 测试，重启 AiVision 后端进程后验证。
       固定注册表随 Python 模块导入，增删注册项或修改默认参数都需要进程重新加载代码；
       仅在前端停止再启动检测，不能代替后端进程重启。

六、如果我要删除一个模型

    1. 先全仓查找该逻辑模型名，处理 FeatureSpec.required_models、Consumer、
       物流通道、前端 requiredModels、示例及测试中的引用；依赖它的业务需要一起调整。
       特别检查 Consumer 直接使用的模型名：例如手机检测除了 yolo_phone，
       还可能通过 PERSON_MODEL_NAME 使用 yolo_human 做人体关联。
       仅从 required_models 移除名称，不等于所有业务依赖都已处理。

    2. 从 model_registry.py 的 MODEL_SPECS 构造列表移除该 ModelSpec。
       如果 FeatureSpec 仍引用已删除名称，start_all() 会拒绝启动并报告未注册模型。
       同步清理本机 YAML 和示例中的对应项；只删 YAML 路径不会删除模型，
       仍在注册表中的模型会继续尝试启动，并因缺少路径失败。

    3. Worker 类只有在没有其他模型使用时才考虑删除。
       物理权重文件也可能被其他逻辑模型共用，删除注册项不会自动删除权重文件。

    4. 更新相关测试和页面配置，重启 AiVision 后端进程。
       验证模型列表不再包含它、剩余模型正常加载、相关检测功能符合调整后的行为。

七、如果只是更换已有模型的权重

    使用前端“模型配置”中的路径保存，或管理员调用 PATCH 路径接口。
    运行已启动时会异步重载，未启动时只保存，等启动时再加载。
    configuration_saved=true 表示文件已保存；还要继续看 reload.status 和
    runtime.running，确认是否真正加载成功。
    手动编辑 YAML 不会自动清除进程内缓存，也不会自动重载 Worker；手动修改后
    重启 AiVision 后端进程。优先通过现有路径保存流程完成在线更换。

八、修改后怎么验证

    核对模型注册、推理结果、故障恢复和 /api/models 的 runtime、reload 状态，
    并验证受影响 Consumer / API 的行为。涉及页面模型配置时，在 unified_frontend/
    下运行 npm run build。实际权重需在部署机器确认能加载并完成推理。
"""
