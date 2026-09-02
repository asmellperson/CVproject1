# AiVision Backend

AiVision 后端重构版采用 **features-first** 架构：每个检测能力都是 `features/{name}` 下的自包含模块，通过 `FeatureSpec` 自动注册；API、缓存、Consumer 启动都通过注册表反射完成。

## 目录结构

```text
core/                 共享配置、DB、缓存、事件、告警
features/             检测功能模块
features/_base/       功能通用基类、配置管理与 Consumer
platform/             摄像头、推理、喇叭、违规图片、总编排
integrations/         Guard Room 与 Security VLM 内置业务模块
api/                  FastAPI 正式路由
main.py               后端入口
```

认证与管理员鉴权复用根目录 `auth/auth.py`；`api/auth.py` 仅保留为兼容入口。

## 启动

```bash
cd /usr/zyy/Fuda_CVPreject/AiVision
conda activate aivision
python -m pip install -r requirements.txt
cp .env.example .env
# 修改 .env 中数据库、DATA_PATH、企业微信等配置
python main.py
```

默认 API 地址：`http://0.0.0.0:7862`。

调试时可用命令行临时覆盖端口：

```bash
python main.py --port <调试端口>
```

## 正式 API 路径

```text
GET    /api/runtime/health
GET    /api/runtime/status
GET    /api/cameras
POST   /api/cameras
GET    /api/cameras/{key}
PUT    /api/cameras/{key}
DELETE /api/cameras/{key}
GET    /api/cameras/{key}/frame.jpg?feature=detect_phone
GET    /api/features
GET    /api/features/{feature}
GET    /api/features/{feature}/configs/{shm_name}
PUT    /api/features/{feature}/configs/{shm_name}
GET    /api/features/{feature}/cameras/{key}/status
GET    /api/models
POST   /api/models
PATCH  /api/models/{model_id}
GET    /api/alarms
GET    /api/alarms/{alarm_id}/image
GET    /api/alarms/{alarm_id}/video
GET    /api/departments
GET    /api/departments/{name}/features
```

## 模型配置

推理 Worker 仍从数据库 `ai_model` 表读取模型名称、`import_path` 和 `description`，
但模型文件路径只从本机配置文件读取，不再回退数据库 `ai_model.path`。
这样同一套数据库部署到不同服务器时，只需要调整每台机器自己的本机配置文件。

本机配置：

```bash
cp config/model_paths.example.yaml config/model_paths.yaml
# 修改 config/model_paths.yaml 中各模型的 path
```

默认读取 `.env` 的 `MODEL_PATHS_CONFIG=config/model_paths.yaml`，相对路径以 `AiVision`
目录为基准。配置文件中按模型 `name` 覆盖路径：

```yaml
models:
  yolo_human:
    path: /path/to/person_phone.pt
  yolo_phone:
    path: /path/to/person_phone.pt
  yolo_face:
    path: /path/to/yolov8x-face.pt
```

数据库中的 `import_path` 建议统一指向：

```text
platform.inference.workers.yolo_detector.YoloDetectorWorker
```

`description` 字段使用 JSON 控制类别过滤，例如：

```json
{"class_filter":[1],"type_label":"phone","conf":0.7}
```

详细迁移步骤见 `MIGRATION.md`。
