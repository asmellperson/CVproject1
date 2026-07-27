# 安检合规 VLM 检测系统

基于 YOLO + ByteTrack + Qwen-VL 的安检工位合规性检测。

## 架构

每台摄像头拥有独立的 `capture → detector → session` 进程组，所有摄像头共享
一个全局 `vlm_worker`。因此 4 台摄像头运行时共有 13 个 worker 进程，而不是
为每台摄像头重复启动 VLM。

运行数据按摄像头隔离在
`/dev/shm/security_vlm_runtime/cameras/<camera_id>/`，VLM 以轮询顺序公平读取
各摄像头的 `pending/` 队列。摄像头之间的 ROI、跟踪状态和活动会话互不影响，
VLM 并发、每日预算和历史统计仍为全局共享。

## 部署

### 1. 创建 Conda 环境

```bash
conda create -n security_vlm python=3.10 -y
conda activate security_vlm
pip install -r requirements.txt
# 记下 python 路径
which python
ffmpeg -version
ffprobe -version
```

### 2. 修改配置

编辑 `configs/config.yaml`:

- `project.root`:实际项目路径
- `envs.worker_python`:上一步得到的 python 路径
- `data.camera_registry_path`:摄像头注册表（默认 `data/config/cameras.json`）
- `vlm.api_key`:阿里云百炼 API Key
- `yolo.device`:`cuda:0` 或 `cpu`

启动 Web 服务后，在“安检流程规范检测”页面填写“摄像头名称 + RTSP 地址”。
支持 2～4 台现场摄像头，每台可独立开启、关闭或重启，也可全部开启/全部关闭。
新增前可用“测试连接”检查编码格式和分辨率。摄像头注册表和运行配置权限为
`0600`，接口及错误信息只返回脱敏地址。FFmpeg/ffprobe 连接期间，RTSP 地址会
短暂出现在本机进程参数中，因此服务器账号和 `/proc` 访问权限也必须受控。

旧版本只配置了 `data.input_video` 时，首次启动会自动创建 ID 为
`legacy-default` 的摄像头，并复制原 `video_id` 对应的 ROI 文件；旧 API 和
旧视频地址仍可继续使用一个版本。

### 3. 启动

```bash
cd <项目根目录>
python src/main.py --config configs/config.yaml
```

或后台:

```bash
nohup python src/main.py --config configs/config.yaml > logs/main.log 2>&1 &
```

后端启动后由统一前端 `unified_frontend` 访问；直接访问 `http://服务器IP:8000/` 只返回服务信息。
统一后端会阻止 viewer 执行摄像头、ROI 和运行状态写操作。生产环境应同时通过
防火墙或监听地址限制 8000 端口只允许统一后端访问，避免绕过统一鉴权直连 API。

调试时可用命令行临时覆盖端口：

```bash
python src/main.py --config configs/config.yaml --port <调试端口>
```

## 目录说明

- `configs/config.yaml` — 总配置
- `src/` — 5 个进程脚本
- `data/annotations/staff_rois/` — 统一前端保存的 ROI 配置
- `data/config/cameras.json` — 安检模块独立的摄像头注册表
- `results/<camera_id>/` — 每个 session 的 JSON 判定结果
- `clips/<camera_id>/` — **只保存不合规的**关键帧拼图
- `logs/` — 日志
- `/dev/shm/security_vlm_runtime/cameras/<camera_id>/` — 摄像头进程组状态
- `/dev/shm/security_vlm_runtime/global/processing/` — 全局 VLM 已认领任务

## 多摄像头接口

- `GET/POST /api/cameras`：查询或添加摄像头
- `PUT/DELETE /api/cameras/{camera_id}`：修改或删除已停止的摄像头
- `POST /api/cameras/test`：测试 RTSP
- `POST /api/cameras/{camera_id}/control/{start|stop|restart}`：独立控制
- `POST /api/cameras/control/{start-all|stop-all}`：全部控制
- `GET/POST /api/cameras/{camera_id}/rois`：摄像头级 ROI
- `GET /video/{camera_id}/{original|rule}`：摄像头级 MJPEG

2～4 路同时推理会线性增加 YOLO 的 GPU 占用。正式上线前应按实际分辨率同时
开启全部摄像头，观察显存和推理帧率；资源不足时优先降低 `yolo.imgsz` 或摄像头
子码流分辨率，不建议再引入 OpenCV 直接解码 H.265。

## 常见问题

- **RTSP 打不开**:用 ffmpeg 先测 `ffmpeg -rtsp_transport tcp -i <url> -t 5 -an -c:v libx264 -pix_fmt yuv420p out.mp4`
- **VLM 一直 error**:先单独跑 `demo` 版本验证 API Key
- **合规率异常**:调 `session.min_persons_to_start` 和 `session.start_hold_frames`
- **花费超标**:调低 `budget.daily_limit_yuan`,或增大 `session.min_session_seconds` 过滤短 session
