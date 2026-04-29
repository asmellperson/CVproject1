# 安检合规 VLM 检测系统

基于 YOLO + ByteTrack + Qwen-VL 的安检工位合规性检测。

## 架构

```
capture_worker  →  detector_worker  →  session_worker  →  vlm_worker
  (RTSP 读流)      (YOLO+Track)       (多 ROI 生命周期)    (Qwen-VL 判定)
       ↓               ↓                    ↓                  ↓
              /dev/shm 共享内存 + JSON 状态文件
                           ↓
                     main.py (FastAPI)
```

## 部署

### 1. 创建 Conda 环境

```bash
conda create -n security_vlm python=3.10 -y
conda activate security_vlm
pip install -r requirements.txt
# 记下 python 路径
which python
```

### 2. 修改配置

编辑 `configs/config.yaml`:

- `project.root`:实际项目路径
- `envs.worker_python`:上一步得到的 python 路径
- `data.input_video`:RTSP 地址
- `vlm.api_key`:阿里云百炼 API Key
- `yolo.device`:`cuda:0` 或 `cpu`

### 3. 启动

```bash
cd <项目根目录>
python src/main.py --config configs/config.yaml
```

或后台:

```bash
nohup python src/main.py --config configs/config.yaml > logs/main.log 2>&1 &
```

访问 `http://服务器IP:8000`

## 目录说明

- `configs/config.yaml` — 总配置
- `src/` — 5 个进程脚本
- `templates/index.html` — 前端
- `data/annotations/staff_rois/` — 前端保存的 ROI 配置
- `results/` — 每个 session 的 JSON 判定结果
- `clips/` — **只保存不合规的**关键帧拼图
- `logs/` — 日志
- `/dev/shm/security_vlm_runtime/` — 运行时共享内存和状态

## 常见问题

- **RTSP 打不开**:用 ffmpeg 先测 `ffmpeg -rtsp_transport tcp -i <url> -t 5 out.mp4`
- **VLM 一直 error**:先单独跑 `demo` 版本验证 API Key
- **合规率异常**:调 `session.min_persons_to_start` 和 `session.start_hold_frames`
- **花费超标**:调低 `budget.daily_limit_yuan`,或增大 `session.min_session_seconds` 过滤短 session