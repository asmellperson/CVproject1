# AiVision Backend v2

AiVision 后端重构版采用 **features-first** 架构：每个检测能力都是 `features/{name}` 下的自包含模块，通过 `FeatureSpec` 自动注册；API、缓存、Consumer 启动都通过注册表反射完成。

## 目录结构

```text
core/                 共享配置、DB、缓存、事件、告警
features/             检测功能模块
features/_base/       功能通用基类、配置服务、API 工厂
platform/             摄像头、推理、喇叭、违规图片、总编排
integrations/         Guard Room 与 Security VLM 内置业务模块
api/                  FastAPI v2 路由和旧路径兼容层
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

## 新 v2 路径

```text
GET    /api/v2/runtime/health
GET    /api/v2/runtime/status
GET    /api/v2/cameras
POST   /api/v2/cameras
GET    /api/v2/cameras/{key}
PUT    /api/v2/cameras/{key}
DELETE /api/v2/cameras/{key}
GET    /api/v2/cameras/{key}/frame.jpg?feature=detect_phone
GET    /api/v2/features
GET    /api/v2/features/{feature}
GET    /api/v2/features/{feature}/configs/{shm_name}
PUT    /api/v2/features/{feature}/configs/{shm_name}
```

## 旧路径兼容

旧前端可以继续访问：

```text
GET/PUT /api/ai/blocks-config/{shm_name}
GET/PUT /api/ai/door-config/{shm_name}
GET/PUT /api/ai/face-config/{shm_name}
GET/PUT /api/ai/phone-config/{shm_name}
GET/PUT /api/ai/human-config/{shm_name}
GET/POST /api/aivision/cameras
GET      /api/aivision/cameras/{key}/frame.jpg
```

旧 feature config 路径直接返回 `config` 主体；v2 路径返回 `{camera, feature, config}` 包装。

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
