# Security VLM Camera Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify Security VLM camera cards, replace media-style controls with power semantics, and let only administrators load the complete RTSP URL when editing.

**Architecture:** Keep all list and health payloads redacted. Add one camera-scoped credentials endpoint in Security VLM and enforce its administrator-only boundary in the unified backend before proxying. The frontend fetches credentials only when an administrator opens the edit dialog; status cards never render RTSP data.

**Tech Stack:** FastAPI, pytest/httpx, React 19, TypeScript, lucide-react, Vite, ESLint

---

### Task 1: Add the camera credentials endpoint

**Files:**
- Modify: `security_vlm/tests/test_multicamera_api.py`
- Modify: `security_vlm/src/main.py`

- [ ] **Step 1: Write the failing API test**

Extend `test_camera_crud_redaction_and_running_conflicts` after camera creation:

```python
camera_id = created["camera"]["camera_id"]
assert created["camera"]["rtsp_url"] == "rtsp://***:***@camera-a/stream"

credentials_response = await client.get(
    f"/api/cameras/{camera_id}/credentials"
)
assert credentials_response.status_code == 200
assert credentials_response.json()["camera"]["rtsp_url"] == (
    "rtsp://admin:secret@camera-a/stream"
)
assert (await client.get(
    "/api/cameras/missing/credentials"
)).status_code == 404
```

Use `rtsp://admin:secret@camera-a/stream` in the existing create payload so the assertion proves that the ordinary response is redacted while credentials are complete.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m pytest security_vlm/tests/test_multicamera_api.py::test_camera_crud_redaction_and_running_conflicts -q
```

Expected: `404` for the new credentials route because it does not exist.

- [ ] **Step 3: Implement the endpoint**

Add after `get_camera` in `security_vlm/src/main.py`:

```python
@app.get("/api/cameras/{camera_id}/credentials")
async def get_camera_credentials(camera_id: str):
    camera = require_camera(camera_id)
    return JSONResponse({
        "camera": {
            "camera_id": camera["camera_id"],
            "name": camera["name"],
            "rtsp_url": camera["rtsp_url"],
        },
    })
```

Do not change `CameraRegistry.public`; list, health, create, update, and delete responses must remain redacted.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2.

Expected: `1 passed`.

### Task 2: Restrict credentials to administrators in the unified backend

**Files:**
- Modify: `unified_backend/tests/test_guard_room_sites.py`
- Modify: `unified_backend/app.py`

- [ ] **Step 1: Write the failing permission test**

Import `_can_access_security_vlm` and add:

```python
def test_security_vlm_credentials_are_admin_only():
    viewer = {"role": "viewer"}
    admin = {"role": "admin"}
    path = "/security-vlm/api/cameras/camera-a/credentials"

    assert _can_access_security_vlm(viewer, "GET", path) is False
    assert _can_access_security_vlm(admin, "GET", path) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/cameras",
    ) is True
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m pytest unified_backend/tests/test_guard_room_sites.py::test_security_vlm_credentials_are_admin_only -q
```

Expected: import failure because `_can_access_security_vlm` is not defined.

- [ ] **Step 3: Implement path-aware authorization**

Add beside `_can_mutate_security_vlm`:

```python
def _can_access_security_vlm(
    user: dict[str, Any],
    method: str,
    path: str,
) -> bool:
    role = str(user.get("role") or "").strip().lower()
    credentials_path = (
        str(path).startswith("/security-vlm/api/cameras/")
        and str(path).endswith("/credentials")
    )
    if credentials_path:
        return role == "admin"
    return _can_mutate_security_vlm(user, method)
```

Change the middleware condition to call:

```python
and not _can_access_security_vlm(
    request.state.user,
    request.method,
    path,
)
```

Use a response message that covers both mutation and credential access:

```python
{"detail": "仅管理员可以修改安检模块配置或读取摄像头连接信息"}
```

- [ ] **Step 4: Run unified backend tests**

Run:

```bash
python -m pytest unified_backend/tests -q
```

Expected: all tests pass.

### Task 3: Load complete RTSP data only when editing

**Files:**
- Modify: `unified_frontend/src/lib/security-vlm.ts`
- Modify: `unified_frontend/src/sections/SecurityVlmSection.tsx`
- Modify: `unified_frontend/src/components/security-vlm/SecurityCameraDialog.tsx`

- [ ] **Step 1: Add the credentials client**

Add:

```typescript
export type SecurityVlmCameraCredentials = Pick<
  SecurityVlmCamera,
  'camera_id' | 'name' | 'rtsp_url'
>

export const getSecurityVlmCameraCredentials = (cameraId: string) =>
  securityVlmGet<{ camera: SecurityVlmCameraCredentials }>(
    `/api/cameras/${encodeURIComponent(cameraId)}/credentials`,
  )
```

- [ ] **Step 2: Make edit opening asynchronous**

Import `getSecurityVlmCameraCredentials`. Replace `openCameraDialog` with:

```typescript
const openCameraDialog = async (camera: SecurityVlmCamera | null) => {
  if (!camera) {
    setEditingCamera(null)
    setCameraDialogKey((value) => value + 1)
    setCameraDialogOpen(true)
    return
  }

  setBusyCameraId(camera.camera_id)
  try {
    const details = await getSecurityVlmCameraCredentials(camera.camera_id)
    setEditingCamera({ ...camera, ...details.camera })
    setCameraDialogKey((value) => value + 1)
    setCameraDialogOpen(true)
  } catch (error) {
    setControlMessage(
      `摄像头编辑信息读取失败：${
        error instanceof Error ? error.message : String(error)
      }`,
    )
  } finally {
    setBusyCameraId(null)
  }
}
```

Update callbacks:

```tsx
onEdit={(camera) => void openCameraDialog(camera)}
onAdd={() => void openCameraDialog(null)}
```

- [ ] **Step 3: Populate and reveal the RTSP input**

In `SecurityCameraDialog`:

```typescript
const [rtspUrl, setRtspUrl] = useState(camera?.rtsp_url || '')
const [message, setMessage] = useState('')
```

Change the input to:

```tsx
<Input
  id="security-camera-rtsp"
  type="text"
  autoComplete="off"
  value={rtspUrl}
  onChange={(event) => setRtspUrl(event.target.value)}
  placeholder="rtsp://用户名:密码@地址/stream"
/>
```

Keep the existing save and connection-test validation.

### Task 4: Simplify cards and use power semantics

**Files:**
- Modify: `unified_frontend/src/components/security-vlm/SecurityCameraBar.tsx`
- Modify: `unified_frontend/src/sections/SecurityVlmSection.tsx`

- [ ] **Step 1: Simplify each camera card**

In `SecurityCameraBar`:

- remove the RTSP `<p>` element;
- replace `Play`, `Square`, and `RefreshCw` imports with `Power`, `PowerOff`, and `RotateCw`;
- render `PowerOff` when `camera.desired_running` is true and `Power` otherwise;
- use titles `关闭摄像头` and `开启摄像头`;
- always render the restart icon, disabling it when `!camera.running`;
- keep the edit icon disabled while the camera is desired-running or busy;
- retain the camera name, status Badge, and `检测与会话处理中` text.

The toggle icon body becomes:

```tsx
{camera.desired_running
  ? <PowerOff className="h-4 w-4" />
  : <Power className="h-4 w-4" />}
```

The restart icon becomes:

```tsx
<RotateCw className="h-4 w-4" />
```

- [ ] **Step 2: Update bulk controls without removing Chinese labels**

In `SecurityVlmSection`, replace bulk `Play`/`Pause` imports and JSX:

```tsx
<Power className="h-4 w-4" />
{controlBusy ? '处理中' : '全部开启'}
```

```tsx
<PowerOff className="h-4 w-4" />
全部关闭
```

Do not change the button labels or click handlers.

- [ ] **Step 3: Build and lint the frontend**

Run:

```bash
cd unified_frontend
npm run build
npm run lint
```

Expected: build succeeds; lint has zero errors. Existing unrelated warnings may remain.

### Task 5: Full verification and publication readiness

**Files:**
- Verify all files modified in Tasks 1–4.

- [ ] **Step 1: Run backend verification**

```bash
python -m compileall -q security_vlm/src security_vlm/tests unified_backend
python -m pytest security_vlm/tests unified_backend/tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Check patch hygiene**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only planned files plus pre-existing unrelated untracked files.

- [ ] **Step 3: Review security behavior**

Confirm from tests and diff:

- health/list responses still call `CameraRegistry.public`;
- only `/api/cameras/{camera_id}/credentials` returns the raw URL;
- unified backend rejects viewer access to credentials;
- camera cards do not render `rtsp_url`;
- the edit dialog receives the raw URL only after an administrator action.
