"""
features/face_recognition/：人脸身份识别与人员授权判断

这个功能检测画面中的人脸，与本地人员特征索引匹配，再结合人员授权状态判断结果。
“识别到是谁”和“是否允许”是两个判断；未知人员与已识别但未授权人员也分别表达。
本文件只作说明，功能声明在 spec.py，由 features/registry.py 统一注册。

一、功能标识与模型依赖

    业务标识 recognize_face，显示名称“人脸身份识别”，报警类型为 7。
    依赖 insightface，由 FaceRecognizerWorker 执行检测、特征提取和底库匹配。
    face_dwell 只判断人脸逗留，本功能关注人员身份、授权和识别记录。
    事业部访问范围由当前功能分配和账号权限决定，不在包入口硬编码。

二、每个文件和子目录负责什么

    spec.py：绑定 FaceRecognitionConsumer、FaceRecognitionConfig 和配置 Schema。
    orm.py/schema.py：身份识别配置、记录相关数据结构及接口契约。
    consumer.py：FaceRecognitionConsumer，按采样间隔调用 insightface。
        周期读取允许人员集合，给匹配结果补充 is_allowed，形成监控状态。
        未知或未授权人员可形成业务告警，_alarm_context() 提供主体和识别元数据。
        post_process() 还原坐标并标注，按配置把识别结果交给 RecognitionRecorder。
        start()/stop() 同时管理自身检测与识别记录写入器。
    records.py：RecognitionRecorder，按摄像头和人员等记录规则保存识别记录与截图；
        识别记录及其冷却独立于普通报警记录，媒体引用参与平台清理。
    library/：人员资料、授权、来源同步、注册照片特征生成和实时匹配索引。
        外部海康协议在 connectors/hikvision/，模型实现在 inference/。

三、一张人脸的处理流程

    摄像头 → ROI → insightface Worker → 检测、对齐、特征提取与 FaceIndex 匹配
        → Consumer 查询授权集合 → 已授权 / 已识别未授权 / 未知
        → 标注与结构化监控 → 识别记录，以及符合条件时的统一报警。
    匹配阈值影响是否认出身份，人员授权决定认出后是否允许，二者不能混为一个开关。
    模型失败时返回故障状态，不把失败结果伪装成一次成功的无人识别。

四、配置和前端怎么联系

    api/routes/face_recognition.py 提供人员库、授权和识别相关接口。
    前端 FaceRecognitionSection 与 face_recognition/ 组件展示配置、人员和记录。
    模型路径在 inference/ 管理；人员同步、照片特征生成是 library/ 的显式任务。
    仅保存识别阈值不会下载照片、重新同步海康或重新生成全部人员特征。

五、修改与验证

    修改匹配输出时同步 Worker、Consumer、记录字段和前端结构化展示。
    覆盖多人、已授权、未授权、未知、模型失败、授权刷新和识别记录冷却。
    检查 ROI 坐标、画面标注及告警主体一致，真实照片与模型需在授权的测试环境联调。
    仅补充本说明时检查语法和差异，不执行人员同步或模型加载。
"""
