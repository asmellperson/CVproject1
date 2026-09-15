# AiVision Backend

AiVision 后端采用 **features-first** 架构：每个检测能力都是 `features/{package}` 下的模块，在 `spec.py` 声明唯一 `FeatureSpec`，由 `features/registry.py` 显式注册；API、缓存、Consumer 启动都通过注册表查询完成。Python 包名与业务标识分离，数据库、API 和前端功能键保持原值。

## 目录结构

```text
AiVision/
├── main.py                      # 正式启动入口
├── api/
│   ├── app.py                   # FastAPI 应用创建
│   ├── deps.py                  # 共享依赖注入
│   ├── mounted_apps.py          # Guard Room / Security VLM 挂载适配
│   └── routes/                  # HTTP API 路由
├── runtime/
│   ├── bootstrap.py             # 启动阶段数据库初始化
│   ├── orchestrator.py          # 总运行调度
│   └── process_cleanup.py       # 残留进程清理
├── cameras/                     # 摄像头配置、采集与帧读取
├── inference/                   # 模型、推理 Worker 和运行管理
├── alarms/                      # 设备、分发、通知、记录与证据
├── departments/                 # 事业部定义、查询与约束
├── features/
│   ├── __init__.py              # 简单包声明
│   ├── registry.py              # 七项内置功能唯一注册入口
│   ├── _shared/                 # 通用基类、配置与跟踪计时
│   ├── intrusion/
│   ├── door_state/
│   ├── face_dwell/
│   ├── person_dwell/
│   ├── phone_detection/
│   ├── face_recognition/        # 含 library/ 人员与特征底库
│   └── logistics_channel/
├── core/                        # 配置、数据库基础能力、缓存、事件及公共工具
├── connectors/                  # 外部系统协议与客户端，当前含 hikvision/
├── integrations/                # 内置 Guard Room / Security VLM
├── config/                      # 模型路径配置模板
├── migrations/                  # 显式离线业务迁移与说明
└── tests/
```

**Python 包名与业务标识分离**。数据库、API 和前端继续使用右列，不能改成目录名：

| Python 包 | `FeatureSpec.name` |
| --- | --- |
| `intrusion` | `blocks` |
| `door_state` | `detect_door` |
| `face_dwell` | `detect_face` |
| `person_dwell` | `detect_human` |
| `phone_detection` | `detect_phone` |
| `face_recognition` | `recognize_face` |
| `logistics_channel` | `detect_logistics_single_person` |

每个功能的唯一 SPEC 定义在自身 `spec.py`。`AiVision.features.registry` 显式导入七项 SPEC，
拒绝重复名称，导入错误直接传播；`all_specs()`、`get_spec()`、`list_orm_classes()` 均从该入口导入。
根包与各功能 `__init__.py` 只作包声明，不自动扫描、不注册、不转发 SPEC 或查询函数。
人员逗留只有一套 Consumer、Schema 和配置表，同时支持通用电气与皓达，按摄像头和事业部隔离。

认证与管理员鉴权复用根目录 `auth/auth.py`。正式启动顺序为：

```text
.env → settings → runtime.bootstrap.bootstrap_database()
     → mp.Manager → init_orchestrator → orchestrator.start()
     → create_app / Uvicorn
```

bootstrap 在调用时集中注册 ORM、创建缺失表并核验现有结构，不负责启动业务运行资源。
`core/db.py` 只提供 Base、连接池、会话与事务；`core/schema.py` 提供通用结构核验工具。
`core/cache.py` 仍有摄像头和 Feature 依赖，未在本批重构。
主启动不使用旧 schema 初始化入口；人脸库 CLI 与 Guard Room 的独立建表流程保留。
旧平台目录已删除，API URL、业务标识、权限及其他运行顺序保持不变。

## 启动

```bash
cd /usr/zyy/Fuda_CVPreject_V3
conda activate aivision
python -m pip install -r AiVision/requirements.txt
cp AiVision/.env.example AiVision/.env
# 修改 .env 中数据库、DATA_PATH、企业微信等配置
python -m AiVision.main
```

默认 API 地址：`http://0.0.0.0:7862`。

调试时可用命令行临时覆盖端口：

```bash
python -m AiVision.main --port <调试端口>
```

## 正式 API 路径

```text
GET    /api/runtime/health
GET    /api/runtime/status
GET    /api/cameras
POST   /api/cameras
GET    /api/cameras/{key}
PATCH  /api/cameras/{key}
DELETE /api/cameras/{key}
GET    /api/cameras/{key}/frame.jpg?feature=detect_phone
GET    /api/features
GET    /api/features/{feature}
GET    /api/features/{feature}/configs/{shm_name}
PUT    /api/features/{feature}/configs/{shm_name}
GET    /api/features/{feature}/cameras/{key}/status
GET    /api/models
PATCH  /api/models/{model_name}/path
GET    /api/alarms
GET    /api/alarms/{alarm_id}/image
GET    /api/alarms/{alarm_id}/video
GET    /api/departments
GET    /api/departments/{name}/features
```

## 模型配置

模型名称、Worker 类和推理参数固定注册在 `inference/model_registry.py`。
推理包的正式导入路径为 `AiVision.inference`；`workers/` 内部结构及公开接口保持不变。
模型文件路径只从本机 YAML 配置读取，不再依赖 `ai_model` 表。
相同物理权重由多个逻辑模型共享一个 Worker，保留各自的类别过滤与结果标签。

管理员通过 `PATCH /api/models/{model_name}/path` 保存路径；接口校验本机文件，
保留 YAML 注释并原子写入、清除路径缓存，返回 HTTP 202 与
`configuration_saved=true`。重载在后台进行，通过 `GET /api/models` 查询
`reload.status`（`loading/succeeded/failed`）及真实 `runtime` 状态。
服务未启动时返回 `not_started`，不把配置保存当成模型加载成功。
修改共享权重的路径会重载相关逻辑模型，不会替换 Consumer 持有的队列。

旧数据库中的 `ai_model` 表不再创建、读取或修改；升级不自动 DROP 历史表。
确认没有旧版本服务使用该表并备份后，可由数据库维护流程删除。

本机配置：

```bash
cp AiVision/config/model_paths.example.yaml AiVision/config/model_paths.yaml
# 在项目根目录执行；修改 AiVision/config/model_paths.yaml 中各模型的 path
```

默认读取 `.env` 的 `MODEL_PATHS_CONFIG=config/model_paths.yaml`，相对路径以 `AiVision`
目录为基准。推理目录迁移后仍保持该基准，模型权重位置及环境变量含义不变。
配置文件中按模型 `name` 覆盖路径：

```yaml
models:
  yolo_human:
    path: /path/to/person_phone.pt
  yolo_phone:
    path: /path/to/person_phone.pt
  insightface_detection:
    path: /srv/models/insightface/buffalo_l/det_10g.onnx
  insightface:
    path: /srv/models/insightface/buffalo_l
```

固定注册项直接引用 Worker 类，并通过 `class_filter`、`type_label`、`conf`、`iou`
明确声明推理参数，不再解析数据库导入路径或 description JSON。

模型注册与主启动结构见[根 README](../README.md)。目录整理不执行业务数据迁移；
现有离线脚本及各自说明位于 `migrations/`，不由启动入口自动运行。

## 人脸库 CLI 与定时同步

人员与特征底库位于 `features/face_recognition/library/`。在项目根目录显式执行的命令为：

```bash
python -m AiVision.features.face_recognition.library.sync
python -m AiVision.features.face_recognition.library.embedding
```

两项 CLI 均按源码层级定位 `AiVision/.env`，不依赖工作目录，系统环境变量优先。
[service](features/face_recognition/library/hikvision-face-library-sync.service) 与
[timer](features/face_recognition/library/hikvision-face-library-sync.timer) 保持原名称和时序；
`ExecStart` 已使用新的同步模块路径，timer 关联的 service 文件存在。
模板没有 `EnvironmentFile` 指令，配置由 CLI 加载。
模板 `WorkingDirectory=/srv/Fuda_CVPreject` 在本机不存在；指定解释器
`/root/miniconda3/envs/aivision/bin/python` 存在，但未验证依赖。
部署时需核实目标目录、解释器及相应 `.env`，不能把模板视为已部署配置。

## 本批静态收尾

第三批-2 仅同步文档及静态引用，未运行测试、导入业务模块、启动服务、连接数据库、
加载模型、拉取 RTSP 或执行同步任务。既有测试数字属于历史批次，见根 README 对应说明。
`.gitignore` 允许 runtime 的四个现有源码文件、features 和 api/routes；运行数据、日志、
模型、缓存、临时文件和真实配置仍不提交。历史文档及 integrations 中保留的历史调用注释
见根 README 的“架构收尾的静态检查范围”，不作为当前导入依据。
