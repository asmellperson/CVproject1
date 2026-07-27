# Security VLM Multi-Camera Design

## 1. Goal and scope

Extend the security-inspection module from one configured RTSP source to
2–4 independently managed cameras.

Confirmed requirements:

- Administrators add cameras inside the security module by entering a camera
  name and RTSP URL.
- Each camera runs the current security workflow independently:
  capture, person detection/tracking, multiple ROIs, multiple ROI sessions,
  keyframe collection, and VLM judgement.
- The current session rule remains unchanged: each ROI owns its current
  `RoiState` and may have one active session, while different ROIs on the same
  camera may have sessions concurrently.
- Each camera can be started, stopped, and restarted independently.
- Global start-all and stop-all controls remain available.
- The frontend provides a camera status bar, a primary single-camera view, and
  an optional two-camera side-by-side view.
- ROI editing always uses a single selected camera.

This design targets 2–4 concurrent cameras. Shared/batched YOLO inference is
explicitly deferred until measured GPU usage shows it is necessary.

## 2. Architecture decision

Use a hybrid process topology:

```text
Security VLM API
├── CameraRegistry
├── CameraRuntimeManager
│   ├── camera_1: capture + detector + session
│   ├── camera_2: capture + detector + session
│   └── camera_3: capture + detector + session
└── one global VLM worker
```

Each camera receives an isolated capture/detector/session process group. This
preserves the current `YOLO.track(..., persist=True)` behavior and prevents one
camera's tracker or session state from leaking into another camera.

The VLM worker is global because budget, API concurrency, history, and task
claiming must remain globally coordinated. Starting the first camera starts the
global VLM worker. Stopping the final camera puts it into drain mode: finalized
pending and in-flight tasks are handled before the process exits.

The first implementation may load one YOLO model per active camera. For 2–4
cameras this is the lower-risk choice. GPU memory and per-camera inference FPS
must be exposed in health data so a later shared detector can be justified by
measurements rather than added pre-emptively.

## 3. Persistent camera registry

Store the registry at:

```text
security_vlm/data/config/cameras.json
```

The path is configurable through:

```yaml
data:
  camera_registry_path: data/config/cameras.json
```

Camera records use stable IDs:

```json
{
  "camera_id": "uuid",
  "name": "安检工位一号",
  "rtsp_url": "rtsp://...",
  "created_at": 0.0,
  "updated_at": 0.0
}
```

Rules:

- `camera_id` is generated once and never changes.
- Camera names are trimmed, non-empty, and unique case-insensitively.
- RTSP URLs must use `rtsp://` or `rtsps://`.
- Registry updates use an in-process lock and atomic file replacement.
- Registry files are created with owner-only permissions where the platform
  supports it.
- API responses and logs never expose the stored password.
- An edit request with an empty RTSP field keeps the current URL.
- Changing RTSP while a camera is running returns HTTP 409; the user must stop
  it first. Renaming a running camera is allowed and updates display metadata.
- A running camera cannot be deleted.
- Deleting a camera removes only its registry entry. ROI, result, and history
  files remain for audit. Permanent data deletion is a separate future action.

### RTSP connection test

`POST /api/cameras/test` accepts a candidate RTSP URL and runs `ffprobe` over
TCP with a bounded timeout. It returns connectivity, codec, width, height, and
a sanitized error. A failed test warns the user but does not prevent saving an
offline camera.

## 4. Runtime namespacing

Every camera receives its own runtime root:

```text
/dev/shm/security_vlm_runtime/
├── cameras/
│   ├── <camera_id>/
│   │   ├── frame_meta.json
│   │   ├── frame_slot_0.bin
│   │   ├── frame_slot_1.bin
│   │   ├── capture_status.json
│   │   ├── tracker_latest.json
│   │   ├── tracker_status.json
│   │   ├── session_latest.json
│   │   └── pending/
│   └── <camera_id>/
│       └── ...
└── global/
    ├── vlm_status.json
    ├── vlm_history.json
    ├── vlm_latest_stats.json
    ├── budget.json
    └── processing/
```

No worker may read or write an unqualified legacy runtime key after migration.
Every session task and result carries `camera_id`, `camera_name`, `roi_name`,
and `session_id`.

Camera-group cleanup and restart may remove FrameHub and latest-status files,
but must preserve that camera's `pending` directory.

ROI files use:

```text
data/annotations/staff_rois/<camera_id>_staff_rois.json
```

Changing a camera name therefore does not move or lose its ROI configuration.

## 5. Runtime lifecycle and recovery

`CameraRuntimeManager` owns:

- a thread-safe `camera_id -> CameraRuntime` map;
- process handles for capture, detector, and session;
- desired state (`running` or `stopped`);
- observed health and restart counters;
- the single global VLM process handle.

### Start one camera

1. Resolve the camera record and reject unknown IDs.
2. Create/clean only that camera's volatile runtime directory.
3. Start capture and wait for a healthy first-frame status.
4. Start detector and wait for tracker readiness.
5. Start session and expose the camera as running.
6. Start the global VLM worker if it is not already running.

If any stage fails, already started processes for that camera are stopped and
the API returns the failing stage without changing other cameras.

### Stop one camera

Stop session, detector, and capture in reverse order. An unfinished active
session is discarded because it does not contain a complete inspection.
Already finalized tasks remain eligible for global VLM processing.

When no camera remains running, the manager requests VLM drain mode. The worker
claims no tasks created after the drain snapshot, finishes all finalized
pending and in-flight tasks in that snapshot, then exits. If the process cannot
finish within the configured graceful-shutdown timeout, unclaimed tasks remain
on disk for the next start.

### Start-all and stop-all

Global operations iterate over cameras and return an itemized result:

```json
{
  "results": [
    {"camera_id": "...", "success": true},
    {"camera_id": "...", "success": false, "message": "..."}
  ]
}
```

One failure does not abort operations for the other cameras.

### Unexpected exits

If capture, detector, or session exits while desired state is `running`, the
manager restarts that camera's complete process group using delays of
1, 2, 5, 10, then 30 seconds. A user stop cancels pending restart attempts.

FFmpeg retains its existing short RTSP reconnect loop. A changed resolution
causes the camera group to rebuild its FrameHub before detector and session are
restarted.

## 6. Global VLM scheduling

Each session worker atomically publishes finalized tasks into its own pending
directory. The envelope contains all camera identity fields, so it remains
self-describing even if the camera is later renamed or deleted.

The global VLM worker:

1. Discovers pending queues under `runtime/cameras/*/pending`.
2. Selects tasks round-robin by camera.
3. Atomically moves a task into `global/processing` before calling the API.
4. Enforces the existing global `max_concurrent`, queue timeout, and daily
   budget.
5. Writes camera-scoped latest state and appends one global history record.
6. On recoverable failure, returns the task to its camera queue with bounded
   retry metadata; on terminal failure, records an error result exactly once.

Task filenames include camera ID and session ID. Result identity never depends
only on filenames.

## 7. HTTP API

### Camera management

```text
GET    /api/cameras
POST   /api/cameras
PUT    /api/cameras/{camera_id}
DELETE /api/cameras/{camera_id}
POST   /api/cameras/test
```

List/detail responses contain a redacted RTSP display value and a boolean
`has_rtsp_url`, never the stored secret.

### Runtime control

```text
POST /api/cameras/{camera_id}/control/start
POST /api/cameras/{camera_id}/control/stop
POST /api/cameras/{camera_id}/control/restart
POST /api/cameras/control/start-all
POST /api/cameras/control/stop-all
```

### Camera-scoped ROI and video

```text
GET  /api/cameras/{camera_id}/rois
POST /api/cameras/{camera_id}/rois
GET  /video/{camera_id}/original
GET  /video/{camera_id}/rule
```

### Health and history

`GET /health` returns global VLM/budget state plus a compact status entry for
every registered camera. History records accept an optional `camera_id`
filter and always include camera identity.

All modifying endpoints retain the unified frontend's existing administrator
authorization boundary.

## 8. Frontend interaction

### Header controls

The security module header contains:

```text
[全部开启] [全部停止] [添加摄像头] [单画面 | 双画面]
```

Viewer accounts see status and view controls but not mutation controls.

### Camera status bar

For 2–4 cameras, render horizontally scrollable status cards rather than a
dropdown. Each card shows:

- camera name;
- running/stopped/offline/error state;
- ROI person total;
- active session count;
- detector FPS;
- per-camera start, stop, restart, edit, and delete actions.

The selected card controls the primary view. Active sessions highlight the
card orange; errors highlight it red. Cards are never video thumbnails and do
not open extra MJPEG streams. An active camera is highlighted but does not
force navigation.

### Single-camera mode

This is the default. It shows one large rule video plus the selected camera's
ROI state, active sessions, latest result, FPS, and errors.

### Two-camera mode

Desktop layout uses two independent 16:9 panels side by side. Each panel has
its own selector, and the same camera cannot occupy both panels. Narrow
screens stack the panels vertically.

Each panel opens its own MJPEG request. A failed stream therefore does not
block the other panel. Switching back to single mode closes the second stream.

### ROI editing

Entering the ROI tab forces single-camera mode and uses the selected camera's
original stream and camera-scoped ROI endpoint. Switching cameras with unsaved
ROI edits requires confirmation.

### Camera editor

The add/edit dialog provides name, RTSP input, connection test, save, and
sanitized diagnostic output. Editing leaves the RTSP field blank unless the
administrator intentionally replaces it.

### History

History adds a camera column and an all-cameras/single-camera filter. Existing
ROI and compliance filters operate after the camera filter.

## 9. Backward-compatible migration

On first startup after upgrade:

- If `cameras.json` already exists, no legacy migration runs.
- If no registry exists and legacy `data.input_video` is non-empty, create a
  deterministic `legacy-default` camera named `默认安检摄像头`.
- Copy, rather than delete, the legacy
  `<legacy data.video_id>_staff_rois.json` (default `stream_staff_rois.json`) to
  `legacy-default_staff_rois.json`.
- Existing history entries without camera identity display under
  `legacy-default` without rewriting original audit files.
- Legacy `/video/original`, `/video/rule`, and `/api/rois` routes temporarily
  resolve to `legacy-default` for one release and emit deprecation logs.

Migration is idempotent and writes a timestamped backup before creating the
registry.

## 10. Error handling and security

- RTSP credentials are redacted in API output, logs, exceptions, health data,
  and connection-test results.
- Camera-level failures never change another camera's desired state.
- Unknown/deleted camera IDs return 404.
- Invalid lifecycle transitions are idempotent where safe: starting an already
  running camera and stopping an already stopped camera return current state.
- Registry write failures leave the previous file intact.
- Stream endpoints return a camera-specific offline placeholder/status rather
  than another camera's last frame.
- Destructive data removal is not included in this change.

## 11. Verification strategy

### Unit tests

- Registry CRUD, validation, masking, atomic persistence, and migration.
- Runtime manager start/stop/restart ordering and partial start-all failure.
- Camera-specific runtime path construction and cross-camera isolation.
- VLM round-robin task selection and exactly-once claim behavior.
- API authorization, response schemas, and lifecycle errors.
- Frontend camera selection, distinct dual selections, unsaved ROI guard, and
  stream cleanup.

### Integration tests

- Run two synthetic FFmpeg videos with distinct dimensions/colors.
- Confirm FrameHub, tracker, ROI, session, and latest-result files cannot cross
  camera IDs.
- Stop or corrupt one input and confirm the other remains healthy.
- Rename a camera and confirm ROI/history still resolve through its stable ID.
- Queue simultaneous sessions from two cameras and confirm fair VLM selection.
- Verify only one or two MJPEG requests exist in single/two-camera modes.

### Production acceptance

- Add each of the 2–4 site cameras through the UI and test RTSP connectivity.
- Draw and save multiple ROIs for every camera.
- Run simultaneous inspections on at least two cameras.
- Verify camera-specific histories, global budget accounting, and independent
  stop/restart behavior.
- Measure GPU memory and per-camera detector FPS before deciding whether
  shared detector batching is needed.

## 12. Explicit non-goals

- More than four optimized concurrent cameras.
- Shared/batched YOLO or tracker implementation.
- Cross-camera person re-identification.
- Automatic camera discovery.
- Automatic switching of the primary frontend view.
- Permanent deletion of camera audit data.
- Changes to the current inspection/VLM judgement semantics.
