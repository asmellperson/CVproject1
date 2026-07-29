# AiVision 摄像头探测隔离设计

## 背景

AiVision 在主进程的摄像头 watchdog 线程中使用
`cv2.VideoCapture` 探测 RTSP 视频分辨率。目标服务器上某路不可达摄像头
被周期性重试时，OpenCV 原生扩展 `cv2.abi3.so` 发生 SIGSEGV，导致整个
AiVision API 主进程以退出码 139 终止。Python 异常处理无法捕获原生段错误，
模型 worker 也会因主进程未执行清理逻辑而残留。

## 目标

- 主进程不再加载或调用 OpenCV 的 RTSP 打开逻辑。
- 摄像头探测失败、超时、工具缺失或输出非法时，仅让该摄像头启动失败。
- 保留 watchdog 后续自动重试行为，不影响其他摄像头、模型 worker 和 API。
- 不新增 Python 依赖，复用现有 FFmpeg 工具链中的 `ffprobe`。

## 非目标

- 不调整实际采集进程使用 FFmpeg 拉流和 OpenCV 处理帧的逻辑。
- 不修改 watchdog 的重试间隔、告警策略或摄像头启停语义。
- 不处理目标摄像头本身的网络连通性问题。
- 不重构 AiVision 的进程编排架构。

## 方案比较

### 方案 A：使用 `ffprobe` 子进程（采用）

通过参数数组启动 `ffprobe`，请求第一个视频流的宽高并解析 JSON。子进程异常
不会破坏 Python 主进程，且 FFmpeg 已是实际采集链路的运行依赖。

优点是隔离边界清晰、实现小、无新增依赖；缺点是每次探测会创建一个短生命周期
子进程。

### 方案 B：在 multiprocessing 子进程中继续使用 OpenCV

能够隔离 OpenCV 段错误，但需要额外的进程通信、超时终止和 spawn 生命周期
管理，启动成本与测试复杂度更高，而且仍依赖已知会崩溃的探测后端。

### 方案 C：完全使用数据库中的 `shape`

不再连接 RTSP，启动最快，但数据库配置可能与真实视频源不一致，可能导致共享
内存尺寸和 FFmpeg 输出尺寸错误。

## 组件与数据流

新增 `AiVision/platform/camera/probe.py`，提供单一职责的同步探测函数：

1. 使用参数数组调用 `ffprobe`，不经过 shell，并与实际采集一致地强制使用
   RTSP TCP 传输。
2. 请求第一个视频流的 `width` 和 `height`，输出 JSON。
3. 使用模块级统一超时常量限制外部命令执行时间。
4. 校验进程退出码、JSON 结构以及宽高为正整数。
5. 成功时返回 `(height, width, 3)`；失败时抛出带明确原因的探测异常。

`CameraRuntime._probe_size()` 调用该函数。成功时更新 `height`、`width`、
`channels` 和 `shape`；失败时沿用现有行为，把 `status` 设为 `False` 并记录
`msg`。它不回退到 `cv2.VideoCapture`。

实际采集子进程继续通过 FFmpeg 输出 BGR24 原始帧，并继续使用 OpenCV完成花屏
检测等帧内处理。本次只移除主进程的 RTSP OpenCV 探测风险。

## 错误处理

- `ffprobe` 不存在：报告工具缺失，该摄像头本轮启动失败。
- 命令超时：终止子进程并报告探测超时。
- 非零退出：保留精简后的 stderr 原因，不泄露 RTSP 凭据。
- JSON 无效、无视频流或宽高非法：报告响应无效。
- 所有上述失败均由 `CameraRuntime` 转换为现有的摄像头初始化失败状态；
  watchdog 线程继续运行并按现有间隔重试。

错误信息不得包含完整 RTSP URL，避免用户名和密码进入日志。

## 测试

新增 `AiVision/tests/test_camera_probe.py`，使用受控的 `subprocess.run` 替身
验证边界行为：

- 有效 JSON 返回正确的 BGR shape。
- `ffprobe` 缺失时返回明确失败。
- 超时时返回明确失败。
- 非零退出时清理 stderr 中可能出现的 RTSP 凭据。
- 非法 JSON、缺少视频流和非法宽高均被拒绝。
- `CameraRuntime` 收到探测失败时只标记自身失败，不向主流程抛出异常。

运行最小测试后，再运行 AiVision 全部 pytest 用例与 Python 编译检查。

## 部署与运行验证

代码部署到目标服务器后，单独重启 AiVision。启动清理逻辑会回收上次 SIGSEGV
遗留的 Camera、ModelWorker 和 FFmpeg 进程。验证内容：

- 7862 持续监听且 health 返回 `ok=true`。
- 不可达摄像头继续产生初始化失败告警，但 API 主进程不退出。
- 等待至少两个 watchdog 重试周期后再次检查端口、health 和内核日志。
- `dmesg` 中不再出现 AiVision 主进程位于 `cv2.abi3.so` 的新段错误。

## 风险

- 目标机必须提供 `ffprobe`。若缺失，该摄像头会安全降级为启动失败，不会回退
  到 OpenCV；部署检查需要显式执行 `command -v ffprobe`。
- 部分非标准视频源可能不返回宽高，需要继续保持摄像头离线并记录原因。
- 本地测试可证明错误隔离和解析行为，真实 RTSP 稳定性仍需在目标服务器验证。
