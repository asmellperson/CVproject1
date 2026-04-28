# AiVision 重构版迁移操作手册

本手册用于把旧 AiVision 后端替换为 features-first 重构版。设计目标是：**数据库表结构不变、旧前端路径可继续访问、blocks 和 detect_door 行为保持稳定、face/phone/human 通过通用 YOLO Worker 真正跑起来**。

## Stage 1：安装新依赖，确认 `.env`

进入项目目录并安装依赖：

```bash
cd /usr/zyy/Fuda_CVPreject/AiVision
python3.10 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

复制环境变量模板：

```bash
cp .env.example .env
vim .env
```

至少确认这些字段：

```bash
MYSQL_DB_URL=127.0.0.1
MYSQL_DB_PORT=3306
MYSQL_DB_USER=root
MYSQL_DB_PASSWORD=你的密码
MYSQL_DB_NAME=aivision
DATA_PATH=/usr/zyy/Fuda_CVPreject/AiVision/data
API_HOST=0.0.0.0
API_PORT=7862
```

企业微信从源码硬编码改为环境变量：

```bash
WECHAT_ENABLE=true
WECHAT_CORP_ID=你的企业ID
WECHAT_CORP_SECRET=你的应用Secret
WECHAT_AGENT_ID=1000050
```

如果暂时不测微信，设置：

```bash
WECHAT_ENABLE=false
```

## Stage 2：备份 `aivision` 数据库

替换代码前先备份数据库：

```bash
mysqldump -h 127.0.0.1 -P 3306 -u root -p \
  --single-transaction --routines --triggers aivision \
  > aivision_backup_$(date +%Y%m%d_%H%M%S).sql
```

本次重构 **不要求改表结构**，但会更新 `ai_model.import_path`、`ai_model.description` 和必要的模型路径，所以仍然建议备份。

## Stage 3：替换代码

把完成版 tar 包覆盖到原 AiVision 目录。示例：

```bash
cd /usr/zyy/Fuda_CVPreject
mv AiVision AiVision_backup_$(date +%Y%m%d_%H%M%S)
mkdir -p AiVision
tar -xzf aivision_refactor_complete.tar.gz -C AiVision
```

如果你是在当前目录直接覆盖：

```bash
tar -xzf aivision_refactor_complete.tar.gz -C /usr/zyy/Fuda_CVPreject/AiVision
```

确认关键文件存在：

```bash
ls api main.py pyproject.toml .env.example MIGRATION.md
```

## Stage 4：执行 SQL UPDATE 修正 `ai_model`

重构版以数据库 `ai_model.path` 为准，不在代码里写死模型路径。请按现场实际路径更新。

```sql
UPDATE ai_model SET 
  path='/usr/zyy/Fuda_CVPreject/guard_room/models/person_phone.pt',
  description='{"class_filter":[0],"type_label":"person","conf":0.3}',
  import_path='platform.inference.workers.yolo_detector.YoloDetectorWorker',
  enable=1
WHERE name='yolo_human';

UPDATE ai_model SET 
  path='/usr/zyy/Fuda_CVPreject/guard_room/models/person_phone.pt',
  description='{"class_filter":[1],"type_label":"phone","conf":0.7}',
  import_path='platform.inference.workers.yolo_detector.YoloDetectorWorker',
  enable=1
WHERE name='yolo_phone';

UPDATE ai_model SET 
  path='/srv/cv/research/models/face/yolov8x-face-lindevs.pt',
  description='{"type_label":"face","conf":0.6}',
  import_path='platform.inference.workers.yolo_detector.YoloDetectorWorker',
  enable=1
WHERE name='yolo_face';
```

检查更新结果：

```sql
SELECT name, path, import_path, description, enable
FROM ai_model
WHERE name IN ('yolo_human', 'yolo_phone', 'yolo_face');
```

## Stage 5：启动并验证 blocks + detect_door

启动后端：

```bash
cd /usr/zyy/Fuda_CVPreject/AiVision
source .venv/bin/activate
python main.py
```

另开终端验证 API：

```bash
curl http://127.0.0.1:7862/api/v2/runtime/health
curl http://127.0.0.1:7862/api/v2/runtime/status
curl http://127.0.0.1:7862/api/v2/cameras
```

旧路径也应该可用：

```bash
curl http://127.0.0.1:7862/api/aivision/cameras
curl http://127.0.0.1:7862/api/ai/blocks-config/<shm_name>
curl http://127.0.0.1:7862/api/ai/door-config/<shm_name>
```

帧接口：

```bash
curl -o frame.jpg http://127.0.0.1:7862/api/aivision/cameras/<shm_name>/frame.jpg
curl -o frame_v2.jpg 'http://127.0.0.1:7862/api/v2/cameras/<shm_name>/frame.jpg?feature=blocks'
```

预期：

- `/api/v2/runtime/status` 中 `started=true`。
- `running_cameras` 包含启用摄像头的 `shm_name`。
- `running_consumers` 至少包含 `blocks` 和 `detect_door`，前提是对应功能配置启用。
- blocks 和 detect_door 不依赖 YOLO，即使模型未启动也应能运行。

## Stage 6：验证 face / phone / human 第一次真正跑起来

确认模型路径存在：

```bash
ls -lh /usr/zyy/Fuda_CVPreject/guard_room/models/person_phone.pt
ls -lh /srv/cv/research/models/face/yolov8x-face-lindevs.pt
```

确认 Python 环境能导入 YOLO：

```bash
source .venv/bin/activate
python - <<'PY'
from ultralytics import YOLO
print('ultralytics ok')
PY
```

启动后看日志：

```text
[InferenceManager] 推理 Worker 启动: yolo_human
[InferenceManager] 推理 Worker 启动: yolo_phone
[InferenceManager] 推理 Worker 启动: yolo_face
[detect_phone] Consumer 已启动
[detect_human] Consumer 已启动
[detect_face] Consumer 已启动
```

如果某个 Consumer 被跳过，重点检查：

1. `ai_model.enable=1`。
2. `ai_model.import_path` 是否为 `platform.inference.workers.yolo_detector.YoloDetectorWorker`。
3. `ai_model.path` 文件是否真实存在。
4. `description` 是否为合法 JSON。
5. 当前虚拟环境是否安装 `ultralytics`、`torch`、`opencv-python`。

验证标注帧：

```bash
curl -o phone.jpg 'http://127.0.0.1:7862/api/v2/cameras/<shm_name>/frame.jpg?feature=detect_phone'
curl -o human.jpg 'http://127.0.0.1:7862/api/v2/cameras/<shm_name>/frame.jpg?feature=detect_human'
curl -o face.jpg  'http://127.0.0.1:7862/api/v2/cameras/<shm_name>/frame.jpg?feature=detect_face'
```

## 回滚方案

如果新版本启动失败，停止进程并恢复代码备份：

```bash
pkill -f 'python main.py' || true
cd /usr/zyy/Fuda_CVPreject
mv AiVision AiVision_failed_$(date +%Y%m%d_%H%M%S)
mv AiVision_backup_YYYYMMDD_HHMMSS AiVision
```

恢复数据库：

```bash
mysql -h 127.0.0.1 -P 3306 -u root -p aivision < aivision_backup_YYYYMMDD_HHMMSS.sql
```

## 常见问题

### 1. `Orchestrator 未初始化`

不要直接用 `uvicorn api.app:app` 启动。必须运行：

```bash
python main.py
```

因为 `main.py` 会创建 `multiprocessing.Manager()` 并初始化 Orchestrator。

### 2. 旧前端配置接口 404

确认路径使用的是：

```text
/api/ai/blocks-config/{shm_name}
/api/ai/door-config/{shm_name}
/api/ai/face-config/{shm_name}
/api/ai/phone-config/{shm_name}
/api/ai/human-config/{shm_name}
```

其中 `{shm_name}` 可以是 `ai_camera_config.shm_name`，也兼容摄像头名称、数字 id 和 `camera_{id}`。

### 3. 第三方库 `import platform` 异常

项目保留了顶层 `platform/` 包名。新版 `platform/__init__.py` 已代理 Python 标准库 `platform` 的公开函数，同时支持本项目的 `platform.camera` 等子包。如果仍出现异常，优先检查是否存在旧的残留 `platform.py` 文件。
