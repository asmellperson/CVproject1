# AiVision Backend

AiVision 后端采用 **features-first** 架构：每个检测能力都是 `features/{package}` 下的模块，在 `spec.py` 声明唯一 `FeatureSpec`，由 `features/registry.py` 显式注册；API、缓存、Consumer 启动都通过注册表查询完成。Python 包名与业务标识分离，数据库、API 和前端功能键保持原值。

## 目录结构

```text
core/                 共享配置、DB、缓存、事件及通用媒体工具
features/             检测功能模块
features/_shared/       功能通用基类、配置管理与 Consumer
features/registry.py   七项内置功能的唯一注册入口
runtime/              总编排、生命周期协调及残留进程清理
runtime/bootstrap.py  启动时注册业务 ORM、创建缺失表及核验结构
cameras/              摄像头采集、帧读取及配置管理
inference/            模型加载、推理 Worker 及运行管理
alarms/               告警分发、设备、通知、记录及证据
departments/          事业部定义、查询及约束
integrations/         Guard Room 与 Security VLM 内置业务模块
api/                  FastAPI app、依赖注入及视觉子应用挂载适配
api/routes/           正式 HTTP 路由
main.py               后端入口
```

认证与管理员鉴权直接复用根目录 `auth/auth.py`。
内置功能包为 `intrusion`、`door_state`、`face_dwell`、`person_dwell`、`phone_detection`、
`face_recognition`、`logistics_channel`；对应业务标识仍为 `blocks`、`detect_door`、
`detect_face`、`detect_human`、`detect_phone`、`recognize_face`、`detect_logistics_single_person`。
各功能包不重新导出 SPEC；查询从 `AiVision.features.registry` 导入。
总编排与进程清理从 `AiVision.runtime` 导入，视觉子应用挂载适配使用
`AiVision.api.mounted_apps`，HTTP 路由使用 `AiVision.api.routes`。
旧平台目录已删除，不保留转发包；启动入口、API URL、认证与生命周期顺序保持不变。
数据库准备由 `runtime.bootstrap.bootstrap_database()` 在 `.env` 和 settings 加载后、
创建 `mp.Manager` 前执行；`core/db.py` 只提供 Base、连接池、会话和事务等基础能力。

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
cp config/model_paths.example.yaml config/model_paths.yaml
# 修改 config/model_paths.yaml 中各模型的 path
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

详细迁移步骤见 `MIGRATION.md`。
