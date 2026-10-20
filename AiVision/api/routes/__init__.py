"""
api/routes/：按业务组织的 HTTP 路由

每个文件定义自己的 APIRouter，由上一级 app.py 显式挂载。
这里处理 HTTP 参数、权限、响应和错误映射；业务规则继续由所属服务执行。
本文件只作目录说明，不集中导入路由，也不负责创建 FastAPI 应用。

一、每个文件负责什么

    cameras.py：摄像头配置、功能关联和摄像头相关操作。
    features.py：按 FeatureSpec 查功能、管理逐摄像头配置和检测监控入口。
    models.py：固定逻辑模型的状态查询与本机权重路径保存。
    departments.py：固定事业部查询，以及管理员读取、保存功能分配。
    runtime.py：运行健康、状态及整体运行控制。
    overview.py：平台总览，调用运行层汇总权限范围内的能力和摄像头状态。
    alarms.py：告警列表、统计、图片、视频，以及受签名保护的公开缩略图。
    alarm_dispositions.py：告警处置查询、分页和保存。
    exception_alerts.py：系统异常通知策略配置。
    horns.py：喇叭设备配置及相关运行操作。

    logistics_channels.py：物流通道、成员、ROI、通道监控和运行状态。
    guard_behavior.py：保安室、成员、规则、告警策略与监控。
    security_inspection.py：安检配置、福达AI服务检查、状态和历史。
    agv_person_check.py：触发 AGV 人体检测，等待结果并衔接配置的回调协议。
    face_recognition.py：人员库、人员授权、身份识别配置及识别记录。
    visual_language_detection.py：指令驱动智慧安防设置、结果、事件和视频提问。

二、公共接口与专属接口怎么分工

    features.py 通过 registry 查询功能，承载可以共用的逐摄像头操作。
    通道、保安室、人员底库等具有额外业务对象，需要自己的专属路由和服务。
    功能的持久化标识以 FeatureSpec.name 为准，例如 intrusion 对应 blocks，
    person_dwell 对应 detect_human；不能直接把目录名当作接口参数。
    登录、账号管理和访问审计路由位于仓库根目录 auth/api.py，同样由 app.py 挂载。

三、一次配置写入的流程

    请求体 → Schema 校验 → 角色、事业部和资源权限检查 → 配置服务
        → 数据库事务提交 → 所属模块刷新缓存或通知运行对象 → 返回配置。
    模型路径保存使用 YAML 和推理重载流程；告警处置写入不会修改检测规则。
    接口不能用“已保存”替代模型已加载、摄像头已在线等运行状态。

四、如果我要增加或删除路由

    优先扩展最接近的业务文件；可复用的依赖放 ../deps.py。
    增加新 router 时同步 app.py 的导入和 include_router，以及前端请求封装。
    删除或改名时检查调用方、权限入口、响应 Schema 和页面错误处理。
    不在路由内另起采集进程或直接加载模型，使用已有运行对象。

五、修改后怎么验证

    对实际影响的接口检查成功响应、参数错误、权限拒绝和资源不存在。
    修改公开媒体接口时同时验证签名过期与越权访问；修改配置时检查保存后读取。
    仅修改本目录说明时，语法和差异检查即可。
"""
