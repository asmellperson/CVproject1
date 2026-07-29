# 四事业部安检恢复与高并发代理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留 V4 摄像头探测修复，完整恢复四事业部安检隔离，并让统一后端在 50 终端 × 5fps 下不再因同步代理阻塞。

**Architecture:** 从 V4 提交 `5f8bd13` 顺序合入历史安检提交链；统一后端新增基于共享 `httpx.AsyncClient` 的异步流式代理模块，由 FastAPI 生命周期创建和关闭。测试先覆盖事件循环响应性、错误映射和流式转发，再运行四事业部、AiVision 与前端回归。

**Tech Stack:** Python 3、FastAPI、HTTPX、pytest、React 19、TypeScript、Vite

---

### Task 1: 恢复四事业部安检提交链

**Files:**
- Restore: `security_vlm/configs/config.example.yaml`
- Restore: `security_vlm/src/department_workspace.py`
- Restore: `security_vlm/src/departments.py`
- Restore: `security_vlm/src/camera_registry.py`
- Restore: `security_vlm/src/camera_runtime.py`
- Restore: `security_vlm/src/main.py`
- Restore: `security_vlm/src/roi_geometry.py`
- Restore: `security_vlm/src/session_worker.py`
- Restore: `security_vlm/src/vlm_worker.py`
- Restore: `security_vlm/tests/*.py`
- Restore: `unified_backend/app.py`
- Restore: `unified_backend/tests/test_guard_room_sites.py`
- Restore: `unified_frontend/src/App.tsx`
- Restore: `unified_frontend/src/auth/permissions.ts`
- Restore: `unified_frontend/src/auth/permissions.test.ts`
- Restore: `unified_frontend/src/components/security-vlm/SecurityVideoPanel.tsx`
- Restore: `unified_frontend/src/lib/nav.ts`
- Restore: `unified_frontend/src/lib/security-vlm.ts`
- Restore: `unified_frontend/src/sections/HomeSection.tsx`
- Restore: `unified_frontend/src/sections/SecurityVlmSection.tsx`

- [ ] **Step 1: 确认 V4 摄像头修复基线**

Run:

```bash
git rev-parse --short HEAD
test -f AiVision/platform/camera/probe.py
```

Expected: HEAD 为 `5f8bd13`，且 `probe.py` 存在。

- [ ] **Step 2: 顺序合入完整历史链**

Run:

```bash
git cherry-pick 206ac98^..1282972
```

Expected: 17 个提交全部应用；不覆盖 `AiVision/platform/camera/probe.py`。

- [ ] **Step 3: 验证恢复后的权限入口**

Run:

```bash
cd unified_frontend
npm test -- --run src/auth/permissions.test.ts
```

Expected: 四事业部权限测试通过。

### Task 2: 为异步代理编写失败测试

**Files:**
- Create: `unified_backend/tests/test_async_proxy.py`
- Create: `unified_backend/proxy.py`

- [ ] **Step 1: 写事件循环响应性失败测试**

测试使用 `httpx.MockTransport` 构造等待 `asyncio.Event` 的慢上游，启动 50 个并发代理请求；在这些请求未完成时执行事件循环探针：

```python
await asyncio.wait_for(asyncio.sleep(0), timeout=0.2)
assert entered_count == 50
```

测试还要验证当前同步 `_proxy` 没有可注入的异步客户端，因此在实现前失败。

- [ ] **Step 2: 写错误映射与头过滤失败测试**

覆盖：

```python
pytest.raises(ProxyTimeoutError)
pytest.raises(ProxyUpstreamError)
assert "content-length" not in filtered_headers
assert body == b"frame-bytes"
```

- [ ] **Step 3: 运行测试并确认 RED**

Run:

```bash
python -m pytest unified_backend/tests/test_async_proxy.py -q
```

Expected: 因 `unified_backend.proxy` 尚不存在而失败。

### Task 3: 实现共享异步代理

**Files:**
- Create: `unified_backend/proxy.py`
- Modify: `unified_backend/app.py`
- Modify: `unified_backend/requirements.txt`
- Test: `unified_backend/tests/test_async_proxy.py`

- [ ] **Step 1: 实现代理配置与客户端**

`unified_backend/proxy.py` 提供：

```python
@dataclass(frozen=True)
class ProxySettings:
    max_connections: int
    max_keepalive_connections: int
    connect_timeout_seconds: float
    pool_timeout_seconds: float
    write_timeout_seconds: float
    read_timeout_seconds: float

class AsyncProxyClient:
    def __init__(self, settings: ProxySettings) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                pool=settings.pool_timeout_seconds,
                write=settings.write_timeout_seconds,
                read=settings.read_timeout_seconds,
            ),
            limits=httpx.Limits(
                max_connections=settings.max_connections,
                max_keepalive_connections=settings.max_keepalive_connections,
            ),
        )

    async def send(
        self,
        method: str,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> httpx.Response:
        upstream_request = self._client.build_request(
            method=method,
            url=url,
            content=body or None,
            headers=headers,
        )
        return await self._client.send(upstream_request, stream=True)

    async def close(self) -> None:
        await self._client.aclose()
```

默认值从 `UNIFIED_PROXY_*` 环境变量读取，使用 `httpx.Limits` 和 `httpx.Timeout` 创建共享客户端。

- [ ] **Step 2: 将 FastAPI 代理接入生命周期**

在 `create_app()` 的 lifespan 中创建 `AsyncProxyClient` 并保存到 `app.state.proxy_client`；所有 `/api/*`、`/security-vlm/*` 和 `/aivision/*` 路由调用同一个异步客户端。

流式返回使用：

```python
StreamingResponse(
    proxy_response.iter_bytes(),
    status_code=proxy_response.status_code,
    headers=proxy_response.headers,
    background=BackgroundTask(proxy_response.close),
)
```

- [ ] **Step 3: 增加依赖**

在 `unified_backend/requirements.txt` 添加：

```text
httpx>=0.27.0,<1.0
```

- [ ] **Step 4: 运行测试并确认 GREEN**

Run:

```bash
python -m pytest unified_backend/tests/test_async_proxy.py -q
python -m pytest unified_backend/tests/test_guard_room_sites.py -q
```

Expected: 全部通过。

### Task 4: 执行四事业部与摄像头回归

**Files:**
- Test: `security_vlm/tests/`
- Test: `AiVision/tests/test_camera_probe.py`
- Test: `unified_frontend/src/auth/permissions.test.ts`

- [ ] **Step 1: 运行 Security VLM 测试**

Run:

```bash
python -m pytest security_vlm/tests -q
```

Expected: 全部通过。

- [ ] **Step 2: 运行 V4 摄像头探测测试**

Run:

```bash
cd AiVision
.venv/bin/python -m pytest tests/test_camera_probe.py -q
```

Expected: 全部通过，证明摄像头修复仍在。

- [ ] **Step 3: 运行前端测试与构建**

Run:

```bash
cd unified_frontend
npm test -- --run
npm run build
```

Expected: 测试和生产构建通过。

### Task 5: 执行 50 终端并发验收

**Files:**
- Test: `unified_backend/tests/test_async_proxy.py`

- [ ] **Step 1: 运行 50 并发代理测试**

Run:

```bash
python -m pytest unified_backend/tests/test_async_proxy.py -q
```

Expected: 50 个并发慢请求进入异步上游后，事件循环探针在 200ms 内完成。

- [ ] **Step 2: 核对改动范围与敏感信息**

Run:

```bash
git status --short
git diff --check
git diff -- unified_backend security_vlm unified_frontend AiVision
```

Expected: 仅包含本次恢复、代理修复、测试和文档；无密码、Token 或完整 RTSP 凭据。

- [ ] **Step 3: 发布 V4**

只暂存本次文件，创建中文提交，执行：

```bash
git tag -f V4 HEAD
git push origin V4 --force
```

Expected: `HEAD`、本地 `V4` 和远程 `refs/tags/V4` 三者一致。
