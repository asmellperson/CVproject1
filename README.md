# 福达视觉平台项目架构说明

这份文档读完后应能回答三个问题：

1. 这个项目解决什么业务问题。
2. 前端、统一后端和 AiVision 视觉业务层分别负责什么。
3. 如果要运行、排查或新增能力，应该先看哪些文件。

## 1. 项目定位

本仓库是一个统一的 AI 视频监控平台，公网访问入口是：

```text
https://aicv.fudar.com/
```

公网网关将该域名的 HTTPS 请求转发到项目服务器的 Vite `3000` 端口。

平台把多个视觉检测能力整合到一个前端里，主要覆盖三类业务：

| 业务模块 | 子系统 | 做什么 |
| --- | --- | --- |
| 安检流程规范检测 | `AiVision/integrations/security_vlm` | 通过 YOLO + ByteTrack 跟踪安检工位人员交互过程，再把关键帧交给 Qwen-VL 判断流程是否合规。 |
| 保安行为规范检测 | `AiVision/integrations/guard_room` | 多路摄像头实时检测保安离岗、玩手机、趴睡，并保存报警截图/视频、推送企业微信。 |
| 通用视觉检测能力 | `AiVision` | 以 features-first 架构提供区域入侵、大门开关异常、人脸逗留检测、人员逗留、手机使用检测等能力。 |
| 统一管理界面 | `unified_frontend` | React 前端，统一登录、导航、监控预览、ROI/模型/摄像头配置、报警记录与统计。 |

整体上，这是“一个 Vite 前端 + 一个统一后端 + 一个视觉业务后端”的三层项目。Guard Room 和
Security VLM 的源码、API 与生命周期都属于 AiVision，不再是仓库顶层的独立项目或服务。

## 2. 仓库顶层结构

```text
Fuda_CVPreject_V3/
├── unified_frontend/      # React + TypeScript + Vite 统一前端
├── AiVision/              # 统一视觉业务后端（含全部检测能力）
│   └── integrations/
│       ├── guard_room/    # 保安行为算法与 API 模块
│       └── security_vlm/  # 安检 VLM 算法与按需 worker
├── auth/                  # 共享认证逻辑与 SQLite 用户存储
├── docs/diagrams/         # 项目流程图
├── scripts/               # 三服务启停、状态检查与运行时探测
├── run_guide.txt          # 部署、线上/tmux 运维与账号维护说明
└── PROJECT_ARCHITECTURE.md
```

生产环境统一管理三个 tmux 运行服务，前端由 Vite 直接提供：

| 服务 | 默认端口 | 启动目录 | 主要入口 |
| --- | ---: | --- | --- |
| 统一前端 | `3000` | `unified_frontend` | `npm run dev`（由 `scripts/start.sh` 启动） |
| 统一后端 | `5000` | 仓库| `python -m unified_backend.run_server` |
| AiVision 视觉业务层 | `7862` | 仓库 | `conda activate aivision && python -m AiVision.main` |

## 3. 整体调用关系

```text
浏览器
  |
  v
Vite -> unified_frontend (React 页面与 API 代理, :3000)
  |
  v
unified_backend (:5000)
  |
  +-- 保安行为 API        -> AiVision (:7862, 进程内 Guard Room)
  +-- 安检流程 API        -> AiVision (:7862, 进程内 Security VLM)
  +-- /api/*             -> AiVision (:7862, 正式 API)
  +-- /aivision/*        -> AiVision (:7862)
```

开发环境的代理配置在：

```text
unified_frontend/vite.config.ts
```

前端 API 封装主要在：

```text
unified_frontend/src/lib/api.ts
unified_frontend/src/lib/aivision.ts
unified_frontend/src/lib/security-vlm.ts
```

因此排查“页面请求打到哪里”时，先看 `vite.config.ts` 的 proxy，再看 `src/lib/` 下对应封装。

## 4. 认证与权限

当前项目的后端认证实现集中在 `auth/auth.py`。统一后端负责登录入口，AiVision 与 Guard Room
直接导入共享认证模块并校验同一个 JWT/Cookie。

关键点：

| 项 | 说明 |
| --- | --- |
| 登录入口 | 前端 `unified_frontend/src/pages/LoginPage.tsx` |
| 前端登录态 | `unified_frontend/src/auth/` |
| 后端认证实现 | `auth/auth.py` |
| AiVision/Guard Room 认证引用 | `from auth.auth import ...` |
| 用户数据库 | `runtime/auth/auth_users.db`（可由 `AUTH_USERS_DB` 覆盖） |
| 权限分级 | `unified_frontend/src/auth/permissions.ts` |
| 角色 | `admin` 可以配置/启停/录制；`viewer` 只能查看。 |

线上启动时需要让统一后端和 AiVision 使用同一个 `AUTH_SECRET`：

```bash
export AUTH_SECRET="<统一后端和AiVision保持同一串32位以上随机密钥>"
```

新增账号和角色修改参考`run_guide.txt`。

## 5. unified_frontend 前端架构

### 5.1 技术栈

| 类型 | 技术 |
| --- | --- |
| 构建工具 | Vite |
| UI 框架 | React 19 + TypeScript |
| 样式 | Tailwind CSS |
| UI 基础组件 | Radix UI + 本地 `components/ui` |
| 图标 | `lucide-react` |
| 图表 | `recharts` |

### 5.2 目录职责

```text
unified_frontend/
├── src/App.tsx              # 页面框架：Sidebar + Topbar + 当前模块内容
├── src/main.tsx             # React 入口
├── src/pages/               # 独立页面，目前主要是登录页
├── src/sections/            # 各业务模块页面主体
├── src/components/          # 业务组件和通用组件
├── src/components/ui/       # shadcn/Radix 风格基础 UI 组件
├── src/lib/                 # API、导航、工具函数
├── src/auth/                # 登录态与 AuthContext
├── src/types/               # 前端类型定义
└── vite.config.ts           # dev server、代理、路径别名
```

### 5.3 页面导航

导航配置在：

```text
unified_frontend/src/lib/nav.ts
```

`App.tsx` 根据 `currentPage` 渲染对应 section：

| 页面 id | 组件 | 对应后端 |
| --- | --- | --- |
| `overview` | `HomeSection` | 聚合展示 |
| `security-vlm` | `SecurityVlmSection` | `security_vlm` |
| `guard-behavior` | `GuardBehaviorSection` | `guard_room` |
| `intrusion-detection` | `IntrusionDetectionSection` | `AiVision` |
| `door-detection` | `DoorDetectionSection` | `AiVision` |
| `face-detection` | `FaceDetectionSection` | `AiVision` |
| `human-detection` | `HumanDetectionSection` | `AiVision` |
| `phone-detection` | `PhoneDetectionSection` | `AiVision` |
| `alarms` | `AlarmsSection` | 聚合三类视觉业务报警 |
| `statistics` | `StatisticsSection` | 基于报警数据聚合统计 |

如果新增一个前端模块，通常需要改：

1. `src/lib/nav.ts` 增加导航项。
2. `src/App.tsx` 增加 `case` 渲染。
3. `src/sections/` 增加页面组件。
4. `src/lib/` 增加后端 API 封装。

## 6. guard_room 保安行为规范检测

### 6.1 业务职责

`AiVision/integrations/guard_room` 是 AiVision 内置的保安行为模块，用于值班室/保安场景。它的 FastAPI 子应用
挂载在 AiVision 7862 端口下，没有独立 Web 进程或端口。它支持多路 RTSP 摄像头，并检测：

| 异常 | 判定逻辑概览 |
| --- | --- |
| 离岗 | 多路摄像头超过阈值时间都没有识别到保安。 |
| 玩手机 | 手机框与保安框在时间窗口内持续关联。 |
| 趴睡 | 姿态低头比例 + 画面静止程度持续满足阈值。 |

触发报警后会保存快照、录制短视频，并可通过企业微信推送。

### 6.2 核心数据流

```text
RTSP 摄像头
  |
  v
RTSPReader 线程（每路一个）
  |
  v
LatestFrameBuffer 单槽缓冲（始终只保留最新帧）
  |
  v
GuardRoomRuntime._run_loop
  |
  +-- ThreadPoolExecutor 并行处理每路摄像头
        |
        +-- YOLO 人体/手机检测
        +-- ByteTrack 跟踪
        +-- UniformClassifier 制服识别
        +-- TrackGuardGate 识别结果平滑
        +-- PoseEstimator 姿态估计
        +-- BehaviorEngine 规则判定
  |
  v
MultiCameraConsensus 多摄像头共识
  |
  v
AlarmManager + AlarmClipRecorder + WeChatNotifier
  |
  v
AppState
  |
  v
FastAPI API / MJPEG / 报警列表
```

### 6.3 关键文件

```text
AiVision/integrations/guard_room/
├── config/config.example.yaml # 配置模板
├── src/server.py              # FastAPI API、认证中间件、配置/报警/推流接口
├── src/runtime.py             # 核心运行时，串联拉流、推理、报警、状态
├── src/config.py              # YAML 配置 dataclass
├── src/state.py               # API 与 runtime 之间的共享状态
├── src/behavior.py            # 离岗/玩手机/趴睡规则引擎
├── src/consensus.py           # 多摄像头共识裁决
├── src/uniform.py             # 制服分类模型封装
├── src/pose.py                # 姿态估计
├── src/alarms.py              # 报警事件、冷却、快照、持久化
├── src/alarm_clip_recorder.py # 报警视频录制
└── src/wechat_notifier.py     # 企业微信异步推送
```

### 6.4 配置重点

主配置文件运行时应是：

```text
AiVision/integrations/guard_room/config/config.yaml
```

模板在：

```text
AiVision/integrations/guard_room/config/config.example.yaml
```

重点配置节：

| 配置节 | 作用 |
| --- | --- |
| `video` | 摄像头 RTSP、跳帧、输出目录、重连、JPEG 质量。 |
| `models` | 人体/手机 YOLO、制服分类、姿态模型路径与推理参数。 |
| `rules` | 离岗、手机、趴睡的阈值和报警冷却时间。 |
| `wechat` | 企业微信开关、凭据、报警接收人、视频片段时长。 |

排查 Guard Room 时，进入 `aivision` tmux，优先看 `src/runtime.py` 日志和状态 API 返回。

## 7. AiVision 通用视觉检测后端

### 7.1 业务职责

`AiVision` 是通用视觉检测后端。它把每一种检测能力都抽象成一个 feature，当前包含：

| feature name | 页面名称 | 检测能力 | 是否依赖模型 |
| --- | --- | --- | --- |
| `blocks` | 区域入侵检测 | ROI 区域变化/入侵检测 | 否 |
| `detect_door` | 大门开关异常检测 | 门禁状态检测 | 否 |
| `detect_face` | 人脸逗留检测 | 人脸框检测、跟踪与逗留计时 | `insightface_detection` |
| `detect_human` | 人员违规逗留检测（通用电气、皓达公司） | 共用算法和 Schema，按摄像头独立配置与计时 | `yolo_human` |
| `detect_phone` | 手机使用检测 | 手机检测 | `yolo_phone` |
| `detect_logistics_single_person` | 物流通道单人检测（四个事业部） | 多摄像头联合人数判定 | `yolo_human` |
| `recognize_face` | 人脸身份识别（电子电工） | 人员特征比对及识别记录 | `insightface` |

人员逗留统一使用 `HumanConsumer`、`HumanConfigSchema` 和 `ai_camera_config_detect_human`。
摄像头必须明确归属 `general_electric` 或 `haoda_company`，页面入口分别限定事业部；后端按摄像头归属及报警归属快照校验权限。
已有皓达配置必须先执行[人员逗留离线迁移与恢复说明](AiVision/migrations/human_20260915.md)，服务启动不会自动转换数据。
人员报警证据按事业部授权；微信卡片使用默认有效 24 小时的单条报警签名缩略图，详情和视频仍需登录。

#### 手机使用检测全链路

下图展示了手机使用检测从 React 前端、统一后端、AiVision 配置系统，到实时视觉推理、空间关联、跟踪、时间判断与告警展示的完整链路：

![手机使用检测全链路流程图](./docs/diagrams/手机使用检测全链路流程图.png)

### 7.2 features-first 架构

AiVision 的核心设计是 features-first：

```text
features/{package_name}/
├── __init__.py   # 简单包声明，不注册功能或转发 SPEC
├── spec.py       # 唯一 SPEC = FeatureSpec(...)
├── consumer.py   # 该功能的运行时处理逻辑
├── orm.py        # 该功能的数据库配置表
└── schema.py     # 该功能的配置校验模型
```

每个 feature 通过 `FeatureSpec` 声明自己：

```text
name            # URL 和数据库 function_name 使用的机器名
display_name    # 前端/接口展示名称
consumer_cls    # 运行时消费者类
orm_class       # 配置表 ORM
config_schema   # 配置 Pydantic schema
required_models # 依赖哪些推理模型
violation_type  # 违规类型枚举
```

`AiVision/features/registry.py` 是唯一功能注册入口，显式导入七个 `spec.py`，不扫描目录或吞掉导入异常。注册时拒绝重复 `FeatureSpec.name` 并继续核验事业部；查询统一使用 `from AiVision.features.registry import all_specs, get_spec, list_orm_classes`。`features/__init__.py` 和各功能 `__init__.py` 只有包说明，不转发这些查询函数、SPEC 或 Consumer。

包目录名与业务标识严格分离，注册表保持原有遍历顺序：

| Python 包目录 | `FeatureSpec.name`（数据库、API、前端继续使用） |
|---|---|
| `intrusion/` | `blocks` |
| `door_state/` | `detect_door` |
| `face_dwell/` | `detect_face` |
| `person_dwell/` | `detect_human` |
| `logistics_channel/` | `detect_logistics_single_person` |
| `phone_detection/` | `detect_phone` |
| `face_recognition/` | `recognize_face` |

共享配置基类、Consumer、跟踪与逗留计时位于 `_shared/`。`person_dwell/spec.py` 仍只有一个人员逗留 SPEC，同时支持 `general_electric` 和 `haoda_company`。目录迁移没有改变 ORM 表结构、配置字段、算法、报警条件或推理失败时的跟踪状态保留与暂停计时语义。本批只做静态检查，未运行测试，也未执行业务导入、启动服务、连接数据库、加载模型或迁移数据。

人脸库统一归属 `features/face_recognition/library/`，配置、Consumer 和识别记录实现保留原位置：

```text
AiVision/features/face_recognition/
├── __init__.py                         # 简单包声明
├── spec.py                             # 唯一人脸识别 SPEC，业务标识 recognize_face
├── consumer.py
├── orm.py
├── schema.py
├── records.py
└── library/
    ├── __init__.py                     # 海康来源标识与同步异常，不启动业务
    ├── constants.py                    # 模型及索引常量，复用推理模块的检测模型常量
    ├── orm.py                          # FacePerson、FaceEmbedding
    ├── service.py                      # 人员查询、整来源快照写入及特征保存
    ├── index.py                        # 特征字节格式、内存索引及比对
    ├── sync.py                         # one、two 人员完整同步入口
    ├── embedding.py                    # 注册照片下载及增量特征生成入口
    ├── hikvision-face-library-sync.service
    └── hikvision-face-library-sync.timer
```

模型加载、检测和特征提取仍在 `inference/`，海康协议及客户端仍在 `connectors/hikvision/`。本轮没有移动或复制这些实现，也没有改变人员唯一性、单脸注册要求、模型维度、归一化、索引刷新、相似度阈值、识别冷却或权限。旧人员库目录已删除，无旧路径兼容层；剩余运行与应用装配模块现已归入 `runtime/` 和 `api/`。

CLI 导入时经过的 `features` 和 `face_recognition` 父包均只有说明，人员库入口不会隐式加载 registry 或全部 Consumer。只有正式导入 `features.registry` 才加载固定的七项功能；功能导入异常直接传播。SPEC 与公开类使用其正式定义模块，不再依赖包级延迟导出。纯人脸检测仍不导入身份识别和人员库。

同步与特征生成命令（用于部署后显式执行，本轮未执行真实任务）：

```bash
python -m AiVision.features.face_recognition.library.sync
python -m AiVision.features.face_recognition.library.embedding
```

两个入口继续使用 `Path(__file__).resolve().parents[3]` 定位源码所在项目的 `AiVision/.env`；本批目录改名没有改变深度，不依赖工作目录，系统环境变量仍优先（`override=False`）。没有复制 `.env` 或凭据。模型配置仍使用原 `MODEL_PATHS_CONFIG` 和 `AiVision/config/model_paths.yaml`，权重路径语义、`DATA_PATH`、识别截图及媒体清理位置不变；识别媒体子目录仍使用业务标识 `recognize_face`。表名、字段、外键和索引未变，不需要数据库迁移。

仓库 unit 位于 [同步 service](AiVision/features/face_recognition/library/hikvision-face-library-sync.service) 和 [同步 timer](AiVision/features/face_recognition/library/hikvision-face-library-sync.timer)。service 仅更新 `ExecStart` 的 Python 模块名；timer 仍关联 `hikvision-face-library-sync.service`，保留开机 2 分钟、每次启动间隔 10 分钟、1 秒精度，以及 service 的 8 分钟启动超时、30 秒停止超时和 `root` 用户。

部署前需核实 unit 中的 `WorkingDirectory=/srv/Fuda_CVPreject`、相应项目下的 `AiVision/.env`，以及 `/root/miniconda3/envs/aivision/bin/python`。本轮只读检查发现 `/srv/Fuda_CVPreject` 不存在，指定 Python 文件存在；当前源码实际位于 `/usr/zyy/Fuda_CVPreject_V3`，不能直接把仓库模板当作当前部署配置。标准系统 unit 目录未发现同名 service/timer。本轮未改写这些部署路径、安装或启动 unit，也未执行 daemon-reload；unit 指定 Python 环境的运行依赖未验证。

以下为前一轮人脸库迁移的验证记录与后续可复跑命令，结果不代表本批已执行测试。本批仅更新测试引用及注册契约，没有执行下列命令。复跑时需使用下方 29 文件回归同样的隔离环境变量：

```bash
python -m pytest -q -ra \
  AiVision/tests/test_{face_library,face_identity,face_detection,model_registry,model_api}.py \
  AiVision/tests/test_{inference_outcomes,inference_runtime_manager_watchdog,violation_media_cleanup}.py \
  AiVision/tests/test_{alarm_identity,alarm_api,alarm_access_batch,human_departments}.py
python -m pytest -q -ra AiVision/tests/test_face_library_package.py
python -m pytest -q -ra AiVision/tests/test_department_registry.py AiVision/tests/test_hikvision_connector.py
python -m pytest -q -ra \
  AiVision/tests/test_{camera_package,inference_package,alarm_package,alarm_device_package,alarm_records_package,alarm_record_evidence,department_package}.py
```

12 文件专项在迁移前后均为 **280 项通过、0 失败、3 项因当前测试环境缺少 InsightFace 而跳过**；新增 **28 项通过**，覆盖各入口独立导入、七项功能完整注册、单一 ORM/类/索引身份、首次并发查询、四种 CLI 与工作目录组合及 unit 契约。CLI 定位测试拦截原 `.env` 路径并读取临时配置，以 `SQL_ENABLE=false` 验证真实模块入口在配置加载后安全退出，不访问实际凭据或执行同步/生成。

补充的事业部注册与海康协议测试 **42 项通过**，既有七文件包迁移验证 **68 项通过**；下方原 29 文件回归仍为 **767 项通过、0 失败、10 项缺少隔离 MySQL 而跳过**，用例及跳过原因与上一轮一致。测试使用 `/root/miniconda3/bin/python`、临时 SQLite 和媒体、模拟海康与模型，并额外拦截 TCP 外连。没有使用源码副本，原有工作区修改保留；真实 MySQL、海康同步、GPU/InsightFace 推理、现场媒体及 unit 部署未验证。

### 7.3 核心数据流

```text
main.py
  |
  v
init_orchestrator()
  |
  v
Orchestrator.start()
  |
  +-- ensure_schema_ready()
  +-- camera_config_manager 加载摄像头与功能配置
  +-- CameraRuntimeManager 启动摄像头进程
  +-- frame_reader_registry 读取最新帧
  +-- violation_writer 启动违规图片写入
  +-- alarm_dispatcher 配置喇叭/微信/图片写入
  +-- inference_runtime_manager 启动模型推理 worker
  +-- 为每个 FeatureSpec 启动 BaseFunctionConsumer 子类
  |
  v
FastAPI 正式 API
```

### 7.4 关键文件

```text
AiVision/
├── main.py                      # 后端入口，设置 multiprocessing spawn，启动 Uvicorn
├── pyproject.toml               # AiVision Conda 环境内安装的 Python 依赖
├── .env.example                 # 环境变量模板
├── api/                         # FastAPI 应用装配、依赖注入与 HTTP 路由
│   ├── app.py                  # FastAPI app、中间件、路由注册及 ASGI mount
│   ├── deps.py                 # 共享依赖注入
│   ├── mounted_apps.py         # 视觉子应用挂载槽、创建及生命周期适配
│   └── routes/                 # alarms/cameras/departments/exception_alerts/face_recognition/
│                               # features/horns/logistics_channels/models/runtime
├── core/settings.py             # 统一环境变量配置入口
├── core/db.py                   # 数据库连接与 schema 初始化
├── core/cache.py                # 配置缓存
├── core/events.py               # 配置变更事件总线
├── runtime/                     # 运行编排与生命周期协调
│   ├── orchestrator.py         # 总编排器及全局实例
│   └── process_cleanup.py      # 启动前残留进程清理
├── cameras/                     # 摄像头进程、帧读取、摄像头配置服务
├── inference/                   # 模型 worker、队列、推理管理
├── departments/                 # 固定事业部定义、只读查询及相关业务约束
├── alarms/                      # 告警相关能力的归属目录
│   ├── dispatcher.py           # 告警分发、冷却及通道协调
│   ├── devices/                # 设备配置、绑定、运行管理及通信
│   ├── notifications/          # 企业微信发送与通知缩略图签名
│   ├── records/                # 数据库记录、截图、写入队列及关联媒体清理
│   ├── evidence/               # 视频帧缓存、录制、编码及完成状态
│   ├── types.py                # 告警类型及展示信息
│   └── validation.py           # 类型、功能与事业部一致性校验
└── features/                    # 所有检测功能模块
```

正式导入使用 `AiVision.runtime.orchestrator`、`AiVision.runtime.process_cleanup`、
`AiVision.api.mounted_apps` 和 `AiVision.api.routes.*`。原平台目录已删除，没有兼容转发。
启动入口仍为 `python -m AiVision.main`；Orchestrator 的实例、启停顺序和运行流程，
视觉子应用生命周期与 ASGI mount，以及 HTTP URL、router prefix 和认证规则均保持不变。
本轮只迁移文件、更新引用和说明，未运行测试、启动服务、连接数据库或加载模型。

事业部模块统一从 `AiVision.departments` 导入，原目录的三个源码文件完整迁移，公开对象和接口保持不变：

```text
AiVision/departments/
├── __init__.py                  # 职责说明及原有三个注册表对象导出
├── department_registry.py       # DepartmentSpec、固定注册表及 require_department
└── service.py                   # DepartmentService、department_service，只读查询
```

[事业部包说明](AiVision/departments/__init__.py) 明确区分固定定义与功能归属：六个事业部的标识、名称和顺序仍由唯一的 `DEPARTMENT_SPECS` 定义，功能支持范围仍由各自的 `FeatureSpec.departments` 声明。包入口保留 `DEPARTMENT_SPECS`、`DepartmentSpec`、`require_department` 的既有公开导出，不增加查询服务或 Feature 的集中导入，也不创建数据库连接、发送请求或启动任务。

事业部 API、延迟依赖注入、摄像头配置、Feature 注册、告警身份校验、认证用户存储、现有人员逗留离线脚本和测试引用均已更新。`get_department_service()` 仍在调用时导入服务；告警身份校验仍在执行校验时导入 Feature 注册表。查询服务与各调用方共享同一份事业部定义，没有复制注册表。人员逗留继续支持通用电气和皓达，物流成员约束、登录用户的事业部授权、管理权限及告警证据访问规则保持原状。

本模块没有依赖 `__file__`、目录深度或包资源的路径计算，无需调整资源位置，不涉及配置或数据库迁移。旧事业部目录及生成的字节码已清理，剩余运行与应用装配模块现已归入 `runtime/` 和 `api/`；没有兼容转发、旧路径别名或双路径支持。`guard_room` 和 `security_vlm` 文件本轮未改动，工作区原有修改已保留。

事业部迁移的专项与独立导入验证命令如下，在下方 29 文件回归相同的隔离环境变量下执行：

```bash
python -m pytest -q -ra \
  AiVision/tests/test_{department_registry,department_api,feature_department_enable,human_departments}.py \
  AiVision/tests/test_{logistics_channel_departments,logistics_channel_service,alarm_api,alarm_access_batch,alarm_identity}.py \
  unified_backend/tests/test_{user_store,admin_users_api,human_alarm_permissions,logistics_channel_alarms}.py
python -m pytest -q -ra AiVision/tests/test_department_package.py
python -m pytest -q -ra \
  AiVision/tests/test_{camera_package,inference_package,alarm_package,alarm_device_package,alarm_records_package,alarm_record_evidence}.py
```

迁移前后同组 13 文件专项均为 **305 项通过、0 失败、0 跳过**。新增 **14 项独立导入测试通过**，从事业部、认证、Feature、摄像头、告警、API 和调度器入口检查共享定义、延迟导入、功能归属及无外部调用。六个事业部的完整定义与顺序、七个功能的归属、用户角色与可选事业部、查询服务结果、相关 OpenAPI 和 16 张已注册表的结构快照在迁移前后相同。源码 AST 排除导入路径与说明后不变，注册表文件逐字不变。

事业部迁移后，既有六文件包迁移验证为 **54 项通过、0 失败、0 跳过**，包括摄像头与推理的隔离 spawn，以及告警记录与录像状态回写；下方原有 29 文件回归为 **767 项通过、0 失败、10 项跳过**。回归用例及跳过原因与上一轮一致：检测配置 4 项、人员逗留迁移 1 项、物流迁移 5 项均缺少隔离 MySQL，没有新增 skip/xfail。

这些测试直接验证最终工作目录，保留原有工作区修改，没有使用隔离源码副本。仅使用临时 SQLite、临时媒体和模拟外部服务；实际执行时复用 `/tmp/alarm_records_test_guard.py` 的 pytest 网络拦截，禁止 TCP 外连，保留隔离多进程所需的本机 Unix socket。真实 MySQL、现场摄像头/设备、GPU 模型推理、企业微信发送及生产权限数据未验证；本次不操作生产数据或重启服务。

摄像头模块统一从 `AiVision.cameras` 导入，文件职责见 [cameras 包说明](AiVision/cameras/__init__.py)。目录包含 `config_manager.py`、`orm.py`、`probe.py`、`runtime.py`、`runtime_manager.py`、`frame_reader.py` 和 `__init__.py`；类名、方法、数据库表和摄像头 API 保持不变，没有旧包转发或双路径支持。

摄像头包不按自身目录计算配置、模型或运行数据路径；这些位置仍由原有 `AiVision.core.settings`、模型配置及环境变量决定。目录调整不需要数据迁移，也不改变启动命令。可运行 `python -m pytest AiVision/tests/test_camera_package.py -q` 检查独立导入和 spawn：测试在临时目录使用模拟 ffprobe/ffmpeg，实际启动新包的摄像头采集入口，验证共享内存帧发布、读取及退出清理，不连接真实摄像头。

推理模块统一从 `AiVision.inference` 导入，内部结构及 Worker 接口保持不变：

```text
AiVision/inference/
├── __init__.py
├── base_worker.py
├── contracts.py
├── insightface_detector.py
├── model_paths.py
├── model_registry.py
├── runtime_manager.py
└── workers/
    ├── __init__.py
    ├── face_detector.py
    ├── face_recognizer.py
    └── yolo_detector.py
```

`model_paths.py` 的 `_PROJECT_ROOT` 按新目录深度取 `Path(__file__).resolve().parents[1]`，仍指向原来的 `AiVision/`。因此默认配置仍为 `AiVision/config/model_paths.yaml`；自定义相对 `MODEL_PATHS_CONFIG`、绝对配置路径和 YAML 中的模型权重路径语义不变。没有旧推理包转发、导入别名或双路径支持，剩余运行与应用装配模块现已归入 `runtime/` 和 `api/`。

新增验证可执行 `python -m pytest -q AiVision/tests/test_inference_package.py`：六种独立导入顺序验证模型和功能注册，两项从其他工作目录读写临时 YAML 的测试验证相对及绝对配置路径，一项通过真实 `YoloDetectorWorker.start()` 和 `BaseModelWorker._run()` 完成 spawn、共享模型队列、结果路由、错误返回与退出清理。该进程测试只替换外部 `ultralytics` 为模型替身，不是 GPU 或真实模型精度验证。

本次推理目录迁移验证：新包 9 项通过；现有推理、模型 API 和人脸检测五个文件在迁移前后均为 109 项通过、3 项因未安装 InsightFace 而跳过；额外的 consumer 帧处理测试 11 项通过。下方原有 29 文件回归在迁移后仍为 **767 项通过、0 失败、10 项因缺少隔离 MySQL 而跳过**，测试范围没有删减。未验证真实 GPU/模型推理、生产模型重载和真实视频。

推理相关测试命令如下；在下方回归命令的隔离环境变量下执行：

```bash
python -m pytest -q -ra AiVision/tests/test_inference_package.py
python -m pytest -q -ra AiVision/tests/test_model_registry.py AiVision/tests/test_model_api.py \
  AiVision/tests/test_inference_outcomes.py AiVision/tests/test_inference_runtime_manager_watchdog.py \
  AiVision/tests/test_face_detection.py
python -m pytest -q -ra AiVision/tests/test_consumer_frame_change.py
```

告警能力统一归属 `AiVision.alarms`，调用方从实现子模块显式导入。类名、函数名、数据结构及调用接口保持不变：

```text
AiVision/alarms/
├── __init__.py                  # 仅说明告警领域职责，不集中导入实现
├── dispatcher.py               # AlarmRequest、分发器与进程内单例
├── types.py                    # 告警类型及展示信息
├── validation.py               # 类型、功能和事业部一致性校验
├── devices/
│   ├── __init__.py              # 设备模块职责与调用链说明
│   ├── binding.py               # 检测配置与物流通道的设备绑定校验
│   ├── horn.py                  # 单设备登录、心跳、重连、播放及停止门控
│   ├── orm.py                   # AiHornConfig，仍映射 ai_horn_config
│   ├── runtime_manager.py       # 设备生命周期、热同步与播放队列
│   ├── schema.py                # 请求校验与公开响应结构
│   └── service.py               # 配置 CRUD 与事务提交后的运行同步
├── notifications/
│   ├── __init__.py              # 仅含简短职责说明
│   ├── notification_image.py    # 人员报警通知缩略图签名及尺寸限制
│   └── wechat.py                # 企业微信 token 缓存、图文卡片及系统文本通知
├── records/
│   ├── __init__.py              # 仅含简短职责说明
│   ├── orm.py                  # AiAlarmEvent，仍映射 ai_violation_image
│   ├── service.py              # 截图保存、同步写入、异步写入队列及失败批次
│   └── cleanup.py              # 关联记录及媒体清理，复用 core/media_cleanup.py
└── evidence/
    ├── __init__.py              # 仅含简短职责说明
    └── evidence_recorder.py     # 帧缓存、录像任务及状态回调，复用 core/video_encoding.py
```

`alarms/`、`devices/`、`notifications/`、`records/` 和 `evidence/` 的包入口仅含说明，不集中导入实现，也不连接数据库、访问设备、发送通知或启动任务。旧包中有效的分发和调用链说明已整合到 [告警领域说明](AiVision/alarms/__init__.py)，设备协议说明归入 [devices 包说明](AiVision/alarms/devices/__init__.py)，微信协议说明归入 [wechat.py](AiVision/alarms/notifications/wechat.py) 的模块文档。

此前已将原告警通道包的四个实现按职责移动：`dispatcher.py` 位于告警领域根目录，`horn.py` 位于 `devices/`，`wechat.py` 和 `notification_image.py` 位于 `notifications/`。原告警通道包已删除，`core/` 保留其他公共能力；告警记录、截图及视频证据现归入下述 `records/` 和 `evidence/`。所有调用均使用新模块路径，没有旧包转发、包级实现导出或双路径支持。

本轮记录与证据迁移将原 `AiVision/platform/violation/` 中六个文件按下表归属，保留文件名、公开对象和内部保存流程：

| 原包内文件 | 新位置 |
| --- | --- |
| `orm.py` | `AiVision/alarms/records/orm.py` |
| `service.py` | `AiVision/alarms/records/service.py` |
| `cleanup.py` | `AiVision/alarms/records/cleanup.py` |
| `types.py` | `AiVision/alarms/types.py` |
| `validation.py` | `AiVision/alarms/validation.py` |
| `evidence_recorder.py` | `AiVision/alarms/evidence/evidence_recorder.py` |

分发器、记录 ORM 和写入器引用同一个 `alarms.validation`；记录包内部的校验相对导入改为 `..validation`，校验函数仍在调用时才导入 Feature 注册表。调度器继续使用同一个 `violation_writer` 和 `alarm_evidence_recorder`，启动顺序、视频状态回写及退出流程不变。告警与物流 API、批量权限查询、数据库初始化、现有离线脚本和测试中的引用均已更新，离线脚本本轮未执行。旧记录目录已删除，剩余运行与应用装配模块现已归入 `runtime/` 和 `api/`。`.gitignore` 仅为记录包的四个 Python 源文件开放例外，其余 `records/` 数据目录仍被忽略。

六个迁移文件没有依赖 `__file__` 或目录深度的资源定位计算，无需修改路径。截图仍保存到 `DATA_PATH/<告警类型>/`，视频仍位于 `DATA_PATH/alarm_clips/`，失败批次仍位于 `DATA_PATH/alarm_failed_batches/`；相对路径仍以进程工作目录为基准。通用媒体清理和视频编码工具保持原位置。写入器实现导入时会沿用原行为创建 `DATA_PATH` 目录，但不会因此连接数据库、读写媒体、清理文件或启动后台任务；新包初始化文件仅含职责说明。表名、字段、索引、外键、API、权限、缩略图签名和录制参数均未改变，本次目录迁移不需要数据迁移。

本轮另修复 `alarms/devices/service.py` 首行文档字符串前的意外空格：只删除该空格，文件其余内容不变。保留开始时已有的七个 `guard_room` 源文件修改；该模块及 `security_vlm` 本轮仅有旧路径注释更新。

本轮所有测试直接使用最终工作目录源码，没有使用排除工作区修改的源码副本。现有记录、身份、权限、写入、录像和清理专项 11 文件在迁移前后均为 **189 项通过、0 失败、0 跳过**；新增独立导入、单一 ORM 注册、共享实例、相对路径和真实临时 SQLite 状态回写测试共 **18 项通过**。四个既有包的迁移验证为 **36 项通过**，包含隔离 spawn；下方原有 29 文件回归为 **767 项通过、0 失败、10 项跳过**，用例与跳过集合未改变。10 项均缺少隔离 MySQL：检测配置 4 项、人员逗留迁移 1 项、物流迁移 5 项，没有新增 skip/xfail。

验证命令如下，在下方回归命令相同的隔离环境变量下执行（仅使用临时数据库、临时媒体和模拟设备/通知）：

```bash
python -m pytest -q -ra \
  AiVision/tests/test_{violation_writer,alarm_evidence_recorder,violation_media_cleanup}.py \
  AiVision/tests/test_{alarm_identity,alarm_api,alarm_access_batch,human_departments}.py \
  AiVision/tests/test_{face_identity,alarm_config_hot_update,logistics_channel_api,wechat_news_card}.py
python -m pytest -q -ra AiVision/tests/test_alarm_records_package.py AiVision/tests/test_alarm_record_evidence.py
python -m pytest -q -ra AiVision/tests/test_{alarm_package,alarm_device_package,camera_package,inference_package}.py
```

本轮实际执行时额外加载 `/tmp/alarm_records_test_guard.py` 的 pytest 网络拦截插件，禁止 TCP 外连，保留隔离多进程测试所需的本机 Unix socket。迁移前后 AST 排除路径引用与说明后一致；16 张已注册表的 DDL（仅归一化 MySQL 表选项输出顺序）、告警与物流 OpenAPI、告警类型、功能集合、资源路径及运行参数快照一致。未验证真实 MySQL、现场摄像头/设备、生产媒体清理或微信端展示；临时帧与模拟通知测试不能替代这些验证。

调度器、普通检测 Consumer、物流通道运行时使用同一个 `dispatcher.alarm_dispatcher`；设备运行管理器使用 `devices.horn.Horn`。系统异常通知与图文卡片使用 `notifications.wechat.WeChatNotifier`，告警 API 从 `notifications.notification_image` 导入缩略图工具。迁移的四个文件没有依赖 `__file__`、目录深度、模板或包资源的定位计算，无需调整资源路径；配置、环境变量及实际数据位置不变。

新包测试从 13 种入口启动独立 Python 进程，检查外部调用与后台任务不会在导入时触发、模块只加载一次、调用方共享同一分发器及设备管理器。系统通知测试用模拟微信发送和线程验证 API 与调度器的 Markdown 内容、收件人和冷却；人员报警权限测试增加详情访问检查，确认缩略图签名不能授权详情或视频，签名密钥不出现在响应或日志中。验证命令如下，使用下方回归命令的隔离环境变量：

```bash
python -m pytest -q -ra AiVision/tests/test_alarm_package.py AiVision/tests/test_alarm_system_notifications.py
python -m pytest -q -ra \
  AiVision/tests/test_{alarm_horn,horn_backend,horn_binding,horn_runtime_manager,alarm_config_hot_update}.py \
  AiVision/tests/test_{wechat_news_card,human_departments,alarm_api,alarm_access_batch,alarm_identity}.py \
  AiVision/tests/test_{alarm_evidence_recorder,violation_writer,system_config}.py
python -m pytest -q -ra AiVision/tests/test_{alarm_device_package,camera_package,inference_package}.py
python -m pytest -q -ra AiVision/tests/test_face_detection.py
```

上一轮告警分发与通知目录迁移的验证针对仅含该轮改动的隔离源码副本执行，未纳入其他未提交工作区修改。原告警专项 13 文件在迁移前后均为 **187 项通过**；加上系统通知和相关人脸回归共 **225 项通过、0 失败、3 项因未安装 InsightFace 跳过**。告警、报警设备、摄像头和推理四个包的迁移验证共 **36 项通过、0 失败、0 跳过**，包含独立导入与隔离 spawn 验证。

该轮下方原有 29 文件回归仍为 **767 项通过、0 失败、10 项因缺少隔离 MySQL 跳过**，用例及跳过集合与此前相同。现有实现的 AST 在排除引用与说明后不变；告警及喇叭 OpenAPI、功能注册集合、固定输入下的缩略图签名和有效期也与迁移前一致。验证额外拦截外部网络连接，未向现场设备或企业微信发送真实消息；真实设备、微信端展示、GPU 推理及 MySQL 实测未验证。

API 及其依赖、Orchestrator、告警分发的类型引用、普通检测和物流通道的绑定校验、ORM 注册入口、现有离线脚本与测试均使用新包。设备模块没有依赖 `__file__`、目录深度或包资源定位的路径计算，因此不需调整资源路径；原配置及运行数据位置保持不变。设备表、字段、绑定关系、`/api/horns` 接口与权限不变，不需要数据库迁移。旧设备目录已删除，没有兼容包、导入别名或双路径支持。

在下方回归命令的隔离环境变量下执行设备专项和包迁移验证：

```bash
python -m pytest -q -ra AiVision/tests/test_alarm_horn.py \
  AiVision/tests/test_horn_backend.py AiVision/tests/test_horn_binding.py \
  AiVision/tests/test_horn_runtime_manager.py AiVision/tests/test_alarm_config_hot_update.py
python -m pytest -q -ra AiVision/tests/test_alarm_device_package.py
python -m pytest -q -ra AiVision/tests/test_camera_package.py AiVision/tests/test_inference_package.py
```

上一轮设备目录迁移的专项五个文件在迁移前后均为 **84 项通过、0 失败、0 跳过**，覆盖无效或停用设备绑定、保存失败回滚、提交后热更新、未授权访问、凭据脱敏和资源释放。设备包的 **9 项独立导入测试通过**，分别从父包、设备子模块、API、功能注册、数据库模块和调度器入口加载，禁止数据库连接、网络请求与后台任务启动，并核验单一 ORM 注册与共享运行实例。该轮摄像头及推理包的 **14 项测试通过**，包含隔离 spawn 验证。

报警设备目录迁移后，下方原有 **29 文件回归仍为 767 项通过、0 失败、10 项跳过**，用例集合与上一轮相同。10 项均为未配置隔离 MySQL 的既有跳过项（检测配置 4 项、人员逗留迁移 1 项、物流迁移 5 项），没有新增 skip/xfail，也未连接生产库验证。

迁移前后的源码 AST 在排除导入路径和说明文字后相同；只读比较的 ORM 元数据、功能注册集合及喇叭 OpenAPI 描述也完全一致。所有测试仅使用临时测试库与模拟设备；未向现场设备发指令，真实设备登录、心跳重连、播放效果和长期运行尚未验证。

目录迁移时的相关回归为 742 项通过、10 项跳过、21 项失败；这些失败均在迁移前源码中复现。后续基线修复按现行业务规则更正了以下测试，未修改生产代码或放宽权限：

- [喇叭绑定测试](AiVision/tests/test_horn_binding.py)：为摄像头和测试管理员明确设置通用电气事业部，使原有 14 项测试进入喇叭绑定逻辑；保留无效绑定、停用设备、事务回滚及热更新事件断言。
- [物流摄像头服务测试](AiVision/tests/test_logistics_channel_service.py)：人员逗留不能推断空归属摄像头的可见事业部；新建并启用时显式选择通用电气或皓达。缺失、空白和不匹配事业部均拒绝，且不写入摄像头、配置或发布事件。其他功能的既有列表规则不变。
- [功能注册测试](AiVision/tests/test_logistics_config_contract.py)：五个独立导入入口均验证明确的七项名称集合：`blocks`、`detect_door`、`detect_face`、`detect_human`、`detect_logistics_single_person`、`detect_phone`、`recognize_face`，并检查 SPEC 唯一性、模块身份与 ORM 表注册。

修复后三个文件共 158 项通过、0 失败；摄像头包的 5 项测试通过。复跑原来同一组 29 个回归文件，结果为 **767 项通过、0 失败、10 项跳过**；较原来的 773 项增加 4 项事业部参数化用例，总计 777 项。10 项跳过均为未配置隔离 MySQL 实例的既有测试：检测配置 4 项、人员逗留迁移 1 项、物流迁移 5 项，未连接生产库。

在项目根目录使用 Bash 复跑相同范围（SQLite 测试使用临时库；下列命令禁用真实 MySQL 测试连接）：

```bash
env -u CONFIG_TEST_MYSQL_URL -u LOGISTICS_TEST_MYSQL_URL -u HUMAN_TEST_MYSQL_URL \
  MYSQL_DB_URL=127.0.0.1 MYSQL_DB_PORT=1 MYSQL_DB_USER=test MYSQL_DB_PASSWORD=test MYSQL_DB_NAME=test \
  AUTO_CREATE_DB=false DATA_PATH=/tmp/camera-test-baseline-data \
  AUTH_USERS_DB=/tmp/camera-test-baseline-auth.sqlite UNIFIED_BACKEND_DATA_DIR=/tmp/camera-test-baseline-backend \
  PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -ra -o faulthandler_timeout=30 \
  AiVision/tests/test_{camera_package,camera_probe,camera_frame_response}.py \
  AiVision/tests/test_{orchestrator_camera_update,orchestrator_camera_frame,feature_department_enable}.py \
  AiVision/tests/test_{alarm_config_hot_update,consumer_roi,detection_config_contract}.py \
  AiVision/tests/test_{detection_config_migration,detection_config_mysql_migration,face_identity}.py \
  AiVision/tests/test_{horn_backend,horn_binding,human_departments}.py \
  AiVision/tests/test_{human_migration,logistics_channel_departments,logistics_channel_service}.py \
  AiVision/tests/test_{logistics_config_contract,logistics_feature_migration,logistics_mysql_migration}.py \
  AiVision/tests/test_{dwell_inference_failure,dwell_monitor_status,logistics_single_person}.py \
  AiVision/tests/test_{logistics_channel_runtime,core_regressions,runtime_api}.py \
  AiVision/tests/test_{department_api,main_runtime}.py
```

真实 RTSP 摄像头、网络断流重连、现场长时间运行及 MySQL 实测未验证；隔离 spawn 测试不能替代实机验证。

### 7.5 API 概览

新接口主要在：

```text
/api/runtime/health
/api/runtime/status
/api/cameras
/api/cameras/{key}/frame.jpg?feature=detect_phone
/api/features
/api/features/{feature}
/api/features/{feature}/configs/{shm_name}
/api/features/{feature}/cameras/{key}/status
/api/models
/api/alarms
/api/alarms/{alarm_id}/image
/api/alarms/{alarm_id}/video
/api/departments
/api/departments/{name}/features
/api/logistics-channels/{feature}
/api/logistics-channels/{feature}/{channel_id}/status
/api/logistics-channels/{feature}/{channel_id}/frame.jpg
```

统一后端处置接口 `/api/alarm-dispositions` 使用有界游标分页，默认 50 条、最多 100 条；分页、权限、错误处理及性能边界见[报警处置接口说明](unified_backend/alarm_dispositions.md)。

### 7.6 物流通道多摄像头单人检测

统一的 `detect_logistics_single_person` feature 面向通用电气、电子电工、电气部件和伟达公司四个事业部，通道及成员按事业部隔离。管理员在对应模块的配置页新建具名通道，然后新建或绑定摄像头；每个通道支持 1–9 路摄像头，每路摄像头单独保存 ROI。监控页按成员顺序自动拼接：1 路单画面、2 路左右、3–4 路 2×2、5–9 路 3×3。

通道按所有已启用成员的最新结果联合判定：

| 摄像头结果 | 通道状态 | 报警 |
| --- | --- | --- |
| 任意一路人数大于等于 2 | 多人异常 | 达到通道“多人持续时间”后报警 |
| 全部摄像头都有新鲜结果且全部为 0 | 无人异常 | 达到通道“无人持续时间”后报警 |
| 没有多人，至少一路为 1（包括多路各 1 人） | 正常 | 不报警 |
| 存在离线、过期或未出结果的摄像头，其余均为 0 | 未知 | 不报警，未知不能当作无人 |

人体检测置信度、检测开始/结束时间、无人和多人宽限时间、报警间隔及 SQL/喇叭/微信配置均按通道保存。摄像头只保存 ROI、模型 IOU（0～1）、最小检测框面积（像素平方，非负整数）、宽高比范围（宽/高）和画面处理间隔（秒，大于 0），不包含告警配置。接口拒绝未定义字段。状态结果默认超过 5 秒即视为过期，可在启动 AiVision 前调整：

```bash
export LOGISTICS_STATUS_STALE_SECONDS=5
```

业务实现集中在 `AiVision/features/logistics_channel/`：消费者逐路推理并发布快照，`state.py` 判断人数状态与连续异常时间，`runtime.py` 控制时段、汇总和告警事件，`service.py` 与 `membership_transaction.py` 管理配置和成员事务，`compositor.py` 拼接画面。`__init__.py` 仅作包声明，唯一 SPEC 位于 `spec.py`，不预加载服务或运行时。

无人和多人分别连续计时，恢复正常、未知或停用会中断当前异常。每次持续异常成功分发后不重复创建告警事件；冷却期间未分发的事件会继续等待，恢复正常后再次异常仍受通道告警间隔限制。各路人数不相加；明确多人优先，其次至少一路正常、未知，最后才是全部无人。

现有表名保持不变。应用启动不迁移旧配置、不补造通道或转换字段。

纯逻辑回归可在项目根目录执行：

```bash
MYSQL_DB_URL=127.0.0.1 MYSQL_DB_USER=test MYSQL_DB_PASSWORD=test MYSQL_DB_NAME=test \
  DATA_PATH=/tmp/aivision-logistics-test python -m pytest -q -c AiVision/pyproject.toml AiVision/tests
python -m pytest unified_backend/tests -q
cd unified_frontend
node --test tests/*.mjs
npm run lint
npm run build
```

### 7.7 新增 AiVision 检测能力的入口

新增一个 feature 时，优先照着现有目录复制结构：

```text
AiVision/features/phone_detection/
AiVision/features/person_dwell/
```

通常要做：

1. 新建 `AiVision/features/{new_feature}/`。
2. 实现 `consumer.py`，继承 `BaseFunctionConsumer`。
3. 实现 `orm.py`，定义该功能配置表。
4. 实现 `schema.py`，定义配置校验。
5. 在 `spec.py` 定义唯一 `SPEC = FeatureSpec(...)`，在 `features/registry.py` 的显式清单中登记；`__init__.py` 只保留包说明。
6. 如果依赖新模型，确保数据库 `ai_model` 中有对应 `name` 和 `import_path`。
7. 前端增加 section、导航和 API 封装。

## 8. security_vlm 安检流程规范检测

### 8.1 业务职责

`AiVision/integrations/security_vlm` 是 AiVision 内置的安检流程模块。其 API 没有独立端口；点击开启后，
AiVision 才按配置拉起隔离的检测/VLM worker。它不是逐帧直接给 VLM，而是先用传统视觉算法
筛选出“有意义的交互 session”，再把关键帧拼图交给 VLM 判断。

核心目标：

1. 识别每个安检 ROI 内是否出现双人交互。
2. 形成一次完整安检 session。
3. 抽取关键帧。
4. 由 Qwen-VL 判断上身、中身、下身、手臂张开等流程是否合规。
5. 输出历史记录、统计、异常结果和关键帧拼图。

### 8.2 多进程架构

```text
AiVision main.py (7862，托管 security_vlm FastAPI 子应用)
  |
  +-- capture_worker.py
  |     读取 RTSP/视频源，写入 FrameHub 双缓冲共享内存
  |
  +-- detector_worker.py
  |     从 FrameHub 读帧，YOLO + ByteTrack 检测/跟踪人员
  |
  +-- session_worker.py
  |     按工位 ROI 管理双人交互 session，抽取关键帧
  |
  +-- vlm_worker.py
        消费 session_pending 队列，调用 Qwen-VL，写结果和统计
```

进程间通信由 `AiVision/integrations/security_vlm/src/frame_hub.py` 提供：

| 数据类型 | 机制 | 说明 |
| --- | --- | --- |
| 视频帧 | `/dev/shm` 双缓冲 `memmap` | 高频大数据，避免通过 JSON 或队列传大图。 |
| 状态/结果 | `/dev/shm` 原子 JSON 文件 | 小数据，使用 `os.replace` 防止读到半截文件。 |

### 8.3 API 和前端交互

`AiVision/integrations/security_vlm/src/main.py` 提供：

```text
GET  /
GET  /health
GET  /api/history
GET  /api/rois
POST /api/rois
POST /api/control/start
POST /api/control/stop
POST /api/control/restart
GET  /video/original
GET  /video/rule
```

前端封装在：

```text
unified_frontend/src/lib/security-vlm.ts
```

前端访问路径会先经过统一后端，再进入 AiVision 内的 Security VLM 子应用：

```text
/security-vlm/* -> unified_backend (:5000) -> AiVision (:7862)
```

### 8.4 关键文件

```text
AiVision/integrations/security_vlm/
├── src/main.py              # FastAPI 主进程，负责 API 和 worker 生命周期
├── src/frame_hub.py         # 共享内存帧库 + 原子 JSON 状态存储
├── src/capture_worker.py    # 读视频源，写最新帧
├── src/detector_worker.py   # YOLO + ByteTrack 检测/跟踪
├── src/session_worker.py    # ROI session 管理、关键帧抽取
├── src/vlm_worker.py        # Qwen-VL 调用、结果落盘、统计
├── configs/config.example.yaml
├── results/                 # 每个 session 的 JSON 结果
├── clips/                   # 不合规关键帧拼图
└── logs/
```

### 8.5 配置重点

运行配置应是：

```text
AiVision/integrations/security_vlm/configs/config.yaml
```

模板在：

```text
AiVision/integrations/security_vlm/configs/config.example.yaml
```

重点配置节：

| 配置节 | 作用 |
| --- | --- |
| `envs.worker_python` | worker 子进程使用的 Python 解释器。 |
| `runtime.dir` | `/dev/shm` 共享内存和状态文件目录。 |
| `data.input_video` | RTSP 或视频源。 |
| `staff_rois` | 初始工位 ROI；前端保存后以 JSON 文件为准。 |
| `yolo` | 人员检测模型、设备、阈值、ByteTrack。 |
| `session` | 双人交互 session 的开始/结束/关键帧/指纹参数。 |
| `vlm` | Qwen-VL API Key、模型、超时和并发。 |
| `budget` | 每日成本上限和单次调用估算。 |

ROI 热加载逻辑：前端 `POST /api/rois` 后写入 `staff_identity_dir/<video_id>_staff_rois.json`，`session_worker` 通过文件 mtime 自动加载，不需要重启。

## 9. 报警与统计

报警来源有三类：

| 来源 | 前端归一化位置 | 说明 |
| --- | --- | --- |
| Guard Room | `unified_frontend/src/lib/api.ts` 的 `normalizeGuardAlarm` | 离岗、玩手机、趴睡。 |
| AiVision | `normalizeAiVisionAlarm` | 区域入侵、大门、手机、人脸、人体等。 |
| Security VLM | `normalizeSecurityVlmAlarm` | VLM 判定不合规或错误。 |

`getAlarms()` 会并发读取三套系统报警，归一化后按时间倒序合并。统计页目前也是基于报警记录聚合生成。

排查报警时按以下顺序：

1. 先看具体模块页面是否有实时画面和状态。
2. 再看后端原始报警接口是否有数据。
3. 最后看 `unified_frontend/src/lib/api.ts` 的归一化逻辑是否过滤或转换了字段。

## 10. 启动方式

`run_guide.txt` 是线上 tmux 运行手册。常用启动命令如下。

### 10.1 前端

生产环境由统一启动脚本在 tmux 中启动 Vite：

```bash
bash scripts/start.sh
```

也可以只启动前端排障：

```bash
cd unified_frontend
npm run dev -- --host 0.0.0.0 --port 3000
```

生产环境公网访问：

```text
https://aicv.fudar.com/
```

临时改端口：

```bash
npm run dev -- --port <前端调试端口>
```

### 10.2 AiVision（同时承载 Guard Room 与 Security VLM API）

```bash
tmux new -s aivision
cd /usr/zyy/Fuda_CVPreject_V3
conda activate aivision
export AUTH_SECRET="<与统一后端保持同一串32位以上随机密钥>"
python -m AiVision.main
```

临时改端口：

```bash
python -m AiVision.main --port <AiVision调试端口>
```

Guard Room 随 AiVision 启动。Security VLM 的 API 同样随 AiVision 启动，但 token 推理 worker
默认关闭，只有页面点击开启后才使用 `AiVision/integrations/security_vlm/configs/config.yaml` 的 `envs.worker_python`
拉起子进程。不要再创建 `guard_room` 或 `security_vlm` tmux。

## 11. 排查问题的推荐路径

### 11.1 页面打不开

1. 运行 `bash scripts/status.sh`，确认 `unified_frontend` tmux 存在、3000 正在监听且首页返回 2xx。
2. 执行 `tmux attach -t unified_frontend`，查看 Vite 启动日志。
3. 浏览器 Network 里看失败的是静态资源，还是 `/api`、`/aivision`、`/security-vlm` 请求。
4. 检查 `npm run dev`、3000 端口和 `vite.config.ts` 代理配置。

### 11.2 登录失败

1. 在“系统管理 → 用户管理”确认该工号存在且已启用；必要时检查 `runtime/auth/auth_users.db`。
2. 确认统一后端和 AiVision 的 `AUTH_SECRET` 是否一致。
3. 看 `auth/auth.py` 的 token 签发和校验逻辑。

### 11.3 某个算法页面无画面

| 页面 | 优先检查 |
| --- | --- |
| 保安行为规范检测 | `AiVision/integrations/guard_room/src/runtime.py`、`AiVision/integrations/guard_room/config/config.yaml` 的 RTSP 和模型路径。 |
| AiVision 各检测页面 | AiVision 摄像头配置、功能是否启用、模型表是否启用、`/api/runtime/status`。 |
| 安检流程规范检测 | `aivision` 日志中 Security VLM worker 是否启动、状态 API、`runtime.dir` 下状态文件。 |

### 11.4 报警没有出现

1. 先确认算法页面是否已经判定异常。
2. 看对应后端的报警接口是否返回记录。
3. 看前端 `getAlarms()` 是否能读到该来源。
4. 如果是企业微信问题，再查对应后端的企业微信配置和日志。

### 11.5 配置改了但不生效

| 子系统 | 注意事项 |
| --- | --- |
| Guard Room | 部分规则参数被运行中对象持有，配置更新后可能需要重启检测或服务。 |
| AiVision | 摄像头/功能配置通过事件总线热更新；模型 worker 相关变化通常需要重启后端。 |
| Security VLM | ROI 支持热加载；worker_python、模型、VLM 凭据等通常需要重启服务。 |

## 12. 二次开发入口

### 12.1 新增一个前端页面

改这些文件：

```text
unified_frontend/src/lib/nav.ts
unified_frontend/src/App.tsx
unified_frontend/src/sections/<NewSection>.tsx
unified_frontend/src/lib/<new-api>.ts
```

### 12.2 新增一个 AiVision 检测能力

改这些位置：

```text
AiVision/features/{new_feature}/__init__.py
AiVision/features/{new_feature}/spec.py
AiVision/features/registry.py
AiVision/features/{new_feature}/consumer.py
AiVision/features/{new_feature}/orm.py
AiVision/features/{new_feature}/schema.py
unified_frontend/src/sections/
unified_frontend/src/lib/
```

### 12.3 调整 Guard Room 行为规则

优先看：

```text
AiVision/integrations/guard_room/src/behavior.py
AiVision/integrations/guard_room/src/consensus.py
AiVision/integrations/guard_room/config/config.yaml
```

如果涉及画面标注，看：

```text
AiVision/integrations/guard_room/src/drawing.py
```

如果涉及报警保存/推送，看：

```text
AiVision/integrations/guard_room/src/alarms.py
AiVision/integrations/guard_room/src/alarm_clip_recorder.py
AiVision/integrations/guard_room/src/wechat_notifier.py
```

### 12.4 调整 Security VLM 判定流程

优先看：

```text
AiVision/integrations/security_vlm/src/session_worker.py
AiVision/integrations/security_vlm/src/vlm_worker.py
AiVision/integrations/security_vlm/configs/config.yaml
```

如果只是改工位 ROI，走前端 ROI 编辑即可，不需要改代码。

## 13. 最重要的心智模型

这个项目由三个逻辑层组成；生产运行态是 Vite 前端加两个项目后端服务：

```text
unified_frontend = Vite 承载的门面、操作台与前端 API 代理
unified_backend  = 统一鉴权、聚合与 API 网关
AiVision         = 通用视觉能力 + Guard Room + Security VLM
```

Guard Room 与 Security VLM 是 `AiVision/integrations/` 下的业务模块，不是两个独立后端。排查问题时先判断属于哪个视觉模块，再进入 AiVision 内对应目录查看配置、API 和运行时。
