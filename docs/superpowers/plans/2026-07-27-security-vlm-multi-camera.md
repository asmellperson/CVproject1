# Security VLM Multi-Camera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently managed 2–4 camera support to Security VLM while preserving each camera's current capture, tracking, multi-ROI session, and VLM judgement behavior.

**Architecture:** Persist cameras in a locked atomic JSON registry. Give every running camera an isolated generated worker configuration and capture/detector/session process group, while one global VLM worker scans all camera queues. Expose camera-scoped APIs and update the unified frontend with status cards, single view, optional two-panel view, and camera-scoped ROI editing.

**Tech Stack:** Python 3.10, FastAPI, FFmpeg/ffprobe, NumPy/OpenCV, pytest, React 19, TypeScript, Vite.

---

### Task 1: Persistent camera registry and legacy migration

**Files:**
- Create: `security_vlm/src/camera_registry.py`
- Create: `security_vlm/tests/test_camera_registry.py`
- Modify: `security_vlm/configs/config.example.yaml`

- [ ] **Step 1: Write failing registry tests**

Cover this public contract:

```python
registry = CameraRegistry(path)
camera = registry.create("安检工位一号", "rtsp://user:pass@camera/stream")
assert camera["camera_id"]
assert registry.get(camera["camera_id"])["name"] == "安检工位一号"
assert registry.public(camera)["rtsp_url"] == "rtsp://***:***@camera/stream"
registry.update(camera["camera_id"], name="安检工位一号东")
registry.delete(camera["camera_id"])
```

Tests must also prove:

- empty/duplicate names are rejected;
- non-RTSP URLs are rejected;
- an empty update URL preserves the secret;
- JSON remains valid after concurrent reads/writes;
- `migrate_legacy()` creates deterministic `legacy-default` exactly once and
  copies the old ROI file without deleting it.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m pytest security_vlm/tests/test_camera_registry.py -q
```

Expected: failure because `camera_registry` does not exist.

- [ ] **Step 3: Implement the registry**

Create:

```python
class CameraRegistry:
    def __init__(self, path: Path): ...
    def list(self) -> list[dict]: ...
    def get(self, camera_id: str) -> dict | None: ...
    def create(self, name: str, rtsp_url: str) -> dict: ...
    def update(self, camera_id: str, *, name: str | None, rtsp_url: str | None) -> dict: ...
    def delete(self, camera_id: str) -> dict: ...
    def public(self, camera: dict) -> dict: ...
    def migrate_legacy(self, cfg: dict, staff_dir: Path) -> dict | None: ...
```

Use `threading.RLock`, `uuid.uuid4()`, a temporary sibling file plus
`Path.replace()`, and `chmod(0o600)`. Persist:

```json
{"version": 1, "cameras": []}
```

- [ ] **Step 4: Add the registry path to config**

```yaml
data:
  camera_registry_path: data/config/cameras.json
```

- [ ] **Step 5: Verify GREEN**

Run the focused registry test and the complete Security VLM test suite.

### Task 2: Camera runtime paths and generated worker configuration

**Files:**
- Create: `security_vlm/src/camera_runtime.py`
- Create: `security_vlm/tests/test_camera_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

Prove:

```python
paths = CameraRuntimePaths(base_runtime, "camera-a")
assert paths.runtime_dir == base_runtime / "cameras" / "camera-a"
assert paths.pending_dir == paths.runtime_dir / "pending"
```

And:

```python
snapshot = build_camera_config(base_cfg, camera, paths)
assert snapshot["data"]["input_video"] == camera["rtsp_url"]
assert snapshot["data"]["video_id"] == camera["camera_id"]
assert snapshot["data"]["camera_name"] == camera["name"]
assert snapshot["runtime"]["dir"] == str(paths.runtime_dir)
assert snapshot["session"]["pending_queue_dir"] == str(paths.pending_dir)
```

Assert the generated YAML has owner-only permissions and modifying the snapshot
does not mutate `base_cfg`.

- [ ] **Step 2: Verify RED**

Expected: failure because `camera_runtime` does not exist.

- [ ] **Step 3: Implement paths and snapshot generation**

Create:

```python
@dataclass(frozen=True)
class CameraRuntimePaths:
    base_runtime_dir: Path
    camera_id: str
    @property
    def runtime_dir(self) -> Path: ...
    @property
    def pending_dir(self) -> Path: ...
    @property
    def config_path(self) -> Path: ...

def build_camera_config(base_cfg: dict, camera: dict, paths: CameraRuntimePaths) -> dict: ...
def write_camera_config(snapshot: dict, path: Path) -> None: ...
```

Sanitize `camera_id` before using it as a path component.

- [ ] **Step 4: Verify GREEN**

Run the focused runtime tests and full backend tests.

### Task 3: Per-camera process groups and global VLM lifecycle

**Files:**
- Modify: `security_vlm/src/camera_runtime.py`
- Modify: `security_vlm/tests/test_camera_runtime.py`

- [ ] **Step 1: Write failing process-manager tests**

Inject fake `Popen`, sleep, clock, and readiness callbacks. Test:

- one camera starts capture, detector, then session in order;
- two cameras own different process dictionaries and config paths;
- stopping one camera uses session, detector, capture order and leaves the
  other running;
- VLM starts once when the first camera starts;
- VLM stops after the last camera stops;
- start-all continues after one camera fails and returns per-camera results;
- user stop clears desired state and prevents automatic restart;
- unexpected exit schedules group restart with `1, 2, 5, 10, 30` second
  bounded backoff.

- [ ] **Step 2: Verify RED**

Expected: failures because `CameraRuntimeManager` does not exist.

- [ ] **Step 3: Implement the manager**

Create:

```python
@dataclass
class CameraRuntime:
    camera_id: str
    desired_running: bool = False
    processes: dict[str, subprocess.Popen] = field(default_factory=dict)
    restart_attempts: int = 0
    last_error: str = ""

class CameraRuntimeManager:
    def start(self, camera_id: str) -> dict: ...
    def stop(self, camera_id: str) -> dict: ...
    def restart(self, camera_id: str) -> dict: ...
    def start_all(self) -> dict: ...
    def stop_all(self) -> dict: ...
    def is_running(self, camera_id: str) -> bool: ...
    def status(self, camera_id: str) -> dict: ...
    def shutdown(self) -> None: ...
```

The injected/default process command for camera workers is:

```python
[worker_python, script_path, "--config", generated_camera_config]
```

The global VLM command uses the base config plus:

```text
--camera-root <base_runtime>/cameras
```

- [ ] **Step 4: Verify GREEN**

Run focused manager tests.

### Task 4: Camera identity in sessions and multi-queue global VLM

**Files:**
- Modify: `security_vlm/src/session_worker.py`
- Modify: `security_vlm/src/vlm_worker.py`
- Create: `security_vlm/tests/test_vlm_multicamera.py`
- Modify: `security_vlm/tests/test_vlm_worker.py`

- [ ] **Step 1: Write failing session-envelope tests**

Instantiate `PairSessionManager` with camera identity and finalize a session.
Assert the pickle contains:

```python
{
    "camera_id": "camera-a",
    "camera_name": "工位 A",
    "session_id": "...",
    "roi_name": "security_staff_1",
}
```

- [ ] **Step 2: Write failing fair-scanner tests**

Create two pending directories containing `a1`, `a2`, and `b1`. Assert
`MultiCameraPendingScanner.next_paths()` returns camera order `a, b, a`, claims
each path only once, and ignores files already moved to processing.

- [ ] **Step 3: Verify RED**

Expected: missing camera identity and multi-camera scanner.

- [ ] **Step 4: Implement session identity**

Pass `camera_id` and `camera_name` from the generated config into
`PairSessionManager`; include them in finalized payloads and session IDs.

- [ ] **Step 5: Implement multi-camera VLM scanning**

Add:

```python
class MultiCameraPendingScanner:
    def __init__(self, camera_root: Path, processing_dir: Path): ...
    def discover(self) -> dict[str, deque[Path]]: ...
    def claim_next(self) -> Path | None: ...
```

Claim tasks with atomic `Path.replace()` into `global/processing`. Update result
records, history, filenames, and camera-scoped latest result with
`camera_id/camera_name`. Remove the old startup behavior that deletes every
pre-existing pending item; only queue-timeout expiry may discard a task.

- [ ] **Step 6: Verify GREEN**

Run the focused session/VLM tests and full backend suite.

### Task 5: Camera-scoped service methods and FastAPI routes

**Files:**
- Modify: `security_vlm/src/main.py`
- Create: `security_vlm/tests/test_multicamera_api.py`

- [ ] **Step 1: Write failing API tests**

Build the app with a temporary config and injectable registry/runtime manager.
Use FastAPI `TestClient` to cover:

```text
POST/GET/PUT/DELETE /api/cameras
POST /api/cameras/test
POST /api/cameras/{id}/control/start|stop|restart
POST /api/cameras/control/start-all|stop-all
GET/POST /api/cameras/{id}/rois
GET /health
GET /api/history?camera_id=<id>
GET /video/{id}/original|rule
```

Assert list responses redact passwords, running-camera RTSP edits/deletes
return 409, unknown IDs return 404, and health contains isolated camera state.

- [ ] **Step 2: Verify RED**

Expected: 404 responses for new endpoints.

- [ ] **Step 3: Refactor `AppService`**

Replace singleton fields with:

```python
self.registry: CameraRegistry
self.runtime_manager: CameraRuntimeManager
self._frame_hubs: dict[str, FrameHubReader]
self._roi_caches: dict[str, tuple[float, dict]]
```

Add camera-scoped methods:

```python
def camera_runtime_dir(self, camera_id: str) -> Path: ...
def get_frame_hub(self, camera_id: str): ...
def load_rois(self, camera_id: str) -> dict: ...
def save_rois(self, camera_id: str, rois: dict) -> dict: ...
def get_camera_state(self, camera_id: str) -> dict: ...
def get_state(self) -> dict: ...
```

- [ ] **Step 4: Register camera APIs and streams**

Make `_overlay_on_frame(frame, service, camera_id)` and
`_mjpeg(camera_id, kind)` camera-scoped. Keep legacy routes resolving to
`legacy-default` when present.

- [ ] **Step 5: Implement sanitized ffprobe test**

Reuse `probe_video_shape()` and add codec probing with a 10-second timeout.
Never include the submitted URL in error output.

- [ ] **Step 6: Verify GREEN**

Run API tests and complete backend suite.

### Task 6: Backward compatibility and configuration

**Files:**
- Modify: `security_vlm/configs/config.example.yaml`
- Modify: `security_vlm/src/main.py`
- Modify: `security_vlm/readme.md`
- Test: `security_vlm/tests/test_multicamera_api.py`

- [ ] **Step 1: Add failing migration-route tests**

With only legacy `data.input_video`, assert startup creates
`legacy-default`, copies the configured legacy ROI file, and serves legacy
`/api/rois` and `/video/rule` through that camera.

- [ ] **Step 2: Add configuration keys**

```yaml
runtime:
  dir: /dev/shm/security_vlm_runtime
  camera_root: /dev/shm/security_vlm_runtime/cameras
data:
  camera_registry_path: data/config/cameras.json
```

- [ ] **Step 3: Update deployment documentation**

Document FFmpeg/ffprobe requirements, camera CRUD, process count, GPU sizing,
runtime paths, and migration.

- [ ] **Step 4: Verify GREEN**

Run migration/API tests and parse the example YAML.

### Task 7: TypeScript API client

**Files:**
- Modify: `unified_frontend/src/lib/security-vlm.ts`

- [ ] **Step 1: Define camera-aware types**

Add:

```typescript
export type SecurityVlmCamera = {
  camera_id: string
  name: string
  rtsp_url: string
  has_rtsp_url: boolean
  running: boolean
  capture?: SecurityVlmWorkerStatus
  detector?: SecurityVlmWorkerStatus
  session?: SecurityVlmWorkerStatus
}
```

Update health/history types to carry camera identity.

- [ ] **Step 2: Add camera API functions**

Implement typed GET/POST/PUT/DELETE wrappers for camera CRUD, test connection,
per-camera and global controls, camera ROI, history filter, and:

```typescript
securityVlmVideoUrl(cameraId, kind, nonce)
```

- [ ] **Step 3: Verify TypeScript**

Run:

```bash
npm run build
```

Expected at this intermediate checkpoint: errors only in the old
`SecurityVlmSection` call sites, proving the client contract changed.

### Task 8: Status cards, camera editor, and single/two-camera UI

**Files:**
- Create: `unified_frontend/src/components/security-vlm/SecurityCameraBar.tsx`
- Create: `unified_frontend/src/components/security-vlm/SecurityCameraDialog.tsx`
- Create: `unified_frontend/src/components/security-vlm/SecurityVideoPanel.tsx`
- Modify: `unified_frontend/src/sections/SecurityVlmSection.tsx`

- [ ] **Step 1: Build focused presentation components**

`SecurityCameraBar` renders JSON-only cards with selected/running/error/session
states and admin action callbacks.

`SecurityCameraDialog` supports add/edit, masked RTSP semantics, test result,
save, and destructive delete confirmation.

`SecurityVideoPanel` owns exactly one MJPEG `<img>` and camera selector.

- [ ] **Step 2: Refactor section state**

Use:

```typescript
const [selectedCameraId, setSelectedCameraId] = useState('')
const [viewMode, setViewMode] = useState<'single' | 'dual'>('single')
const [secondaryCameraId, setSecondaryCameraId] = useState('')
```

Rules:

- select the first registered camera when selection disappears;
- prevent duplicate primary/secondary selection;
- ROI tab forces single mode;
- camera changes with unsaved ROI call `window.confirm`;
- only the selected one or two panels create MJPEG requests;
- global and per-camera controls refresh health without page reload;
- history adds camera column/filter;
- empty registry shows an add-camera onboarding state.

- [ ] **Step 3: Implement responsive layout**

Use two equal `aspect-video` panels in a desktop two-column grid and one column
below the large breakpoint. Preserve `object-contain`.

- [ ] **Step 4: Verify frontend**

Run:

```bash
npm run build
npm run lint
```

Expected: both exit 0.

### Task 9: Regression and integration verification

**Files:**
- Verify all modified backend/frontend files.

- [ ] **Step 1: Run backend tests**

```bash
python -m pytest security_vlm/tests -q
```

- [ ] **Step 2: Compile backend**

```bash
/root/miniconda3/envs/security_vlm/bin/python -m py_compile \
  security_vlm/src/camera_registry.py \
  security_vlm/src/camera_runtime.py \
  security_vlm/src/main.py \
  security_vlm/src/capture_worker.py \
  security_vlm/src/detector_worker.py \
  security_vlm/src/session_worker.py \
  security_vlm/src/vlm_worker.py
```

- [ ] **Step 3: Run a two-camera synthetic integration**

Generate two short FFmpeg test videos with different dimensions, create two
camera records, start their capture workers against isolated runtime roots,
and assert both FrameHubs publish their own expected shape and frame IDs.

- [ ] **Step 4: Build and lint frontend**

```bash
cd unified_frontend
npm run build
npm run lint
```

- [ ] **Step 5: Inspect scope**

```bash
git diff --check
git status --short
```

Confirm no Guard Room, AiVision inference, authentication, or unrelated
department modules changed.
