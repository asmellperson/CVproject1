# 福达视觉平台

福达视觉平台将摄像头管理、十三项视觉检测、告警证据、统计和用户管理整合在一个系统中。当前运行结构是 **React/Vite 前端 + AiVision 唯一业务后端**；认证模块 `auth` 由 AiVision 加载，共用 MySQL。

本文按当前源码整理（2026-09-20）。算法、配置和 API 细节见 [AiVision README](AiVision/README.md)，部署操作见 [运行手册](run_guide.txt)。本机的 `unified_frontend/info.md` 提供页面与组件导览，该文件按现有 Git 忽略规则在本地维护。

## 1. 运行架构

```mermaid
flowchart LR
    Browser[浏览器] --> Frontend[unified_frontend · Vite :3000]
    Frontend -->|/api| API[AiVision · FastAPI :7862]
    API --> Auth[auth · 认证 / 用户 / 访问审计]
    API --> Runtime[Orchestrator · 摄像头 / 模型 / 检测]
    API --> Records[总览 / 告警 / 统计 / 处置]
    API --> Assistant[福达AI助手 · 业务工具 / 对话审计]
    Assistant --> DB
    Assistant --> Qwen
    Auth --> DB[(共享 MySQL)]
    Records --> DB
    Runtime --> DB
    Runtime --> Media[图片与视频证据]
    Runtime --> Notify[喇叭 / 企业微信]
    Runtime -->|安检关键帧| Qwen[内部福达AI服务]
    Runtime -->|共享帧 / 视频提问| JoyAdapter[JoyAI Adapter :8070]
    JoyAdapter --> JoyAI[JoyAI 主模型 :7060]
```

运维脚本管理以下两个 tmux 服务：

| 服务 | 默认监听地址 | 启动入口 |
| --- | --- | --- |
| `unified_frontend` | `0.0.0.0:3000` | `npm run dev` |
| `aivision` | `0.0.0.0:7862` | `python -m AiVision.main` |

项目站点地址为 `https://aicv.fudar.com/`，网关部署需把请求转发至前端入口。Vite 的 `/api` 代理默认指向 `http://127.0.0.1:7862`，由 `VITE_AIVISION_TARGET` 覆盖；配置中也保留 `/ws` 的 WebSocket 代理。

保安行为与安检流程均在 `AiVision/features/` 中注册，使用同一套摄像头、推理、数据库和告警设施。内部福达AI为安检和福达AI助手提供模型服务，由独立的运维入口管理。

## 2. 仓库目录

```text
Fuda_CVPreject_V3/
├── unified_frontend/       # React + TypeScript + Vite
│   ├── src/auth/           # 登录状态、角色与事业部权限
│   ├── src/sections/       # 业务页面
│   ├── src/components/     # 业务组件与基础 UI
│   ├── src/hooks/          # 总览、轮询、主题等 Hooks
│   └── src/lib/            # API、导航和公共逻辑
├── AiVision/
│   ├── main.py             # 唯一后端正式入口
│   ├── api/routes/         # 检测、总览、告警、处置等 API
│   ├── runtime/            # 数据库 bootstrap、资源编排和总览
│   ├── cameras/            # 配置、FFmpeg 采集和帧读取
│   ├── inference/          # 模型注册、共享 Worker 和后台重载
│   ├── features/           # 十三项原生检测功能
│   ├── alarms/             # 记录、处置、证据、设备和通知
│   ├── assistant/          # 福达AI对话、配置工具、权限和执行审计
│   ├── departments/        # 固定事业部目录
│   ├── core/               # 环境配置、数据库、日志、缓存和事件
│   ├── connectors/         # 海康、福达AI与 JoyAI Adapter HTTP 协议
│   └── migrations/         # 历史数据的显式离线迁移
├── auth/                   # 认证、账号与访问审计
├── scripts/                # 双服务启动、停止和状态检查
├── docs/diagrams/           # 项目流程图
└── run_guide.txt            # 运维说明
```

## 3. 功能与业务标识

功能唯一注册入口是 [features/registry.py](AiVision/features/registry.py)。目录名、后端业务标识、前端页面 ID 各有用途，调用接口时应使用业务标识。

| 功能 | 功能目录 | 后端业务标识 | 前端页面 ID |
| --- | --- | --- | --- |
| 指令驱动智慧安防 | `visual_language_detection` | `visual_language_detection` | `visual-language-detection` |
| 区域入侵 | `intrusion` | `blocks` | `intrusion-detection` |
| 大门开关异常 | `door_state` | `detect_door` | `door-detection` |
| 人脸逗留 | `face_dwell` | `detect_face` | `face-detection` |
| 人员违规逗留 | `person_dwell` | `detect_human` | `human-detection` |
| 手机使用 | `phone_detection` | `detect_phone` | `phone-detection` |
| 警戒围栏 | `security_fence` | `security_fence` | `security-fence` |
| 非法闯闸检测 | `tailgating` | `tailgating` | `tailgating-detection` |
| 人脸身份识别 | `face_recognition` | `recognize_face` | `face-recognition` |
| 物流通道单人 | `logistics_channel` | `detect_logistics_single_person` | `logistics-single-person` |
| 保安行为规范 | `guard_behavior` | `guard_behavior` | `guard-behavior` |
| 安检流程规范 | `security_inspection` | `security_inspection` | `security-vlm` |
| AGV 无人运货 | `agv_person_check` | `agv_person_check` | `agv-person-check` |

各事业部的可访问功能由管理员在“系统管理 → 功能分配”中配置，保存于 MySQL 的 `department_feature_access` 表。管理员和普通账号进入检测页面均遵守事业部功能分配；管理员可查看全部事业部并修改分配，普通账号还需具有对应事业部的归属权限。取消分配不会停止检测或删除数据，摄像头是否参与检测仍取决于摄像头、功能及通道/保安室成员的开关和运行状态。

平台具有十三项检测能力，总览按账号可访问的事业部和功能汇总能力卡片、摄像头入口与功能数量。点击平台汇总中的“摄像头离线”可查看未在线设备的名称、所属事业部和状态，列表区分离线与已停用，并随总览刷新。AGV 摄像头待机时仍计入在线设备；只有尚未完成的检测请求计入“正在检测”，判定完成后即退出该统计。

### 福达AI助手

导航中的“福达AI助手”提供账号私有、按会话部门隔离的聊天。管理员可通过自然语言添加或删除摄像头、重命名、调整 FPS、启停、ROI、检测阈值和报警参数，也可管理物流通道、保安室、喇叭基本信息及系统配置。实际能力及参数约束由 `/api/assistant/capabilities` 和现有业务 Schema 提供；普通账号只能查询授权部门配置。

例如：“把二厂物流出口重命名为物流出口东侧，FPS 改成 8”“物流主通道只在工作日 08:00 到 18:00 报警”。模型先查询真实资源和当前参数，再提交局部修改；目标有歧义时需要补充说明。保存使用原业务事务、缓存和热更新事件，拒绝覆盖读取后发生的并发修改。聊天显示操作前后值、实际保存状态及操作编号，支持在配置未被继续修改时撤销参数修改；新建、绑定和删除不属于参数撤销范围。

普通检测参数按摄像头保存，资源搜索分别接收部门、功能和摄像头名称；参数名称通过业务 Schema 识别。例如非法闯闸的“人体置信度”对应 `value.threshold`，取值范围为 `0.01–1`。未指定摄像头时先查询该部门和功能下的候选，唯一目标读取当前版本后修改，多个目标则列出真实摄像头供选择；批量修改须有明确范围。

删除摄像头须明确目标，助手读取并核对版本后调用原删除服务，同时移除该摄像头的检测配置并通知热更新；保留其他摄像头和物流通道。删除后回查数据库，记录仍存在时不能报告成功。已绑定保安室的摄像头须先通过管理页面解除绑定。停用功能与删除摄像头分别处理，删除不可撤销。

添加摄像头需明确名称和事业部，可提供完整 RTSP 或 IP、账号和密码。后一种方式默认端口 `554`、路径 `/Streaming/Channels/101`，明确指定的端口和路径优先生效，账号密码按 URL 规则编码。`shm_name` 自动生成 `camera_数字`。凭据在进入模型和聊天数据库前替换为引用，仅暂存在服务器内存；重启或引用过期后需重新提供。建档成功不代表视频源已连通，启用检测仍需配置对应 ROI 和规则。

助手通过内部福达AI的 Chat Completions 接口对话，每轮先判断聊天、平台查询或配置任务。“你好”“你好哇”等整条独立问候直接识别为聊天，本轮模型请求不携带旧任务上下文；附带查询、配置请求或明确续办指令时仍结合历史进行模型分类。普通聊天直接返回自然语言，语气轻松、亲切、适度俏皮；平台任务使用严格工具 JSON，后端按本轮允许的操作类别校验执行。查询结论来自实际工具数据，配置结果来自业务操作记录，模型自行声称完成不能作为成功依据。配置已为目标值时明确反馈无需修改，缺少信息时通过澄清工具提问。

没有配置操作的聊天不会生成操作记录，工具指令不完整时不执行，工具格式错误最多纠正一次。任务分类严格校验 JSON 和 Schema，可恢复的分类格式或字段错误最多纠正一次，两次请求共用分类超时预算并遵守取消与并发限制。分类与平台工具请求使用 `response_format=json_schema`，模型服务须支持 Schema 约束；普通聊天使用自然语言，安检沿用 JSON 对象模式。分类输出预算默认 `1024` tokens，并受模型设置中的输出上限限制。配置任务未执行就返回正文时最多提醒模型执行一次，仍无有效结果则显示未完成；未知结果不自动重放。

查询计划区分能力目录、资源列表和实际配置。查询配置必须读完对应目标和分页，取得真实结果后由后端直接返回；名称列表不能替代参数值。历史同时按轮数与字符数限制，分类历史不携带助手答复正文。已读取的目标引用与待澄清请求在当前进程中短期保留，不缓存可复用的配置版本；权限变化导致原轮次不可见时，对应上下文失效。进程重启后依靠数据库中可见的最近历史继续理解，无法确认的目标需要澄清。

助手未独立保存模型设置时继承安检连接。后台任务有并发、队列及调用次数上限，不在启动阶段加载大模型或探测连接；与安检共享 `QWEN_MAX_CONCURRENT_REQUESTS` 请求预算。模型配置可在助手页面由管理员维护，部署后应使用实际模型验证对话和配置执行。

### 指令驱动智慧安防

检测导航按功能分配过滤，已分配“指令驱动智慧安防”时该功能位于检测导航首项。摄像头加入功能后由现有 Orchestrator 自动处理，共享帧经 `get_camera_frame_info()` 进入 `features/visual_language_detection/`，再由 `connectors/joyai/client.py` 调用 Adapter；浏览器只访问 AiVision API。

每台摄像头独立使用 `visual-language-{department}-{camera_id}` 会话，默认每秒发送一张新帧，同一摄像头串行处理并跳过重复帧。帧间隔、JPEG 质量、图像宽度、输出长度、采样参数、监控指令、ROI 和报警推送按摄像头保存到 MySQL。共享帧先经公共 ROI 裁剪，再发送给 JoyAI；空 ROI 表示全帧。监控页面使用统一统计卡片展示摄像头状态、启用摄像头数、最近推理耗时和最近结果时间；左侧展示实时画面与突出的最新理解结果，右侧提供聊天式视频问答和事件时间线。问答输入位于底部，本次提问与模型回答以不同气泡展示；静默结果不展示，回复只展示正文。提问响应和事件时间线保留同一帧的采集时间。

配置页依次为摄像头、监控指令、ROI 配置、推理参数、报警推送、喇叭设备。各标签共享当前摄像头草稿，保存时提交完整配置。ROI 使用 `AiVisionRoiEditor`，报警推送使用 `AlarmPushConfig` 管理当前功能的喇叭绑定、企业微信和报警间隔，喇叭设备管理由 `DetectionConfigTabs` 统一挂载。监控指令应要求仅在目标事件发生时输出结果；自动观察正文通过公共 `AlarmDispatcher` 按配置触发告警，静默、视频问答和处理错误不触发业务告警。

`AiVision/.env` 中的 `JOYAI_ADAPTER_URL` 指向 `http://172.16.0.32:8070`，模型名通过 Adapter 的 `/v1/models` 读取。`7060` 由 Adapter 调用，不进入 AiVision 业务客户端。Adapter 需启用 `HONOR_INBOUND_GENERATION_PARAMS=true` 才会采用摄像头保存的 `max_tokens`、`temperature`、`top_p`。管理员可修改绑定和参数；viewer 可在授权事业部内查看和提问。

### 普通检测与共享推理

```text
RTSP → FFmpeg 采集 → 双缓冲共享内存 → 最新帧缓存
     → 功能 Consumer → 共享模型 Worker → 业务规则
     → 标注画面 / 状态 / AlarmDispatcher
```

区域入侵使用人体框与警戒线侧别；门状态使用图像差分；人脸与人员逗留使用跟踪和持续时间；手机检测使用候选关联与持续确认；身份识别使用 InsightFace 和人员特征库，记录识别结果，不产生普通违规告警。

人脸身份识别共用人员资料和特征库，通行白名单按事业部独立保存。同一事业部的所有人脸识别摄像头共用该事业部白名单，添加或取消授权只影响当前事业部。

海康人员底库通过固定入口 `python -m AiVision.face_library` 依次同步人员资料和增量生成人脸特征。使用目标 Python 环境执行 `--install-systemd` 安装或更新定时任务，安装时自动写入当前项目和解释器路径并校验实际生效入口；任务结束后间隔 10 分钟再次执行。`--status` 同时检查定时器、入口和最近执行结果，部署用法见 [人脸库自动更新](AiVision/README.md#133-自动更新与-systemd-部署)。

模型名称和 Worker 类型由 `inference/model_registry.py` 固定注册，本机权重路径保存在 `AiVision/config/model_paths.yaml`。同一物理权重且 Worker 类型相同的逻辑模型可以共用进程。保存模型路径后需检查后台重载状态，HTTP `202` 只表示配置已接受。

YOLO 检测大图在进入进程队列前按当前 `imgsz` 等比例缩小，默认 `640`；模型结果恢复为原始 ROI 坐标。Consumer 保留原图用于跟踪、标注和证据，减少队列传图的数据量。

`GET /api/runtime/status` 按功能和摄像头返回推理统计。`last_outcome.timing_ms` 区分输入传输与排队、Worker 执行、结果返回和请求总耗时；公共 Consumer 循环的 `last_frame_timing` 记录读帧、业务处理、画图及实际处理间隔，用于定位多路检测更新缓慢的原因。

### 警戒围栏

`security_fence` 按摄像头保存每日禁入时段、时区和警戒 ROI，通行白名单按事业部管理，同一事业部的围栏摄像头共用。管理员在“围栏白名单”逐人设置允许状态并即时保存，无需先选择摄像头；未添加人员默认不允许通行，不同事业部和人脸身份识别功能的授权分别维护。两个时段均使用 InsightFace 比对完整有效人员特征库：禁入时段内 ROI 有人即形成异常时间报警，包括白名单人员；其余时段白名单放行，确认库内非白名单或库外未知人员后形成异常人员报警。白名单只决定准入，不限制身份识别范围。识别与人脸身份识别共用有效特征库，不检查白名单是否人人都有特征；个别人员缺少特征不阻塞其他人员识别，未匹配的人脸按未知人员规则确认。

身份识别使用完整画面，人体和人脸分别检测，监控同时显示人体框与人脸框；人员进入 ROI 后执行区域规则。库内身份复用人脸身份识别的匹配结论，在可靠的单摄像头轨迹内累计确认，单次无人脸不清空有效观测；库外未知身份额外核对人脸质量。禁入报警先记录，持续违规期间确认身份后补全同一记录，不重复通知；库外人员标记为“未知人员”。无有效身份依据或相似度不确定时保持“身份待核验”，不按等待时间判为未知人员，禁入时段仍然报警。短暂漏检或处理间隔变长时撤销通行身份，并在报警间隔窗口内保留事件关联；恢复后需当前有效人脸重新确认，持续违规不重复记录，不同人员分别记录。多人身份关联不明、配置变化或推理异常会重新核验。

待核验和未知人员按摄像头及当前可见违规人数共享报警间隔，新轨迹编号不能重置冷却；同时可见的多人仍可分别记录，库内身份确认后可独立记录。人脸识别等待上限由 `FENCE_INFERENCE_TIMEOUT_SECONDS` 配置，默认 5 秒；失败信息包含实际超时、模型或索引刷新错误。

围栏监控使用 JPEG 串行轮询，目标间隔 200 毫秒。预览按最新采集帧绘制 ROI，并叠加 5 秒内且规则时段、分辨率一致的人体和人脸检测结果；画面更新不等待模型推理完成，结果过期后撤销检测框。前端先解码新图，再替换已显示画面；短暂取图失败时保留上一帧并提示刷新异常。

围栏页面沿用其他检测页的实时监控和配置管理两个标签；监控区左侧展示摄像头选择和当前识别结果，右侧展示实时画面，支持拖动调整宽度，窄屏自动上下排列。配置包含摄像头、参数、ROI、模型和报警设置，报警间隔位于“报警推送”。报警统一在“数据中心 → 报警记录”中查看、筛选和处置，显示姓名、工号和摄像头所属事业部；详情另显示人员组织编码。人员库未提供部门名称，组织编码不等同于摄像头事业部。

大屏通过 `/api/external/security-fence` 读取摄像头、画面、实时状态及报警历史，无需 API Key 或账号登录，按事业部及平台当前功能分配查询。接入方式见[围栏外部 API 文档](docs/security-fence-external-api.md)。摄像头安装后应验证入口正脸像素、光照、多人遮挡及跟踪效果；该功能不保证未露出可识别人脸的人员一定触发身份报警。

### 非法闯闸

`tailgating` 使用共享人体模型跟踪完整画面，只有两个不同人员同向跨越过闸判定线的有效线段，并在同一 ROI 内连续共同出现达到确认时间，才触发尾随报警。默认共同出现确认时间为 0.3 秒；共同出现结束后的关联窗口默认 3 秒，用于等待双方完成过线。同组人员的一次通行只记录一次，三人及以上同行合并为同组事件，独立事件分别报警，元数据保存轨迹编号、方向和共同出现时间。

区域入侵警戒线和过闸判定线使用统一的青色抗锯齿描边，方向以独立短双箭头表示。闯闸的浅色标记表示通行方向，区域入侵的琥珀色标记指向报警侧。配置页沿用公共 ROI 编辑器，使用小方形控制点和轻透明区域填色。

配置按摄像头保存在 `ai_camera_config_tailgating`，默认停用，由管理员在“功能分配”中开放给目标事业部。摄像头加入功能后需保存 ROI、过闸判定线和监测方向；参数与启停经现有事务、缓存和事件总线热更新。画面使用最新采集帧，状态查询不等待推理锁；采样间隔超过配置上限、推理失败、分辨率变化或配置变更时清除旧通行状态。状态接口返回剩余有效时间，监控页使用浏览器单调时钟计时，短暂请求失败保留尚未过期的数据，结果超过 2 秒失效。实际部署需用闸机录像验证方向、贴身遮挡与检测采样频率。

外部大屏通过 `/api/external/tailgating` 只读查询事业部、摄像头、画面、实时状态、报警和抓拍图，无需 API Key 或账号登录。报警也可从 `ai_violation_image` 按 `feature_name='tailgating'`、`violation_type=17` 和事业部查询；图片地址可直接用于缩略图和原图链接。数据库 SQL、字段和 HTTP 示例见[非法闯闸对接文档](docs/tailgating-external-api.md)。

### 物流通道

一个通道最多绑定九路摄像头，每路独立配置 ROI，通道保存检测时段、人数阈值、持续时间和通知策略。联合规则按顺序判断：任一路多人 → 多人异常；否则至少一路单人 → 正常；否则存在未知 → 未知；全部有效且无人 → 无人异常。

通道的“时段与参数”使用一套检测与报警时段，按星期、每日起止时间和时区同时控制检测及通知，默认每天 `08:00～20:00`。时段外停止检测和报警，实时画面仍可查看；未选择星期时不检测、不报警。接口通过 `config.schedule` 读写时段，时间段须在同一天内，周一到周日编码为 `0～6`。“报警推送”维护报警间隔、记录、企微和喇叭渠道。

各路人数不相加，例如 `[1, 1]` 为正常、`[0, unknown]` 为未知。持续异常达到阈值后以通道为主体分发告警，监控与证据使用通道拼接画面。

### 保安行为

`GuardBehaviorConsumer` 复用平台采集，执行人体/手机检测、ByteTrack、制服分类及可选的姿态/车辆推理，发布各摄像头感知快照。保安室运行时汇总成员状态，处理离岗、玩手机、趴睡和车辆出厂检查异常。

配置分为保安室、成员、规则参数、车辆 ROI 与各类告警策略。必需模型是 `yolo_guard_person_phone`、`guard_uniform`，姿态和车辆模型属于可选依赖，影响对应子规则。当前非保安人员框显示为灰色。

### 安检流程

`InspectionConsumer` 从平台帧缓存取图，调用共享 `yolo_human`，按命名工位 ROI 跟踪双人交互、生成 session 并抽取关键帧。后台 `InspectionRuntime` 按事业部和摄像头轮询调度福达AI请求，检测线程不等待网络判定。

安检每路最多保留一个人体检测请求，按摄像头顺序提前投递并重叠等待。`SECURITY_INSPECTION_INFLIGHT` 默认 `4`，范围 `1～4`；结果使用投递时的原图、采样时间和配置代次，禁用、离线或配置变化会取消相关请求。

交互候选按轨迹 ID 识别，检测结果排序变化不重置同一人员配对；低帧率下按有效采样间隔折算运动量，过期轨迹不用于启动会话。

- 摄像头开关、工位 ROI、检测参数和告警配置通过公共摄像头/功能 API 保存到 MySQL。
- ROI 配置页显示摄像头原始画面；新增工位并绘制、保存区域后，检测生成安检标注画面。
- 全局模型地址及调度参数通过 `/api/security-inspection/settings` 保存；默认地址为 `http://127.0.0.1:18100/v1`，模型名为 `fuda-qwen38-27b`。
- 模型最终返回 `compliant`、`confidence`、`reason`；历史状态区分合规、不合规、错误和取消。
- 只有不合规结果进入业务告警，截图使用该 session 的关键帧拼图。会话录像从交互开始采集、结束时封存，判定后按报警通道和冷却设置保存，可在报警详情播放；告警冷却按摄像头和工位隔离。
- 安检历史和统计采用滚动最近 31 天。每条不合规 session 与 JPEG 证据在同一数据库事务中保存，图片不受通知开关或报警冷却影响；历史列表支持查看证据。
- 安检总数包含合规、不合规和判定失败；修改 ROI 等操作产生的取消会话单独统计并保留历史，不计入安检总数。合规率只基于合规与不合规判定。
- 运行时提供模型健康检查、连续失败熔断和自动恢复状态。

外部安防大屏使用 `/api/external/security-inspection` 查询摄像头、画面、状态和会话历史，并读写摄像头安检配置；警戒围栏和非法闯闸分别使用 `/api/external/security-fence`、`/api/external/tailgating` 只读查询。三组接口均无需 API Key 或账号登录，按 `department` 和平台当前功能分配查询，并校验资源归属。图片地址可直接显示原图和缩略图，安检配置复用平台数据及热更新。接入方式见[安检文档](docs/security-inspection-external-api.md)、[围栏文档](docs/security-fence-external-api.md)和[非法闯闸文档](docs/tailgating-external-api.md)。

## 4. 认证、权限与数据

[auth/api.py](auth/api.py) 提供登录、登出、当前用户、修改密码、用户管理和访问审计接口，由 AiVision 的 `create_app()` 注册。浏览器通过 Cookie 维持登录，前端请求携带 `credentials: 'include'`；接口返回 `401` 时清空前端登录状态。

`/api/external/` 下的数据、图片和安检配置接口允许直接访问，无需请求头凭证，也不依赖人员登录 Cookie。平台账号接口、管理接口和全局模型设置仍校验人员登录及对应权限。

| 数据 | MySQL 表 / 存储 |
| --- | --- |
| 用户账号 | `auth_users` |
| 外部系统凭证摘要与授权 | `auth_external_clients` |
| 最近访问记录 | `auth_access_viewers` |
| 事业部功能分配 | `department_feature_access` |
| 摄像头及功能配置 | `ai_camera_config` 及各功能配置表 |
| 统一告警事件 | `ai_violation_image` |
| 报警处置与历史 | `ai_alarm_disposition` |
| 安检 session | `ai_security_inspection_session` |
| 安检不合规图片 | `ai_security_inspection_session_image`，按 `session_id` 关联的 JPEG 二进制 |
| 指令驱动智慧安防配置与事件 | `ai_camera_config_visual_language_detection`、`ai_visual_language_event` |
| 围栏时段、ROI 与报警策略 | `ai_camera_config_security_fence` |
| 围栏事业部通行白名单 | `ai_security_fence_person_authorization` |
| 闸机 ROI、过闸判定线与共同出现规则 | `ai_camera_config_tailgating` |
| 人脸底库 | `ai_face_person`、`ai_face_embedding` |
| 人脸识别事业部通行白名单 | `ai_face_person_authorization` |
| 证据文件 | 本机 `DATA_PATH`，数据库保存引用 |

摄像头 `shm_name` 由后端按数据库主键生成，统一使用 `camera_<摄像头ID>`，例如 `camera_105`。总览及检测功能页面新建摄像头时无需自行生成该标识；画面、检测请求和报警筛选使用接口返回的完整值。

报警媒体、识别截图和安检 session 默认保留 31 天，启动后及每 60 分钟清理过期数据。安检数据库图片随 session 删除。磁盘媒体的 `ALARM_MEDIA_MAX_GB=10` 是容量告警阈值，超限不会提前删除保留期内证据；数据库 BLOB 不计入磁盘媒体阈值。磁盘报警目录由正式报警类型注册表统一确定。

`admin` 管理配置、账号及事业部功能分配；所有角色均按事业部与功能的配对授权进入检测页面和读取检测数据。分配保存采用事务和版本校验，冲突返回 409；后端请求读取最新权限，已登录页面每 30 秒同步一次，重新进入可见标签页时立即同步。报警记录和统计保留事业部数据权限，不因取消功能分配而隐藏已有历史。访问记录页面还要求后端返回 `capabilities.view_access_audit=true`。报警处置接口按报警访问权限授权，并非所有写操作都限定管理员。

运维脚本复用 `scripts/auth_secret` 并向 AiVision 注入 `AUTH_SECRET`。手动启动也需要配置至少 32 字符的密钥；不要在文档或 Git 中写入真实密钥、数据库密码或带认证信息的视频地址。

## 5. 告警、统计与 API

全部检测告警进入同一数据库和接口，前端不再汇总三个独立后端的数据。告警 ID 使用数据库主键字符串，列表在数据库中按权限、事业部、事件类型和时间过滤后分页；统计接口按查询范围聚合。

处置状态包括 `pending`、`acknowledged`、`resolved`、`false_positive`，记录备注、处理人和最近 20 次历史。处置列表默认每页 50 条，最多 100 条，通过 `next_cursor` 继续读取。

| 接口入口 | 用途 |
| --- | --- |
| `/api/auth/*`、`/api/admin/*` | 认证、账号、访问审计 |
| `/api/overview` | 平台、事业部、摄像头与能力总览 |
| `/api/assistant/*` | 账号私有对话、异步指令、停止任务和模型设置 |
| `/api/runtime/health`、`/api/runtime/status` | 公开健康检查 / 受权限控制的运行状态 |
| `/api/cameras`、`/api/features` | 摄像头、功能配置和画面 |
| `/api/models` | 模型配置与运行/重载状态 |
| `/api/alarms`、`/api/alarms/statistics/summary` | 告警及统计 |
| `/api/alarm-dispositions` | 报警处置 |
| `/api/logistics-channels/*` | 通道与成员管理、状态及拼图 |
| `/api/guard-behavior/sites/*` | 保安室、策略、成员及运行状态 |
| `/api/security-fence/*`、`/api/external/security-fence/*` | 围栏平台状态与人员选择 / 无需 API Key 或登录的大屏只读接口 |
| `/api/tailgating/cameras/{key}/status` | 非法闯闸实时状态、轨迹与通行事件 |
| `/api/external/tailgating/*` | 无需 API Key 或登录的非法闯闸画面、状态、报警和图片只读接口 |
| `/api/security-inspection/*` | 安检历史、运行状态与福达AI设置 |
| `/api/external/security-inspection/*` | 无需 API Key 或登录的安检展示、图片和摄像头配置接口 |
| `/api/visual-language-detection/cameras/{key}/*` | 视觉理解结果、事件与视频提问 |
| `/api/face-recognition/records` | 身份识别记录 |
| `/api/horns`、`/api/exception-alert` | 喇叭与系统异常通知 |

接口字段以路由源码和运行实例的 `/docs`、`/openapi.json` 为准。

现场喇叭支持海康网络音柱（如 DS-QA6C301）。“喇叭设备”分为设备管理、音频库和 SIP 服务；各检测功能在“报警推送”中设置喇叭绑定。设备列表及报警绑定选项按当前事业部隔离，未归属的旧设备由管理员在“待分配设备”中整理。后端校验设备归属，禁止跨事业部绑定。管理员为每台设备填写 HTTP/HTTPS 管理地址、设备凭据和 SIP 身份，平台后台自动同步启用设备的 SIP 参数。SIP 通信服务和音频库由全平台共用，默认监听 UDP `5062`，独立于 HTTP API 的 `7862` 端口。

平台重启、注册超时或注册过期时，后台和试播会重新启用尚未注册的设备 SIP 通道，促使其立即注册；已完成注册的设备不反复启停。注册失败提示区分未收到请求、账户不匹配和摘要认证未通过。

“音频库”支持上传 AAC，默认限制为 10 MB、60 秒；服务器通过 FFmpeg 校验并转换音频，素材保存在 `DATA_PATH/horn_audio`。各设备和检测配置均可选择素材并点击“试播音频”现场确认。在“报警推送”中启用喇叭、选择设备和音频并保存后，异常告警由服务器通过 SIP/RTP 播放。选择“设备已有音频（ISAPI）”时，报警绑定填写设备素材库的整数音频 ID。连接测试只读取设备信息，不保存配置或播放声音。

每台 SIP 喇叭可在设备编辑弹窗设置 `0–200%` 音频响度，`100%` 保持原始响度，`0%` 静音。试播和实际报警使用同一设备设置，服务器在发送前调整音频，不改写共享素材。

所有检测功能的喇叭、企业微信和报警记录分别设置间隔。喇叭间隔为 `0` 时不额外等待，同台设备串行播放；人员或人脸逗留达到设定时长后，只要当前有效观测仍成立就继续触发，目标离开后不再续播。企业微信仍按自己的推送间隔执行；事件型检测保持各自的事件触发规则。

删除设备时展示引用它的事业部、功能、摄像头、物流通道和保安室，包括关闭告警后保留的绑定。已停用设备可在确认清单后解除绑定并删除；操作在同一事务内关闭相关喇叭告警、清空设备和音频绑定，保留其他报警渠道及检测配置。确认期间引用或设备状态发生变化时需重新核对。

## 6. 环境准备与启动

准备 Python `>=3.10,<3.12`、Node.js 20 环境、MySQL、FFmpeg/ffprobe，以及本机可用的模型权重。Python 依赖和 GPU 人脸环境说明见 [AiVision 环境准备](AiVision/README.md#11-环境准备与启动)。

首次部署从以下模板准备本机配置，已有文件应保留：

```bash
cd /usr/zyy/Fuda_CVPreject_V3
cp -n AiVision/.env.example AiVision/.env
cp -n AiVision/config/model_paths.example.yaml AiVision/config/model_paths.yaml
cp -n scripts/start.env.example scripts/cold_start.env
cd unified_frontend
npm ci
```

随后填写真实数据库连接、可写 `DATA_PATH` 和模型路径。`cold_start.env` 仅用于覆盖运行环境探测等脚本设置；模板占位值不能直接用于部署。

已有数据库的喇叭结构使用 `python -m AiVision.migrations.horn_sip_audio_20261016 --check` 核对。停止服务并备份数据库后，在项目根目录执行 `python -m AiVision.migrations.horn_sip_audio_20261016 --apply --offline`，准备事业部归属、SIP 配置列和音频表，再启动服务。工具支持为明确指定地址的旧设备分配事业部，参数见 [后端数据迁移说明](AiVision/README.md#103-数据迁移边界)。空库由正常启动流程建表。

独立通知间隔要求各告警配置表包含 `horn_interval` 和 `wechat_interval`。使用 `python -m AiVision.migrations.alarm_channel_intervals_20261021 --check` 只读核对；停止服务并备份数据库后执行同一命令的 `--apply --offline`，完成后再启动服务。未单独设置的通知间隔沿用该配置的报警记录间隔。

围栏事业部白名单使用 `python -m AiVision.migrations.security_fence_authorization_20261022 --check` 只读核对。停止后端及相关写入并备份数据库后，执行同一命令的 `--apply --offline`，按摄像头所属事业部合并已有人员授权，再启动后端。部署命令和生效方式见 [run_guide.txt](run_guide.txt) 第九节。

AiVision 启动命令使用默认参数，监听地址和端口读取 `API_HOST`、`API_PORT`，默认 `0.0.0.0:7862`。前端代理、启动健康检查和状态脚本使用后端端口 `7862`，前端端口为 `3000`；自定义端口时应同步调整代理目标和运维检查配置。

主入口按源码位置加载 `AiVision/.env`，已有进程环境变量优先。Settings 只读取环境变量与字段默认值；启动预检也不再回退到仓库根目录的旧 `.env`。

在项目根目录管理服务：

```bash
bash scripts/start.sh
bash scripts/status.sh
```

停止服务使用 `bash scripts/stop.sh`；`start.sh --force` 会先关闭已有同名会话，再重新启动。普通 `start.sh` 会跳过已有会话。

单独排障时，在已配置 `AUTH_SECRET` 的终端启动后端：

```bash
conda activate aivision
python -m AiVision.main
```

另一个终端启动前端：

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
npm run dev
```

主入口在数据库准备和运行资源启动后才启动 HTTP。不要用单独的 `uvicorn AiVision.api.app:app` 代替正式入口，也不要通过多个 Web Worker 重复启动同一批摄像头资源。

摄像头启动使用有限并行，`AiVision/.env` 中的 `CAMERA_START_WORKERS` 默认 `4`，范围 `1～16`，控制同时探测和等待首帧的路数。启动日志输出模块、数据库、摄像头、模型和总耗时。设备启动失败后由后台看门狗重试；持续的重连日志不表示整个平台仍在初始化，可通过健康接口确认运行状态。

## 7. 验证与故障定位

| 现象 | 优先检查 |
| --- | --- |
| 页面打不开或 API 代理失败 | `scripts/status.sh`、两个 tmux 日志、监听端口与 Vite 代理目标 |
| 登录失败 | `auth_users` 中账号状态、MySQL 连接、`AUTH_SECRET` 和 `auth/auth.py` |
| 页面没有可选事业部 | 用户授权部门、URL 的 `department` 参数及前端权限解析 |
| 摄像头无画面 | 摄像头/功能开关、RTSP、FFmpeg、最新帧时间与模型状态 |
| 配置保存但模型未工作 | `/api/models` 的 `reload`、`runtime` 和后端日志 |
| 保安行为部分规则不可用 | 保安室成员状态、必需/可选模型与对应规则开关 |
| 安检有画面但无判定 | 工位 ROI、session 条件、福达AI健康状态、排队与历史错误 |
| 有违规但无通知 | 持续时间、冷却主体、SQL/企微/喇叭开关、设备绑定及发送日志 |
| 告警视频未生成 | `pending/ready/failed` 状态、前后帧缓存、FFmpeg 和磁盘权限 |

`/api/runtime/health` 的 `ok=true` 表示 Orchestrator 已启动且至少一个模型就绪，不代表所有摄像头、功能或福达AI服务均正常。

前端代码的现有检查入口：

```bash
npm --prefix unified_frontend run lint
npm --prefix unified_frontend run build
```

后端改动按实际影响进行 Python 语法检查、接口验证与现场验证，重点核对权限、配置保存、资源生命周期和业务判定。

福达AI助手可在项目根目录运行 `python -m AiVision.tests.assistant_diagnostics --base-url http://127.0.0.1:18100/v1 --model fuda-qwen38-27b --output /tmp/fuda-ai-diagnostics`，分别检查模型、Agent、业务工具、端到端及持续多轮对话。业务写入仅使用临时 SQLite，输出脱敏报告；真实模型与脚本模型的结果分别统计。模型层含格式一致与格式冲突的 Schema 探针，区分接口接受请求和实际输出合规；多轮评分允许复用已定位目标，仍要求本轮重新读取配置和版本。命令和统计口径见[助手分层诊断](docs/assistant-diagnostics.md)。

纯文档修改可执行：

```bash
git diff --check -- README.md unified_frontend/info.md AiVision/README.md
```

## 8. 开发入口

新增检测功能先参考最接近的 `features/` 模块，拆分 Schema、ORM、Consumer 和 SPEC，再在 `features/registry.py` 显式注册。需要新模型时更新模型注册表和路径模板；涉及告警时同步检查告警类型、主体身份与前端事件映射。

前端开发同时检查 `src/lib/nav.ts`、`src/auth/permissions.ts`、`src/App.tsx` 和对应业务组件，沿用已有事业部切换、请求取消、配置保存及错误处理方式。

修改保安行为规则从 `features/guard_behavior/behavior.py`、`site_rules.py` 和 `runtime.py` 入手；修改安检流程从 `features/security_inspection/sessions.py`、`vlm.py`、`schema.py` 和 `prompts.py` 入手。摄像头采集、模型推理、HTTP 路由保持各自职责。
