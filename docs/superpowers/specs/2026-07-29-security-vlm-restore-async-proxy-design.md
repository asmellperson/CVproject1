# 四事业部安检恢复与高并发代理设计

## 目标

在保留 V4 中 AiVision 摄像头 `ffprobe` 探测修复的前提下，完整恢复安检流程规范检测的四事业部隔离能力，并修复统一后端同步代理阻塞事件循环的问题。

性能验收目标为 50 个终端同时以当前 5fps 查看实时画面，即约 250 个图片请求/秒；压测时统一后端健康接口 P95 小于 200ms，画面请求不触发前端 5 秒超时。

## 基线与历史恢复

实施基线固定为 V4 提交 `5f8bd13`，其中包含：

- `AiVision/platform/camera/probe.py`
- `AiVision/platform/camera/runtime.py`
- `AiVision/tests/test_camera_probe.py`

四事业部安检功能位于从 `206ac98` 到 `1282972` 的连续 17 个提交中。这些提交与 V4 摄像头修复从共同祖先 `4aab013` 分叉，涉及的生产文件互不重叠，因此按原顺序合入完整提交链，不从旧版本整树覆盖。

恢复后的事业部为：

- 通用电气：`general_electric`
- 电子电工：`electronics_electrician`
- 电气部件：`electrical_components`
- 贵金属回收：`precious_metal_recycling`

四个事业部复用页面、模型、规则和服务进程，但独立管理摄像头、RTSP 凭据、ROI、运行状态、历史、告警和统计。通用电气旧数据通过既有幂等迁移进入对应工作区，另外三个事业部初始为空。

## 异步代理架构

统一后端增加一个职责单一的异步上游客户端模块。FastAPI 生命周期内只创建一个共享 `httpx.AsyncClient`，所有代理路由复用连接池。

```text
浏览器
  -> 统一后端认证与事业部权限
  -> AsyncProxyClient
  -> AiVision / Guard Room / Security VLM
  -> StreamingResponse
```

代理不得把完整图片或视频缓冲到内存后再返回。上游响应通过异步迭代器流式转发；浏览器断开时关闭上游响应，使取消能够沿调用链传播。

默认连接参数由环境变量控制：

- `UNIFIED_PROXY_MAX_CONNECTIONS=512`
- `UNIFIED_PROXY_MAX_KEEPALIVE_CONNECTIONS=128`
- `UNIFIED_PROXY_CONNECT_TIMEOUT_SECONDS=3`
- `UNIFIED_PROXY_POOL_TIMEOUT_SECONDS=2`
- `UNIFIED_PROXY_WRITE_TIMEOUT_SECONDS=10`
- `UNIFIED_PROXY_READ_TIMEOUT_SECONDS=10`

读取超时是连续数据块之间的等待上限，不限制正常持续输出的视频总时长。

## 错误处理

- DNS、拒绝连接和其他上游连接错误返回 `502`。
- 连接池等待、读写或连接超时返回 `504`。
- 上游的正常 HTTP 状态码和业务响应体原样转发。
- 过滤 `connection`、`transfer-encoding`、`content-length` 和已经解码的 `content-encoding`，由下游重新生成正确传输头。
- 代理客户端在应用关闭时显式关闭。
- 不通过增加 Uvicorn 多进程规避阻塞，避免内存运行状态在进程间分裂。

## 测试与验收

测试按 TDD 执行：

1. 先构造慢上游并证明旧同步代理会阻塞事件循环。
2. 验证 50 个并发慢代理请求存在时，事件循环探针和健康请求仍可在 200ms 内完成。
3. 验证连接错误映射到 `502`，超时映射到 `504`。
4. 验证响应体流式转发和响应头过滤。
5. 运行历史四事业部 Security VLM、统一后端权限、前端权限测试。
6. 运行 AiVision 摄像头探测测试，证明 V4 修复仍保留。
7. 运行前端测试和生产构建。

生产服务器升级后重复现场采样。50 个终端同时查看时，统一后端 `/api/health` P95 应小于 200ms，AiVision 直连与统一后端不再出现秒级分层差异，浏览器不出现 `frame.jpg` 5 秒超时。

## 风险与边界

- 新增 `httpx` 是为获得真正的异步连接池、流式响应和取消传播；线程池包装 `requests` 不满足 250 请求/秒目标。
- 实际画面带宽仍取决于 JPEG 大小和网络出口；本次消除服务端事件循环串行瓶颈，不改变当前 5fps。
- 首次启动会执行既有事业部数据迁移。部署前应备份 Security VLM 的数据与运行目录，迁移逻辑本身保持幂等和原子写入。
- 不修改现有模型、提示词、检测阈值和 AiVision 摄像头探测逻辑。
