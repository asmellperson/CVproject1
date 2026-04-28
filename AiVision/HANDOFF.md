# AiVision 重构 — 新对话交接文档

把这份文档 + 配套的 `aivision_refactor_part1_to_3_partial.tar.gz`(包含已完成的 50+ 个文件)
一起发给新对话的 Claude,他就能无缝接上继续。

---

## TL;DR(给新对话 Claude 看的最简上下文)

我在重构一个叫 **AiVision** 的 Python AI 视觉监控后端项目,目录在 `./AiVision/`,
直接覆盖原目录(老代码会被替换)。

新架构是 **features-first(方案A)** + **API v2 + 旧路径兼容**:

```
AiVision/
├── core/                     # 共享基础设施(已完成)
├── platform/                 # 摄像头/推理/告警设备/违规图片(已完成)
├── features/                 # 5 个功能模块,每个自包含(已完成)
│   ├── _base/                # 通用基类 + API 工厂
│   ├── blocks/               # 区域入侵
│   ├── detect_door/          # 大门
│   ├── detect_face/          # 人脸逗留
│   ├── detect_phone/         # 手机
│   └── detect_human/         # 人体逗留
├── api/                      # FastAPI 路由(待完成)★
├── main.py                   # 极简入口(待完成)★
├── .env.example              # 环境变量模板(待完成)★
└── _archive/migrations/      # 旧迁移脚本归档(无需新写,只需移动)
```

★ = **新对话需要继续完成的部分**,详情见下方"剩余 TODO"。

---

## 关键设计决策(已敲定,不要改方向)

### 1. FeatureSpec 注册机制
每个 `features/{name}/__init__.py` 导出 `SPEC = FeatureSpec(...)`,
`features/__init__.py` 自动发现注册。所有跨功能逻辑(API/ORM/Cache/Consumer 启动)
都通过 SPEC 反射,**加新功能只需要新建一个目录**,零改动现有代码。

### 2. 5 个旧 *_config_api.py 文件被消除
通过 `features/_base/api.py` 一个工厂方法支撑所有 feature 的配置 CRUD。
新前端路径: `/api/v2/features/{feature}/configs/{shm_name}`(GET/PUT)。
旧路径 `/api/ai/{feature}-config/{shm_name}` 由 `api/compat.py` 转发到 v2(待写)。

### 3. 5 个 ORM 表的告警字段重复被消除
`features/_base/orm.py` 提供 `FeatureConfigBase` 基类(含 mixin),
每个 feature 的 ORM 只写自己的特有字段。**数据库表结构不变**,无需迁移。

### 4. CapManager(700 行上帝对象)被拆解
- `platform/camera/manager.py` — 摄像头进程
- `platform/inference/manager.py` — 推理 Worker 进程
- `platform/camera/frame_reader.py` — 统一帧读取
- `platform/orchestrator.py` — 总编排,~200 行

### 5. 配置加载从 os.getenv 改为 Pydantic Settings
`core/settings.py` 集中管理。**用户的 .env 字段没变**,只是加载方式变。

### 6. 推理(ModelWorker)首版有了通用实现
旧代码假设 `function/models/yolo_*_worker.py` 三个文件存在但实际不存在,
导致 face/phone/human 实际从未跑起来过。
新代码提供 `platform/inference/workers/yolo_detector.py` —— 一个通用 YOLO Worker
通过 `ai_model.description` JSON 配置 class_filter 实现一个模型支持多用途
(用户的 person_phone.pt 同时给 detect_human 和 detect_phone 用)。

### 7. 微信告警保持现状
**不录视频,不发视频**,只发文本+图片(用户原话)。
代码已写在 `core/alarm/wechat.py`,凭据从 `WECHAT_CORP_ID` / `WECHAT_CORP_SECRET` 环境变量读
(旧代码硬编码在源码里,这是一个改动)。

### 8. 旧 `migrations/` 20 个一次性脚本归档到 `_archive/migrations/`
不参与运行。无需重写新迁移脚本(因为表结构不变)。

### 9. 用户的真实模型路径(数据库 ai_model.path 字段)
- `yolo_phone` / `yolo_human` → `/usr/zyy/Fuda_CVPreject/guard_room/models/person_phone.pt`
  (class 0=人, class 1=手机)
- `yolo_face` → `/srv/cv/research/models/face/yolov8x-face-lindevs.pt`

用户原话: **代码以数据库路径为准,不假设也不替换。**

启用新代码前,需要执行的数据库 UPDATE:
```sql
UPDATE ai_model SET 
  description='{"class_filter":[0],"type_label":"person","conf":0.3}',
  import_path='platform.inference.workers.yolo_detector.YoloDetectorWorker'
WHERE name='yolo_human';

UPDATE ai_model SET 
  description='{"class_filter":[1],"type_label":"phone","conf":0.7}',
  import_path='platform.inference.workers.yolo_detector.YoloDetectorWorker'
WHERE name='yolo_phone';

UPDATE ai_model SET 
  description='{"type_label":"face","conf":0.6}',
  import_path='platform.inference.workers.yolo_detector.YoloDetectorWorker'
WHERE name='yolo_face';

-- 用户已确认数据库里 path 字段需要更新到上面的实际路径
```

---

## 项目背景信息

- **范围**:只重构 AiVision/。`guard_room/` 和 `unified_frontend/` 是另外两个独立项目,**不动**
- **前端约束**:用户会跟着改前端,所以 API 路径可以改 → 因此采用了 v2 路径
- **数据库**:MySQL,表结构**不变**,只是 ORM 类换位置
- **当前实际跑起来的**:只有 blocks 和 detect_door(纯帧差,无需推理),
  其他三个 detect_* 因为 ModelWorker 缺失被 `[WARN] 跳过消费者` 跳过了
- **重构后**:5 个功能全部能跑起来(face/phone/human 第一次真正能用)

---

## 已完成的文件清单(共 51 个)

```
01_FILE_MAPPING.md                  # 旧→新映射表

core/
  settings.py                       # ★ Pydantic Settings,替代散落 os.getenv
  db.py                              # SQLAlchemy 引擎/会话/Base 唯一来源
  cache.py                           # ★ 通过 features 注册表反射,不再硬编码 5 个表
  events.py                          # 事件总线(从旧 config/events.py 几乎搬不动)
  logger.py                          # DEBUG_FEATURES 环境变量更友好
  alarm/
    horn.py                          # 用法改为 horn.play(event_id)
    wechat.py                        # ★ 凭据从环境变量读,只发文本+图片
    dispatcher.py                    # ★ 全新,告警判定/分发从 Consumer 抽出
    __init__.py

features/
  __init__.py                        # ★ 自动发现注册所有 feature
  _base/
    spec.py                          # ★ FeatureSpec dataclass — 架构灵魂
    orm.py                           # ★ FeatureConfigBase mixin,消除 5 表字段重复
    api.py                           # ★ 通用 API 工厂,消除 5 个 *_config_api.py
    service.py                       # ★ 通用 CRUD,消除 5 个 save_xxx_config_by_shm_name
    consumer.py                      # ★ BaseFunctionConsumer 重构(从 700 行瘦到 250 行)
    tracking.py                      # ★ IouTracker 通用,消除 face/human 重复
    dwell_consumer.py                # ★ face/human 共用模板
  blocks/
    __init__.py / orm.py / schema.py / consumer.py
  detect_door/
    __init__.py / orm.py / schema.py / consumer.py  # 双阶段告警保留
  detect_face/
    __init__.py / orm.py / schema.py / consumer.py  # 仅 3 行(继承 dwell_consumer)
  detect_phone/
    __init__.py / orm.py / schema.py / consumer.py
  detect_human/
    __init__.py / orm.py / schema.py / consumer.py  # 仅 3 行

platform/
  camera/
    orm.py / service.py / runtime.py / frame_reader.py / manager.py
  inference/
    orm.py / service.py / base_worker.py / manager.py
    workers/
      yolo_detector.py / __init__.py
  alarm_device/
    orm.py / service.py
  violation/
    orm.py / service.py
  orchestrator.py                    # ★ 替代 700 行 CapManager,~250 行
```

---

## 剩余 TODO(新对话需完成)

### 必做(让代码能跑起来)

#### A) `__init__.py` 文件(空的,但 Python 包需要)
```
core/__init__.py
platform/__init__.py
platform/camera/__init__.py
platform/inference/__init__.py
platform/alarm_device/__init__.py
platform/violation/__init__.py
features/_base/__init__.py
features/blocks/  features/detect_*/  下面都已有 __init__.py
```

#### B) API 层(用户前端依赖)
```
api/__init__.py
api/app.py              # FastAPI 实例 + 中间件 + CORS + 路由注册
api/deps.py             # FastAPI Depends(get_orchestrator 等)
api/v2/__init__.py
api/v2/cameras.py       # /api/v2/cameras 摄像头 CRUD + 帧获取
api/v2/features.py      # /api/v2/features/{feature}/configs/{shm_name}
                        # 直接用 features._base.api.create_features_router(feature_config_service)
api/v2/runtime.py       # /api/v2/runtime/health  /api/v2/runtime/status
api/compat.py           # 旧路径兼容层:
                        #   GET/PUT /api/ai/blocks-config/{shm_name}
                        #   GET/PUT /api/ai/door-config/{shm_name}
                        #   GET/PUT /api/ai/face-config/{shm_name}  
                        #   GET/PUT /api/ai/phone-config/{shm_name}
                        #   GET/PUT /api/ai/human-config/{shm_name}
                        #   GET/POST /api/aivision/cameras
                        #   GET /api/aivision/cameras/{key}/frame.jpg
                        # 内部转调 v2 实现,响应体保持旧格式
                        # (前端切完后下一版可删)
```

#### C) 入口
```
main.py                 # ~50 行
                        # 1. multiprocessing.set_start_method("spawn")
                        # 2. 加载 .env
                        # 3. 信号处理(SIGINT/SIGTERM → orchestrator.stop)
                        # 4. mp.Manager() → init_orchestrator(mp_manager)
                        # 5. orchestrator.start()
                        # 6. uvicorn.run(api.app)
```

#### D) 配置和依赖
```
.env.example            # 在用户现有 .env 基础上加 WECHAT_CORP_ID/SECRET/AGENT_ID
                        # 加 DEBUG_FEATURES (可选)
                        # 加 API_HOST/API_PORT (可选)
pyproject.toml          # 替代散落的依赖管理
                        # 关键依赖:
                        # fastapi, uvicorn, pydantic-settings, sqlalchemy, pymysql
                        # apscheduler, pytz, opencv-python, numpy
                        # ultralytics(YOLO), requests, setproctitle
```

#### E) 文档和迁移
```
README.md               # 新架构说明 + 启动方法
MIGRATION.md            # 6 阶段迁移操作手册:
                        #   Stage 1: 安装新依赖,确认 .env
                        #   Stage 2: 备份 aivision 数据库
                        #   Stage 3: 替换代码(用 tar 包覆盖 AiVision/)
                        #   Stage 4: 执行上面的 SQL UPDATE 修 ai_model
                        #   Stage 5: 启动验证 (blocks + detect_door 应该和之前一样跑)
                        #   Stage 6: 验证 face/phone/human 第一次能跑起来
```

### 选做(质量改进)

```
tests/                  # pytest 单元测试
  test_features_blocks.py
  test_api_features.py
  test_orchestrator.py
```

---

## 用户的偏好/原话

- 重构幅度:**结构+重复代码合并** (问 #2)
- 数据库:**可以改但需迁移脚本** (问 #3) — 实际我这次设计成不需要迁移
- API 路径:**可以改,前端我会一起改** (Q2)
- 范围:**只 AiVision,guard_room 后续再看** (Q1)
- 录屏:**不做,微信只发文本+图片** (Q1/Q2)
- 节奏:**分批发,每批 review** (Q2 of 节奏)
- 代码位置:**重写 AiVision/ 原目录,老代码直接被覆盖** (Q2 of 实际状态)

## 用户技术栈备注

- Python 3.10
- venv 在 `AiVision/.venv/`
- 用户对企业微信 corpsecret 硬编码在源码不在意,但我新代码改成了环境变量
  (用户没反对就保留)

---

## 新对话开场白建议

```
你好。我在继续一个 AiVision 后端重构项目,前一个对话已经完成了 51 个文件的核心架构。

附件 aivision_refactor_part1_to_3_partial.tar.gz 是已完成的所有代码,
HANDOFF.md 是项目背景和剩余 TODO。

请你先读 HANDOFF.md,然后帮我完成剩余的:
1. 所有 __init__.py 文件(让 Python 包能 import)
2. api/ 全部(尤其是 api/compat.py 的旧路径兼容层 — 我前端要继续用旧路径)
3. main.py 入口
4. .env.example + pyproject.toml
5. MIGRATION.md 操作手册

不需要重新讨论方向,直接出代码。
```
