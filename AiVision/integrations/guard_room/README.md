
# AiVision 值班室 AI 行为监控模块

基于多路摄像头的实时保安行为监控系统，自动检测**离岗、玩手机、趴睡**三类异常行为，并通过企业微信推送带视频的报警消息。
![alt text](guard_room架构图.png)

---

## 目录

- [功能概览](#功能概览)
- [系统架构](#系统架构)
- [处理流程](#处理流程)
- [代码文件说明](#代码文件说明)
- [环境与依赖](#环境与依赖)
- [快速启动](#快速启动)
- [配置说明](#配置说明)
- [API 接口](#api-接口)

---

## 功能概览

| 功能 | 说明 |
|------|------|
| 多路摄像头接入 | 支持最多 9 路 RTSP 摄像头并行拉流 |
| 制服识别 | 使用 ConvNeXtV2 分类模型区分保安与非保安，仅对保安做行为分析 |
| 离岗检测 | 所有摄像头均超过阈值时间未见保安，触发报警 |
| 玩手机检测 | 手机框与保安框在时间窗口内持续关联，触发报警 |
| 趴睡检测 | 结合姿态估计（低头比率）与运动量判断趴睡状态 |
| 多摄像头共识 | 各路摄像头独立分析，汇聚后统一裁决|
| 报警录制 | 触发报警时自动录制 5 秒（可配）MP4 视频片段 |
| 企业微信推送 | 报警视频异步推送到指定员工 |
| Web 管理界面 | FastAPI 提供状态查询、配置管理、MJPEG 推流、报警回放等接口 |
| JWT 认证 | 通过根目录 `auth/auth.py` 提供，HttpOnly Cookie + Bearer Token 双模式，支持 admin/viewer 角色 |

---

## 系统架构

```
摄像头 RTSP 流
    │
    ▼
RTSPReader (每路一个守护线程)
    │  写入最新帧
    ▼
LatestFrameBuffer (单槽缓冲，始终保留最新帧)
    │
    ▼
GuardRoomRuntime._run_loop (主循环线程)
    │
    ├─► ThreadPoolExecutor (每路摄像头并行)
    │       │
    │       └─► _process_one_camera()
    │               ├─ YOLO 人体检测 + ByteTrack 跟踪
    │               ├─ UniformClassifier 制服识别 (含 TTL 缓存)
    │               ├─ TrackGuardGate 识别结果平滑
    │               ├─ 手机检测 (裁图/全图模式)
    │               ├─ PoseEstimator 姿态估计
    │               └─ BehaviorEngine 行为规则判断
    │
    ├─► MultiCameraConsensus 多摄像头共识裁决
    │
    ├─► AlarmManager 报警去抖 + 快照保存 + 持久化
    │
    ├─► AlarmClipRecorder 报警视频录制
    │
    ├─► WeChatNotifier 企业微信异步推送
    │
    └─► AppState 共享状态更新 (供 Web API 读取)
            │
            ▼
        FastAPI Server
        /api/stream.mjpg  /api/alarms  /api/status ...
```

---

## 处理流程

### 1. 拉流与缓冲
每路摄像头启动一个 `RTSPReader` 守护线程持续拉流，写入对应的 `LatestFrameBuffer`（单槽，始终只保留最新帧）。主循环检测到新帧后才触发推理，跳帧由 `process_every_n_frames` 控制。

### 2. 单路摄像头处理（并行）
主循环将各路摄像头的帧提交到线程池，每路独立执行：

```
原始帧
 → YOLO 人体检测（带 ByteTrack 跟踪）
 → UniformClassifier 制服识别（TTL 缓存，避免逐帧重复推理）
 → TrackGuardGate 识别结果保持（容忍短暂遮挡）
 → 手机检测（默认对保安区域裁图批量推理，过滤平板误检）
 → PoseEstimator 姿态估计（全图单次推理，按 IoU 匹配 track_id）
 → BehaviorEngine 行为规则判断（离岗/手机/趴睡）
 → 标注帧绘制
```

### 3. 多摄像头共识
各路结果汇聚到 `MultiCameraConsensus`：
- **离岗**：所有在线摄像头均超出宽限期未见保安（"全否"策略）
- **手机/趴睡**：任一摄像头命中即报警（"任一"策略），取最高置信度

### 4. 报警触发
```
共识结果 active
 → _emit_alarm_once()（锁存去重，防止行为持续期间重复触发）
 → AlarmManager.emit()（冷却期过滤，保存 JPEG 快照，持久化 JSON）
 → AlarmClipRecorder.start_clip()（启动视频录制任务）
 → 视频录制完成 → WeChatNotifier.notify_alarm()（异步推送）
```

### 5. 行为规则详解

**离岗**：从"最后一次见到保安"时刻起计时，超过 `absent_alarm_seconds` 触发。`guard_hold_seconds` 宽限期容忍保安短暂走出画面。

**手机**：三层过滤——①空间过滤（手机框在人体框扩展区域且位于上半身）→ ②时间窗口（`phone_window_seconds` 内命中 `phone_min_hits_in_window` 帧）→ ③持续时长（激活时长 ≥ `phone_seconds`）。`phone_grace_seconds` 宽限期容忍短暂漏检。

**趴睡**：低头（`head_down_ratio ≥ prone_head_down_ratio_threshold`）+ 静止（帧间位移 ≤ `static_motion_threshold`）持续 `prone_sleep_seconds` 秒触发。帧计数采用软衰减（满足 +1，不满足 -2）避免单帧噪声。

---

## 代码文件说明

```
项目根目录/
├── config/
│   └── config.yaml          # 主配置文件
├── models/
│   ├── person_phone.pt      # YOLO 检测模型（人体+手机）
│   ├── uniform_classes.pt   # 制服分类模型（ConvNeXtV2）
│   └── yolo11n-pose.engine  # 姿态估计模型（TensorRT）
├── outputs/                 # 运行输出（快照、视频、报警记录）
└── src/（或包目录）
    ├── types.py             # 全局数据类型（Detection、AlarmEvent 等）
    ├── config.py            # 配置加载（AppConfig 及各子配置 dataclass）
    ├── utils.py             # 通用工具函数（ensure_dir、now_str、safe_float）
    ├── geometry.py          # 几何计算（IoU、中心点、多边形转换）
    ├── drawing.py           # 画面标注（检测框、多边形、调试文字、报警横幅）
    ├── auth.py              # 认证授权兼容入口，实际逻辑在仓库根目录 auth/auth.py
    ├── state.py             # 共享状态（AppState，运行时与 Web API 的数据中转站）
    ├── guard_gate.py        # 保安识别结果平滑（hold_seconds 宽限期）
    ├── uniform.py           # 制服识别分类器（ConvNeXtV2，timm）
    ├── pose.py              # 姿态估计（YOLO-Pose，全图单次推理）
    ├── behavior.py          # 行为规则引擎（离岗/手机/趴睡的跨帧时序判断）
    ├── consensus.py         # 多摄像头共识（多路结果汇聚裁决）
    ├── alarms.py            # 报警事件管理（冷却、快照、JSON 持久化）
    ├── alarm_clip_recorder.py  # 报警视频片段录制（触发式固定时长录制）
    ├── wechat_sender.py     # 企业微信 API 调用（上传视频、发送消息）
    ├── wechat_notifier.py   # 企业微信推送器（异步队列，不阻塞主循环）
    ├── runtime.py           # 系统运行时核心（串联所有子模块的主循环）
    └── server.py            # FastAPI Web 服务（API 路由、认证中间件、推流）
```

### 模块依赖关系（从底层到顶层）

```
types / utils / geometry
       │
       ▼
config / drawing / auth
       │
       ▼
guard_gate / uniform / pose / behavior / consensus / alarms / alarm_clip_recorder
       │
       ▼
wechat_sender → wechat_notifier
       │
       ▼
state ←→ runtime
       │
       ▼
     server
```

---

## 环境与依赖

### 运行环境

```bash
conda activate aivision
```

本模块由 AiVision 直接加载，不再创建或启动独立的 `guard_room` Web 环境。

### 主要依赖

```
ultralytics      # YOLO 检测与姿态估计
timm             # ConvNeXtV2 制服分类模型
torch torchvision
opencv-python
fastapi uvicorn
pydantic
pyyaml
requests
pillow
```

### 安装依赖

```bash
conda run -n aivision python -m pip install \
  -r AiVision/requirements.txt \
  -c requirements-python311.lock
```

---

## 快速启动

### 1. 准备配置文件

```bash
cp AiVision/integrations/guard_room/config/config.example.yaml \
  AiVision/integrations/guard_room/config/config.yaml
# 编辑 config.yaml，填写摄像头地址、模型路径、企业微信凭证
```

### 2. 启动 AiVision

```bash
cd <仓库根目录>
bash scripts/start.sh
```

Guard Room 作为 FastAPI 子应用挂载在 AiVision 的 7862 端口，不再监听独立端口。

### 3. 验证服务

```bash
curl http://localhost:7862/api/integrations/guard-room/api/health
```

业务请求通常经统一后端转发；直接请求除公开健康接口外需要与平台一致的认证信息。

---

## 配置说明

### 关键参数速查

| 参数 | 位置 | 说明 | 默认值 |
|------|------|------|--------|
| `source_cam1~3` | video | 摄像头 RTSP 地址 | — |
| `process_every_n_frames` | video | 每隔 N 帧推理一次 | 3 |
| `detector_conf` | models | 检测置信度阈值 | 0.35 |
| `uniform_cls_conf` | models | 制服识别置信度阈值 | 0.80 |
| `absent_alarm_seconds` | rules | 离岗报警时长阈值（秒） | 60 |
| `phone_seconds` | rules | 手机持续时长阈值（秒） | 300 |
| `prone_sleep_seconds` | rules | 趴睡持续时长阈值（秒） | 300 |
| `alarm_cooldown_absent` | rules | 离岗报警冷却（秒） | 120 |
| `phone_detect_mode` | runtime | `guard_crop`（生产）/ `full_frame_test`（调试） | guard_crop |
| `AUTH_SECRET` | 环境变量 | JWT 签名密钥（生产必须设置） | 开发默认值 |
| `AUTH_DEFAULT_PASSWORD` | 环境变量 | 登录密码 | `Fuda@2026` |

### 环境变量

```bash
export AUTH_SECRET="your-strong-random-secret-32chars+"
export AUTH_DEFAULT_PASSWORD="your-password"
# 默认长期登录；如需固定过期时间，再设置 AUTH_TOKEN_EXPIRE_HOURS=12
export AUTH_USERS_DB="/path/to/runtime/auth/auth_users.db"
export AUTH_CORS_ORIGINS="https://your-frontend.com"
```

---

## API 接口

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/auth/login` | 公开 | 登录，返回 JWT |
| GET | `/api/auth/me` | 登录 | 当前用户信息 |
| POST | `/api/auth/logout` | 公开 | 登出，清除 Cookie |
| GET | `/api/health` | 公开 | 健康检查 |
| GET | `/api/status` | 登录 | 系统运行状态 |
| GET | `/api/config` | 登录 | 获取当前配置 |
| POST | `/api/config` | admin | 更新配置（热更新，部分需重启生效） |
| POST | `/api/control/start` | admin | 启动检测 |
| POST | `/api/control/stop` | admin | 停止检测 |
| POST | `/api/control/restart` | admin | 重启检测 |
| GET | `/api/recording/status` | 登录 | 录制状态 |
| POST | `/api/recording/start` | admin | 开始手动录制 |
| POST | `/api/recording/stop` | admin | 停止手动录制 |
| GET | `/api/alarms` | 登录 | 报警列表（`?limit=50`） |
| GET | `/api/alarms/{id}/image` | 登录 | 报警截图 |
| GET | `/api/alarms/{id}/video` | 登录 | 报警视频 |
| GET | `/api/statistics` | 登录 | 统计图表数据 |
| GET | `/api/frame.jpg` | 登录 | 最新帧快照 |
| GET | `/api/stream.mjpg` | 登录 | MJPEG 实时推流 |

---

## 输出目录结构

```
outputs/
├── alarm_events.json        # 全量报警事件记录（每次变更后全量覆写）
├── alarms/                  # 报警触发瞬间的 JPEG 快照
│   └── phone_use_5_123_20250101_120000.jpg
├── alarm_clips/             # 报警触发后录制的 MP4 视频片段
│   └── phone_use_5_20250101_120000.mp4
├── records/                 # 手动录制的视频
│   └── manual_record_20250101_120000.mp4
└── annotated.mp4            # 标注视频（save_annotated_video=true 时生成）
```
