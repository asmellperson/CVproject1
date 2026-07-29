# Security VLM Department Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将安检流程规范检测复用到四个事业部，按事业部隔离摄像头、ROI、运行状态、历史、告警和统计，并让安检 ROI 同时支持拖拽矩形与逐点多边形。

**Architecture:** 保留单个 `security_vlm` 服务和一套模型规则，新增事业部工作区管理器，为四个事业部分配独立的摄像头注册表、ROI、运行和结果目录。所有运行任务与结果携带 `department + camera_id`，统一后端负责身份校验和告警过滤，前端通过一个带 `department` 属性的 `SecurityVlmSection` 复用页面。

**Tech Stack:** Python 3、FastAPI、Pydantic、pytest、OpenCV/NumPy、React 19、TypeScript、Vite。

---

## 文件结构与职责

新增文件：

- `security_vlm/src/departments.py`：事业部白名单与标准化校验，避免业务模块之间循环导入。
- `security_vlm/src/department_workspace.py`：事业部白名单、路径生成、工作区创建和旧数据迁移。
- `security_vlm/tests/test_department_workspace.py`：目录隔离、空工作区、幂等迁移和损坏数据测试。
- `unified_frontend/src/components/roi/RoiCanvas.tsx`：从 AiVision ROI 编辑器抽出的通用无模式 ROI 画布。

主要修改文件：

- `security_vlm/src/camera_registry.py`：注册表写入事业部元数据，并兼容读取旧版注册表。
- `security_vlm/src/roi_geometry.py`：统一矩形与多边形格式，提供点包含、矩形交叠率和边界框计算。
- `security_vlm/src/session_worker.py`：热加载多边形 ROI，使用多边形成员判定，任务写入事业部标识。
- `security_vlm/src/camera_runtime.py`：按事业部生成运行目录与 worker 配置。
- `security_vlm/src/vlm_worker.py`：按事业部公平扫描任务，并分别写历史、统计和结果。
- `security_vlm/src/main.py`：事业部工作区业务门面和事业部作用域 API。
- `security_vlm/configs/config.example.yaml`：事业部数据根目录、运行根目录、并发和公平调度配置。
- `unified_backend/app.py`：接口权限、事业部告警采集与过滤。
- `unified_frontend/src/lib/security-vlm.ts`：事业部作用域 API 和 ROI 顶点类型。
- `unified_frontend/src/sections/SecurityVlmSection.tsx`：接收事业部、清理跨事业部状态并接入通用 ROI 画布。
- `unified_frontend/src/components/AiVisionRoiEditor.tsx`：复用通用 ROI 画布，保持 AiVision 现有行为。
- `unified_frontend/src/App.tsx`、`unified_frontend/src/lib/nav.ts`、`unified_frontend/src/auth/permissions.ts`、`unified_frontend/src/sections/HomeSection.tsx`：四个事业部入口与权限。

不新增第三方依赖。

### Task 1: 建立事业部工作区与幂等迁移

**Files:**

- Create: `security_vlm/src/departments.py`
- Create: `security_vlm/src/department_workspace.py`
- Create: `security_vlm/tests/test_department_workspace.py`
- Modify: `security_vlm/src/camera_registry.py`
- Modify: `security_vlm/configs/config.example.yaml`
- Modify: `security_vlm/tests/test_camera_registry.py`

- [ ] **Step 1: 写工作区隔离和迁移失败测试**

```python
def test_manager_creates_four_isolated_empty_workspaces(tmp_path):
    manager = DepartmentWorkspaceManager(
        data_root=tmp_path / "data" / "departments",
        runtime_root=tmp_path / "runtime" / "departments",
    )

    electronics = manager.get("electronics_electrician")
    components = manager.get("electrical_components")

    assert electronics.registry.list() == []
    assert components.registry.list() == []
    assert electronics.registry.path != components.registry.path
    assert electronics.roi_dir != components.roi_dir
    assert electronics.runtime_dir != components.runtime_dir


def test_legacy_files_migrate_only_to_general_electric_and_are_idempotent(tmp_path):
    legacy_registry = tmp_path / "legacy" / "cameras.json"
    legacy_roi_dir = tmp_path / "legacy" / "rois"
    legacy_runtime = tmp_path / "legacy" / "runtime"
    write_legacy_fixture(legacy_registry, legacy_roi_dir, legacy_runtime)

    manager = make_manager(tmp_path)
    first = manager.migrate_general_electric(
        legacy_registry_path=legacy_registry,
        legacy_roi_dir=legacy_roi_dir,
        legacy_runtime_dir=legacy_runtime,
    )
    second = manager.migrate_general_electric(
        legacy_registry_path=legacy_registry,
        legacy_roi_dir=legacy_roi_dir,
        legacy_runtime_dir=legacy_runtime,
    )

    assert first.migrated is True
    assert second.migrated is False
    assert len(manager.get("general_electric").registry.list()) == 1
    assert manager.get("electronics_electrician").registry.list() == []
    assert legacy_registry.exists()
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run:

```bash
cd security_vlm && pytest -q tests/test_department_workspace.py
```

Expected: `FAIL`，错误包含 `ModuleNotFoundError: No module named 'department_workspace'`。

- [ ] **Step 3: 实现事业部常量、目录和值对象**

在 `departments.py` 中定义固定白名单和 `require_department()`；`camera_registry.py` 和 `department_workspace.py` 都只依赖该模块，禁止互相导入。然后在 `department_workspace.py` 中定义路径对象：

```python
SECURITY_DEPARTMENTS = (
    "general_electric",
    "electronics_electrician",
    "electrical_components",
    "precious_metal_recycling",
)


def require_department(value: str) -> str:
    department = str(value or "").strip()
    if department not in SECURITY_DEPARTMENTS:
        raise ValueError(f"不支持的事业部: {department or '<empty>'}")
    return department


@dataclass(frozen=True)
class DepartmentWorkspace:
    department: str
    data_dir: Path
    runtime_dir: Path
    registry: CameraRegistry

    @property
    def roi_dir(self) -> Path:
        return self.data_dir / "rois"

    @property
    def camera_runtime_dir(self) -> Path:
        return self.runtime_dir / "cameras"

    @property
    def result_store(self) -> ResultStore:
        return ResultStore(self.runtime_dir)
```

`DepartmentWorkspaceManager.get()` 必须调用 `require_department()`，创建事业部自己的 `cameras.json`、`rois/` 和运行目录。迁移使用 `.migration-v2.json` 完成标记，先复制到临时目录、校验 JSON 后再原子替换；保留旧文件。

增加损坏隔离测试：破坏 `general_electric/cameras.json` 后，读取该工作区抛出明确错误，但 `electronics_electrician` 仍可创建和读取摄像头。

旧数据迁移只迁移持久数据：摄像头注册表、每摄像头 ROI、`vlm_state.json`、`vlm_history.json`、`vlm_latest_stats.json` 和 `vlm_budget.json`。旧 `/dev/shm` 中的进程心跳、共享帧和临时 pending 文件不迁移，升级后所有摄像头保持停止状态。

- [ ] **Step 4: 升级摄像头注册表格式**

将 `CameraRegistry` 构造函数改为：

```python
def __init__(self, path: Path, *, department: str):
    self.path = Path(path)
    self.department = require_department(department)
    self._lock = threading.RLock()
```

新文件写入：

```python
{
    "version": 2,
    "department": self.department,
    "cameras": cameras,
}
```

读取 `version == 1` 时只允许迁移器把它归入 `general_electric`；读取 `version == 2` 时校验文件内 `department` 与当前工作区一致，不一致时抛出 `RuntimeError`，不得返回空列表。

- [ ] **Step 5: 增加可配置根目录并运行测试**

在 `config.example.yaml` 中增加：

```yaml
departments:
  data_root: data/departments
  runtime_root: /dev/shm/security_vlm_runtime/departments
  max_cameras_per_department: 4
```

Run:

```bash
cd security_vlm && pytest -q tests/test_department_workspace.py tests/test_camera_registry.py
```

Expected: 全部通过，且旧注册表迁移测试仍保留旧源文件。

- [ ] **Step 6: 提交工作区基础**

```bash
git add security_vlm/src/departments.py security_vlm/src/department_workspace.py security_vlm/src/camera_registry.py security_vlm/configs/config.example.yaml security_vlm/tests/test_department_workspace.py security_vlm/tests/test_camera_registry.py
git commit -m "feat: add isolated security department workspaces"
```

### Task 2: 支持矩形与多边形 ROI 数据和几何判定

**Files:**

- Modify: `security_vlm/src/roi_geometry.py`
- Modify: `security_vlm/src/session_worker.py`
- Modify: `security_vlm/src/main.py`
- Modify: `security_vlm/configs/config.example.yaml`
- Modify: `security_vlm/tests/test_roi_membership.py`
- Modify: `security_vlm/tests/test_multicamera_api.py`

- [ ] **Step 1: 写旧矩形兼容与多边形成员判定测试**

```python
def test_normalize_roi_converts_legacy_rect_to_points():
    assert normalize_roi_points([10, 20, 50, 80]) == [
        [10.0, 20.0],
        [50.0, 20.0],
        [50.0, 80.0],
        [10.0, 80.0],
    ]


def test_bbox_belongs_to_polygon_by_center_or_overlap():
    polygon = [[0, 0], [100, 0], [80, 100], [20, 100]]

    assert bbox_belongs_to_roi([40, 20, 60, 80], polygon, 0.30) is True
    assert bbox_belongs_to_roi([75, 20, 125, 80], polygon, 0.20) is True
    assert bbox_belongs_to_roi([120, 20, 180, 80], polygon, 0.10) is False


def test_invalid_polygon_is_rejected():
    with pytest.raises(ValueError, match="至少 3 个顶点"):
        normalize_roi_points([[1, 2], [3, 4]])


def test_validate_rois_rejects_out_of_bounds_and_small_polygons():
    with pytest.raises(ValueError, match="超出画面"):
        validate_rois(
            {"越界": [[-1, 0], [100, 0], [100, 100]]},
            width=1920,
            height=1080,
            min_area=2500,
        )
    with pytest.raises(ValueError, match="面积过小"):
        validate_rois(
            {"过小": [[0, 0], [10, 0], [10, 10]]},
            width=1920,
            height=1080,
            min_area=2500,
        )
```

- [ ] **Step 2: 运行测试并确认现有矩形实现失败**

Run:

```bash
cd security_vlm && pytest -q tests/test_roi_membership.py
```

Expected: `FAIL`，缺少 `normalize_roi_points`，现有 `_normalize_rect` 无法处理嵌套顶点。

- [ ] **Step 3: 实现无依赖多边形几何**

在 `roi_geometry.py` 中实现并导出：

```python
Point = tuple[float, float]


def normalize_roi_points(values) -> list[list[float]]:
    if isinstance(values, Sequence) and len(values) >= 4 and all(
        isinstance(value, (int, float)) for value in values[:4]
    ):
        x1, y1, x2, y2 = _normalize_rect(values)
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    points = []
    for value in values if isinstance(values, Sequence) else []:
        if not isinstance(value, Sequence) or len(value) < 2:
            raise ValueError("ROI 顶点格式无效")
        point = [float(value[0]), float(value[1])]
        if not all(math.isfinite(item) for item in point):
            raise ValueError("ROI 顶点必须是有限数值")
        points.append(point)
    if len(points) < 3:
        raise ValueError("ROI 至少 3 个顶点")
    return points


def roi_bounds(points) -> list[float]:
    normalized = normalize_roi_points(points)
    xs = [point[0] for point in normalized]
    ys = [point[1] for point in normalized]
    return [min(xs), min(ys), max(xs), max(ys)]
```

使用射线法实现 `point_in_polygon()`，使用 Sutherland–Hodgman 算法把任意简单多边形依次裁剪到人体矩形四条边，再用鞋带公式计算交叠面积。`bbox_belongs_to_roi()` 保持原语义：人体中心在多边形内，或者人体框与多边形交叠面积占人体框面积达到阈值。

实现 `validate_rois(rois, width, height, min_area)`：逐个调用 `normalize_roi_points()`，拒绝空名称、少于 3 点、非有限数值、越界和面积不足；返回标准化顶点字典。

- [ ] **Step 4: 更新 session worker 的加载与任务格式**

把热加载中的 `v[:4]` 改为：

```python
roi_cache = {
    name: normalize_roi_points(value)
    for name, value in rois.items()
}
```

创建 `PairSession` 时继续把送给裁图/VLM 的 `roi_box` 保存为外接矩形：

```python
roi_box=roi_bounds(roi)
```

`session_latest.staff_rois` 保留完整顶点，不退化成外接矩形。

修改 `main.py` 的规则画面叠加：ROI 使用 `cv2.polylines()` 和半透明 `cv2.fillPoly()` 绘制；人体归属继续调用同一个 `bbox_belongs_to_roi()`，不能在叠加层保留矩形专用判断。

- [ ] **Step 5: 更新 API ROI 校验测试并运行**

测试保存内容：

```python
payload = {
    "staff_rois": {
        "工位 1": [[10, 20], [80, 10], [95, 70], [30, 90]],
        "旧矩形": [100, 100, 300, 400],
    }
}
response = await client.post(
    f"/api/departments/general_electric/cameras/{camera_id}/rois",
    json=payload,
)
assert response.json()["staff_rois"]["旧矩形"] == [
    [100.0, 100.0], [300.0, 100.0], [300.0, 400.0], [100.0, 400.0]
]
```

API 保存时从摄像头采集状态取得原始画面宽高，使用配置项 `roi.min_area_px` 调用 `validate_rois()`；无法取得尺寸时返回明确的 `409`，要求先连接摄像头，而不是跳过边界校验。

在示例配置中加入：

```yaml
roi:
  min_area_px: 2500
```

Run:

```bash
cd security_vlm && pytest -q tests/test_roi_membership.py tests/test_multicamera_api.py
```

Expected: 全部通过。

- [ ] **Step 6: 提交多边形 ROI 后端支持**

```bash
git add security_vlm/src/roi_geometry.py security_vlm/src/session_worker.py security_vlm/src/main.py security_vlm/configs/config.example.yaml security_vlm/tests/test_roi_membership.py security_vlm/tests/test_multicamera_api.py
git commit -m "feat: support polygon security rois"
```

### Task 3: 让运行时任务携带事业部并隔离摄像头状态

**Files:**

- Modify: `security_vlm/src/camera_runtime.py`
- Modify: `security_vlm/src/session_worker.py`
- Modify: `security_vlm/configs/config.example.yaml`
- Modify: `security_vlm/tests/test_camera_runtime.py`

- [ ] **Step 1: 写事业部运行目录和配置快照测试**

```python
def test_runtime_paths_include_department(tmp_path):
    paths = CameraRuntimePaths(
        base_runtime_dir=tmp_path,
        department="electronics_electrician",
        camera_id="camera-a",
    )
    assert paths.runtime_dir == (
        tmp_path / "departments" / "electronics_electrician" / "cameras" / "camera-a"
    )


def test_camera_snapshot_contains_department(tmp_path):
    snapshot = build_camera_config(
        base_cfg(),
        {
            "department": "electrical_components",
            "camera_id": "camera-a",
            "name": "A",
            "rtsp_url": "rtsp://camera-a/stream",
        },
        paths_for(tmp_path, "electrical_components", "camera-a"),
    )
    assert snapshot["data"]["department"] == "electrical_components"
    assert snapshot["data"]["video_id"] == "camera-a"


def test_global_running_limit_is_configurable(runtime_manager):
    runtime_manager.max_running_cameras = 1
    assert runtime_manager.start("general_electric", "camera-a")["ok"] is True
    result = runtime_manager.start("electronics_electrician", "camera-b")
    assert result["ok"] is False
    assert "同时运行上限" in result["message"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
cd security_vlm && pytest -q tests/test_camera_runtime.py
```

Expected: `FAIL`，`CameraRuntimePaths` 尚无 `department` 参数。

- [ ] **Step 3: 修改运行时键和值对象**

所有公开运行方法改为 `start(department, camera_id)`、`stop(department, camera_id)`、`restart(department, camera_id)` 和 `status(department, camera_id)`。将运行时字典从 `camera_id` 键改为：

```python
RuntimeKey = tuple[str, str]


def runtime_key(department: str, camera_id: str) -> RuntimeKey:
    return require_department(department), str(camera_id)
```

`CameraRuntime` 增加 `department` 字段；`camera_provider` 签名改为 `Callable[[str], list[dict]]`；`_get_camera()` 必须同时接收事业部和摄像头 ID，禁止扫描其他工作区寻找同 ID 摄像头。

从配置读取全局同时运行上限：

```yaml
runtime:
  max_running_cameras: 16
```

`start()` 在启动新摄像头前统计四个事业部的 `desired_running` 数量；达到配置上限时返回明确失败结果，已经运行的同一摄像头仍保持幂等成功。

`CameraRuntimePaths.runtime_dir` 返回：

```python
self.base_runtime_dir / "departments" / self.department / "cameras" / self.camera_id
```

`build_camera_config()` 写入：

```python
data_cfg["department"] = camera["department"]
data_cfg["video_id"] = camera["camera_id"]
runtime_cfg["department_dir"] = str(paths.department_runtime_dir)
```

`start_all()` 和 `stop_all()` 接收 `department`，只遍历对应工作区摄像头；全局 `shutdown()` 才停止全部事业部。

- [ ] **Step 4: 让 session pending 任务包含事业部**

在 session 任务 payload 中加入：

```python
{
    "department": self.department,
    "camera_id": self.camera_id,
    "camera_name": self.camera_name,
    ...
}
```

缺少 `department` 的旧 pending 文件只允许按 `general_electric` 恢复。

- [ ] **Step 5: 运行运行时回归测试**

Run:

```bash
cd security_vlm && pytest -q tests/test_camera_runtime.py tests/test_capture_worker_ffmpeg.py
```

Expected: 全部通过；测试断言同名摄像头在不同事业部生成不同配置路径。

- [ ] **Step 6: 提交运行时隔离**

```bash
git add security_vlm/src/camera_runtime.py security_vlm/src/session_worker.py security_vlm/configs/config.example.yaml security_vlm/tests/test_camera_runtime.py
git commit -m "feat: scope security runtimes by department"
```

### Task 4: 按事业部公平调度 VLM 并分区结果

**Files:**

- Modify: `security_vlm/src/vlm_worker.py`
- Modify: `security_vlm/tests/test_vlm_multicamera.py`
- Modify: `security_vlm/tests/test_vlm_worker.py`
- Modify: `security_vlm/configs/config.example.yaml`

- [ ] **Step 1: 写轮询公平性与结果分区测试**

```python
def test_department_scanner_round_robins_pending_tasks(tmp_path):
    roots = make_pending_tree(
        tmp_path,
        {
            "general_electric": ["ge-1.pkl", "ge-2.pkl"],
            "electronics_electrician": ["ee-1.pkl"],
        },
    )
    scanner = DepartmentPendingScanner(roots, processing_dir=tmp_path / "processing")

    first_three = [scanner.claim_next().department for _ in range(3)]

    assert first_three[:2] == ["general_electric", "electronics_electrician"]


def test_result_accumulator_writes_only_target_department(tmp_path):
    stores = DepartmentResultStores(tmp_path, SECURITY_DEPARTMENTS)
    accumulator = DepartmentAccumulator(stores)

    accumulator.record({
        "department": "electrical_components",
        "camera_id": "camera-a",
        "status": "non_compliant",
    })

    assert stores.get("electrical_components").read("vlm_history")["items"]
    assert stores.get("general_electric").read("vlm_history", {"items": []})["items"] == []
```

- [ ] **Step 2: 运行测试并确认新类不存在**

Run:

```bash
cd security_vlm && pytest -q tests/test_vlm_multicamera.py tests/test_vlm_worker.py
```

Expected: `FAIL`，缺少 `DepartmentPendingScanner` 和 `DepartmentAccumulator`。

- [ ] **Step 3: 实现公平扫描**

扫描路径固定为：

```text
<runtime_root>/departments/<department>/cameras/<camera_id>/pending/*.pkl
```

`DepartmentPendingScanner` 为每个事业部维护一个待处理队列，并使用 `collections.deque(SECURITY_DEPARTMENTS)` 轮询。单个事业部没有任务时跳过，但不能因为通用电气持续有任务而饿死其他事业部。

任务声明：

```python
@dataclass(frozen=True)
class PendingTask:
    department: str
    camera_id: str
    path: Path
```

- [ ] **Step 4: 实现分事业部累计器**

将全局 `history`、`counts` 和统计写入改为：

```python
accumulators: dict[str, DepartmentAccumulator] = {
    department: DepartmentAccumulator(
        store=ResultStore(runtime_root / "departments" / department),
        max_history=max_history,
    )
    for department in SECURITY_DEPARTMENTS
}
```

`process_one()` 从 payload 读取并校验 `department`，结果记录必须包含：

```python
record["department"] = department
record["camera_id"] = camera_id
record["camera_name"] = camera_name
```

稳定结果文件写入：

```text
<results_dir>/<department>/<camera_id>/<session_id>.json
```

预算仍使用全局 `BudgetGuard`，但各事业部统计分别记录本事业部调用量和队列长度。

- [ ] **Step 5: 增加公平调度配置并运行测试**

```yaml
vlm:
  max_concurrent: 3
  scheduling: department_round_robin
```

Run:

```bash
cd security_vlm && pytest -q tests/test_vlm_multicamera.py tests/test_vlm_worker.py tests/test_frame_hub.py
```

Expected: 全部通过，两个事业部结果文件互不出现对方记录。

- [ ] **Step 6: 提交 VLM 分区**

```bash
git add security_vlm/src/vlm_worker.py security_vlm/configs/config.example.yaml security_vlm/tests/test_vlm_multicamera.py security_vlm/tests/test_vlm_worker.py
git commit -m "feat: partition security vlm results by department"
```

### Task 5: 提供事业部作用域 API 并保留通用电气兼容入口

**Files:**

- Modify: `security_vlm/src/main.py`
- Modify: `security_vlm/tests/test_multicamera_api.py`

- [ ] **Step 1: 写四工作区 API、容量和跨工作区摄像头测试**

```python
@pytest.mark.asyncio
async def test_department_camera_lists_are_isolated(client):
    created = await client.post(
        "/api/departments/general_electric/cameras",
        json={"name": "一号", "rtsp_url": "rtsp://ge/stream"},
    )
    camera_id = created.json()["camera"]["camera_id"]

    assert (await client.get(
        "/api/departments/general_electric/cameras"
    )).json()["cameras"][0]["camera_id"] == camera_id
    assert (await client.get(
        "/api/departments/electronics_electrician/cameras"
    )).json()["cameras"] == []
    assert (await client.get(
        f"/api/departments/electronics_electrician/cameras/{camera_id}"
    )).status_code == 404


@pytest.mark.asyncio
async def test_each_department_has_its_own_four_camera_limit(client):
    for department in SECURITY_DEPARTMENTS:
        for index in range(4):
            response = await client.post(
                f"/api/departments/{department}/cameras",
                json={
                    "name": f"Camera {index}",
                    "rtsp_url": f"rtsp://{department}-{index}/stream",
                },
            )
            assert response.status_code == 201
        assert (await client.post(
            f"/api/departments/{department}/cameras",
            json={"name": "Camera 5", "rtsp_url": "rtsp://fifth/stream"},
        )).status_code == 400


@pytest.mark.asyncio
async def test_delete_archives_roi_and_keeps_history(client, service):
    camera = await create_camera(client, "general_electric", "A")
    await save_polygon_roi(client, "general_electric", camera["camera_id"])
    service.workspace("general_electric").result_store.write(
        "vlm_history",
        {"items": [{
            "department": "general_electric",
            "camera_id": camera["camera_id"],
        }]},
    )

    response = await client.delete(
        f"/api/departments/general_electric/cameras/{camera['camera_id']}"
    )

    assert response.status_code == 200
    assert service.workspace("general_electric").archive_dir.joinpath(
        camera["camera_id"]
    ).exists()
    assert service.get_department_state("general_electric")["history"]
```

- [ ] **Step 2: 运行测试并确认新路由返回 404**

Run:

```bash
cd security_vlm && pytest -q tests/test_multicamera_api.py
```

Expected: `FAIL`，事业部路由尚未注册。

- [ ] **Step 3: 把 AppService 改为工作区门面**

核心入口：

```python
def workspace(self, department: str) -> DepartmentWorkspace:
    return self.workspaces.get(department)


def get_department_state(self, department: str) -> dict:
    workspace = self.workspace(department)
    cameras = [
        self.get_camera_state(department, camera["camera_id"])
        for camera in workspace.registry.list()
    ]
    return {
        "department": department,
        "running": any(camera["running"] for camera in cameras),
        "cameras": cameras,
        "history": (
            workspace.result_store.read("vlm_history", {"items": []}) or {}
        ).get("items", [])[:200],
        "stats": workspace.result_store.read("vlm_latest_stats", {}) or {},
    }
```

`roi_path()`、`camera_store()`、`get_frame_hub()` 和 `_roi_caches` 的键都改为 `department + camera_id`。

删除摄像头时先调用 `runtime_manager.stop(department, camera_id)`，再通过工作区把 ROI 和摄像头运行目录原子移动到 `archive/<camera_id>/<timestamp>/`；历史文件不移动、不删除。

- [ ] **Step 4: 注册 canonical 路由**

增加：

```python
prefix = "/api/departments/{department}"
```

并将摄像头 CRUD、凭据、测试、启停、ROI、历史和视频路由放到该前缀下。每个处理函数第一行调用 `require_department(department)`，随后只取得该工作区。

保留现有 `/api/cameras`、`/api/history`、`/video/{camera_id}/{kind}` 作为通用电气兼容别名；兼容路由内部显式调用 `general_electric`，并在响应头加入：

```text
Deprecation: true
```

根 `/health` 只返回四个事业部的聚合健康摘要，不返回混合历史；页面使用 `/api/departments/{department}/health`。

- [ ] **Step 5: 运行 API 回归测试**

Run:

```bash
cd security_vlm && pytest -q tests/test_multicamera_api.py tests/test_camera_registry.py tests/test_camera_runtime.py
```

Expected: 全部通过；兼容入口仍返回通用电气数据，新入口严格隔离。

- [ ] **Step 6: 提交事业部 API**

```bash
git add security_vlm/src/main.py security_vlm/tests/test_multicamera_api.py
git commit -m "feat: add department-scoped security vlm api"
```

### Task 6: 在统一后端强制权限并隔离告警

**Files:**

- Modify: `unified_backend/app.py`
- Modify: `unified_backend/tests/test_guard_room_sites.py`

- [ ] **Step 1: 写 viewer 跨事业部拒绝和告警过滤测试**

```python
def test_security_viewer_can_only_read_own_department():
    viewer = {"role": "viewer", "department": "electronics_electrician"}

    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/electronics_electrician/cameras",
    ) is True
    assert _can_access_security_vlm(
        viewer,
        "GET",
        "/security-vlm/api/departments/general_electric/cameras",
    ) is False
    assert _can_access_security_vlm(
        viewer,
        "POST",
        "/security-vlm/api/departments/electronics_electrician/cameras",
    ) is False


def test_security_alarm_filter_requires_matching_department():
    viewer = {"role": "viewer", "department": "electrical_components"}
    alarms = [
        {"event_type": "security_vlm_non_compliant", "department": "general_electric"},
        {"event_type": "security_vlm_non_compliant", "department": "electrical_components"},
    ]
    assert _filter_alarms(alarms, user=viewer) == [alarms[1]]


def test_security_alarm_ids_include_department():
    alarm = _normalize_security_vlm_alarm({
        "department": "precious_metal_recycling",
        "session_id": "session-1",
        "camera_id": "camera-a",
        "status": "non_compliant",
    })
    assert alarm["id"] == "security_vlm:precious_metal_recycling:session-1"


def test_security_platform_summary_aggregates_department_cameras():
    summary = _security_vlm_runtime_summary({
        "departments": {
            "general_electric": {"camera_count": 2, "online_camera_count": 1},
            "electronics_electrician": {"camera_count": 3, "online_camera_count": 2},
        }
    })
    assert summary["camera_count"] == 5
    assert summary["online_camera_count"] == 3
    assert summary["offline_camera_count"] == 2
```

- [ ] **Step 2: 运行测试并确认现有权限只看角色而失败**

Run:

```bash
pytest -q unified_backend/tests/test_guard_room_sites.py
```

Expected: `FAIL`，当前 `_can_access_security_vlm()` 不解析事业部。

- [ ] **Step 3: 实现路径事业部解析和权限矩阵**

```python
SECURITY_VLM_DEPARTMENT_PATH = re.compile(
    r"^/security-vlm/api/departments/([^/]+)(?:/|$)"
)


def _security_vlm_department_from_path(path: str) -> str | None:
    match = SECURITY_VLM_DEPARTMENT_PATH.match(str(path).rstrip("/"))
    return _normalize_department(match.group(1)) if match else None
```

权限规则：

```python
if role == "admin":
    return True
if role != "viewer" or method not in {"GET", "HEAD", "OPTIONS"}:
    return False
requested = _security_vlm_department_from_path(path)
return requested is not None and requested == _normalize_department(user.get("department"))
```

凭据接口即使是 `GET` 也只允许管理员。旧无事业部兼容入口只允许管理员或 `general_electric` viewer。

- [ ] **Step 4: 按事业部采集和标准化告警**

`_normalize_security_vlm_alarm()` 增加：

```python
"id": f"security_vlm:{item['department']}:{source_id}",
"department": item["department"],
"camera_no": item.get("camera_id") or item.get("roi_name") or "security_vlm",
"camera_name": item.get("camera_name") or item.get("roi_name") or "安检流程规范检测",
```

viewer 只请求自己的：

```text
/api/departments/<department>/history
```

admin 分别请求四个事业部历史并合并。`_filter_alarms()` 对 `source == "security_vlm"` 额外按 `department` 过滤。

把 `security_vlm_non_compliant` 和 `security_vlm_error` 加入电子电工、电气部件、贵金属回收三个事业部的 `DEPARTMENT_EVENT_TYPES`。平台状态读取根 `/health` 的事业部汇总，摄像头总数、在线数和离线数按四个工作区求和，删除当前硬编码的单摄像头计数。

把汇总逻辑提取为 `_security_vlm_runtime_summary(payload)`，对缺失或非数字字段按 0 处理，返回 `camera_count`、`online_camera_count` 和 `offline_camera_count`，供平台状态接口复用。

- [ ] **Step 5: 运行统一后端测试**

Run:

```bash
pytest -q unified_backend/tests/test_guard_room_sites.py
```

Expected: 全部通过。

- [ ] **Step 6: 提交权限和告警隔离**

```bash
git add unified_backend/app.py unified_backend/tests/test_guard_room_sites.py
git commit -m "feat: enforce security department access"
```

### Task 7: 增加四个前端入口并让所有请求带事业部

**Files:**

- Modify: `unified_frontend/src/auth/permissions.ts`
- Modify: `unified_frontend/src/lib/nav.ts`
- Modify: `unified_frontend/src/App.tsx`
- Modify: `unified_frontend/src/sections/HomeSection.tsx`
- Modify: `unified_frontend/src/lib/security-vlm.ts`
- Modify: `unified_frontend/src/components/security-vlm/SecurityVideoPanel.tsx`

- [ ] **Step 1: 先修改类型，让旧调用在 TypeScript 构建中失败**

定义：

```typescript
export type SecurityVlmDepartment =
  | 'general_electric'
  | 'electronics_electrician'
  | 'electrical_components'
  | 'precious_metal_recycling'

export type RoiPoint = [number, number]
export type SecurityVlmRois = Record<string, RoiPoint[]>
```

将所有 API 函数的第一个参数改为 `department: SecurityVlmDepartment`，例如：

```typescript
export const getSecurityVlmHealth = (department: SecurityVlmDepartment) =>
  securityVlmGet<SecurityVlmHealth>(
    `/api/departments/${encodeURIComponent(department)}/health`,
  )
```

- [ ] **Step 2: 运行构建并确认所有旧调用被类型系统找出**

Run:

```bash
cd unified_frontend && npm run build
```

Expected: `FAIL`，错误集中在 `SecurityVlmSection.tsx` 和视频组件缺少 `department` 参数。

- [ ] **Step 3: 增加页面 ID 和权限**

保留 `security-vlm` 作为通用电气页面 ID，并新增：

```typescript
| 'security-vlm-electronics-electrician'
| 'security-vlm-electrical-components'
| 'security-vlm-precious-metal-recycling'
```

三个事业部权限分别加入对应页面。告警事件映射仍使用相同事件类型，但后台最终按事业部过滤。

在 `nav.ts` 增加三个同名导航项，描述包含对应事业部。`HomeSection` 的管理员事业部分组使用各自页面 ID。

- [ ] **Step 4: 让 App 复用同一页面**

```tsx
case 'security-vlm':
  return <SecurityVlmSection department="general_electric" />
case 'security-vlm-electronics-electrician':
  return <SecurityVlmSection department="electronics_electrician" />
case 'security-vlm-electrical-components':
  return <SecurityVlmSection department="electrical_components" />
case 'security-vlm-precious-metal-recycling':
  return <SecurityVlmSection department="precious_metal_recycling" />
```

所有摄像头、ROI、启停、历史和视频 URL 构造函数都带 `department`。

- [ ] **Step 5: 运行前端构建和 Lint**

Run:

```bash
cd unified_frontend && npm run build && npm run lint
```

Expected: 两个命令退出码均为 0。

- [ ] **Step 6: 提交前端事业部路由**

```bash
git add unified_frontend/src/auth/permissions.ts unified_frontend/src/lib/nav.ts unified_frontend/src/App.tsx unified_frontend/src/sections/HomeSection.tsx unified_frontend/src/lib/security-vlm.ts unified_frontend/src/components/security-vlm/SecurityVideoPanel.tsx
git commit -m "feat: add security pages for four departments"
```

### Task 8: 抽取并复用无模式 ROI 画布

**Files:**

- Create: `unified_frontend/src/components/roi/RoiCanvas.tsx`
- Modify: `unified_frontend/src/components/AiVisionRoiEditor.tsx`
- Modify: `unified_frontend/src/sections/SecurityVlmSection.tsx`
- Modify: `unified_frontend/src/lib/security-vlm.ts`

- [ ] **Step 1: 定义通用画布接口并让构建先失败**

```typescript
export type RoiCanvasPoint = { x: number; y: number }
export type RoiCanvasMode = 'auto' | 'rect' | 'line'
export type RoiCanvasValidation = {
  valid: boolean
  outOfBounds: boolean
  areaTooSmall: boolean
}

export type RoiCanvasProps = {
  imageUrl: string
  imageAlt: string
  points: RoiCanvasPoint[]
  mode?: RoiCanvasMode
  disabled?: boolean
  minArea?: number
  onChange: (points: RoiCanvasPoint[]) => void
  onValidationChange?: (state: RoiCanvasValidation) => void
}
```

在 `AiVisionRoiEditor` 和 `SecurityVlmSection` 中先引用 `RoiCanvas`，不创建文件。

- [ ] **Step 2: 运行构建并确认模块不存在**

Run:

```bash
cd unified_frontend && npm run build
```

Expected: `FAIL`，错误包含 `Cannot find module '@/components/roi/RoiCanvas'`。

- [ ] **Step 3: 从 AiVisionRoiEditor 抽取现有手势实现**

`RoiCanvas` 必须保留现有 `polygon`、`rect`、`line` 三种调用场景，并把安检与人体逗留使用的 polygon 行为命名为 `auto`：

```typescript
const dragged =
  pointDistance(dragStart, draftPoint) >
  DRAG_THRESHOLD_PX * imagePixelsPerRenderedPixel(
    event.currentTarget.getBoundingClientRect(),
    imageSize,
  )

if (mode === 'line') {
  onChange(dragged ? [dragStart, draftPoint] : appendLinePoint(points, dragStart))
} else if (dragged || mode === 'rect') {
  onChange(rectToPoints(pointsToRect([dragStart, draftPoint])))
} else {
  onChange([...points, dragStart])
}
```

指针落在已有顶点命中半径内时拖动该顶点；否则开始新手势。画布绘制 polygon、编号圆点，并通过 `onValidationChange` 返回 `valid`、`outOfBounds`、`areaTooSmall` 状态给上层操作栏。

`AiVisionRoiEditor` 把现有 `polygon` 映射为 `auto`，`rect` 和 `line` 原样传入；它继续负责刷新画面、提示文字和保存按钮，只把画布手势交给 `RoiCanvas`，确保人体逗留、大门矩形和警戒线行为都不变。

- [ ] **Step 4: 在安检页面管理多个 ROI**

`SecurityVlmSection` 属性：

```typescript
type SecurityVlmSectionProps = {
  department: SecurityVlmDepartment
}
```

状态：

```typescript
const [rois, setRois] = useState<SecurityVlmRois>({})
const currentPoints = currentRoi ? rois[currentRoi] || [] : []
const [roiValidation, setRoiValidation] = useState<RoiCanvasValidation>({
  valid: false,
  outOfBounds: false,
  areaTooSmall: false,
})
```

画布更新：

```tsx
<RoiCanvas
  imageUrl={activeVideoUrl}
  imageAlt={`${selectedCamera?.name || '安检摄像头'} ROI 绘制画面`}
  points={currentPoints.map(([x, y]) => ({ x, y }))}
  mode="auto"
  disabled={!isAdmin || !selectedCameraId || !selectedCamera?.running}
  onChange={(points) => {
    if (!currentRoi) return
    setRois((previous) => ({
      ...previous,
      [currentRoi]: points.map(({ x, y }) => [Math.round(x), Math.round(y)]),
    }))
  }}
  onValidationChange={setRoiValidation}
/>
```

新增 ROI 后提示“可直接点击添加多边形顶点，或拖拽生成矩形”。列表显示顶点数和外接范围，不再把顶点数组当 `[x1,y1,x2,y2]`。当前 ROI 无效、越界或面积过小时禁用保存并显示明确原因。

- [ ] **Step 5: 在事业部变化时彻底清理页面状态**

增加依赖 `department` 的 effect：

```typescript
useEffect(() => {
  setHealth(null)
  setSelectedCameraId(undefined)
  setSecondaryCameraId(undefined)
  setRois({})
  setSlotNames([])
  setCurrentRoi(null)
  setMessage(`正在连接${departmentLabel}安检流程规范检测服务...`)
}, [department, departmentLabel])
```

轮询、摄像头弹窗操作、视频地址和全部启停都使用当前 `department`。

- [ ] **Step 6: 构建、Lint 并人工验证手势**

Run:

```bash
cd unified_frontend && npm run build && npm run lint
```

Expected: 两个命令退出码均为 0。

Manual:

```text
1. 在人体逗留检测 ROI 页面逐点点击并拖拽，确认旧功能不变。
2. 在安检 ROI 页面单击 4 次，确认形成四边形。
3. 清空后从左上拖到右下，确认形成四点矩形。
4. 拖动任一编号顶点，确认只移动该顶点。
5. 创建第二个 ROI，确认第一个 ROI 不被覆盖。
6. 切换事业部，确认摄像头与 ROI 状态立即清空后重新加载。
```

- [ ] **Step 7: 提交 ROI 画布复用**

```bash
git add unified_frontend/src/components/roi/RoiCanvas.tsx unified_frontend/src/components/AiVisionRoiEditor.tsx unified_frontend/src/sections/SecurityVlmSection.tsx unified_frontend/src/lib/security-vlm.ts
git commit -m "feat: reuse polygon roi canvas for security"
```

### Task 9: 完整回归、迁移演练和项目文档

**Files:**

- Modify: `README.md`
- Modify: `security_vlm/readme.md`
- Modify: `security_vlm/logical_explanation.md`

- [ ] **Step 1: 更新运行和数据目录文档**

文档明确写出：

```text
- 四个事业部共用模型和规则。
- 每个事业部最多 4 台摄像头。
- data/departments/<department>/ 保存摄像头与 ROI。
- runtime/departments/<department>/ 保存运行状态、历史和统计。
- 旧全局数据首次启动只迁入 general_electric。
- 全部启停只作用于当前事业部。
```

- [ ] **Step 2: 运行全部后端测试**

Run:

```bash
cd security_vlm && pytest -q
```

Expected: 全部通过。

Run:

```bash
pytest -q unified_backend/tests
```

Expected: 全部通过。

- [ ] **Step 3: 运行前端验证**

Run:

```bash
cd unified_frontend && npm run build && npm run lint
```

Expected: 两个命令退出码均为 0。

- [ ] **Step 4: 使用临时目录演练迁移**

使用测试配置启动一次 `AppService`，确认：

```text
1. legacy cameras.json 保持存在。
2. general_electric/cameras.json 包含原摄像头。
3. general_electric/rois/ 包含原 ROI。
4. 另外三个 cameras.json 的 cameras 均为空数组。
5. 第二次启动不新增重复摄像头或历史。
```

Run:

```bash
cd security_vlm && pytest -q tests/test_department_workspace.py::test_legacy_files_migrate_only_to_general_electric_and_are_idempotent
```

Expected: 通过。

- [ ] **Step 5: 检查未预期改动和格式**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` 无输出；状态只包含本计划涉及的文件。

- [ ] **Step 6: 提交文档与最终验证结果**

```bash
git add README.md security_vlm/readme.md security_vlm/logical_explanation.md
git commit -m "docs: document security department isolation"
```

## 最终验收清单

- [ ] 四个事业部各自看到独立的安检入口。
- [ ] 新增三个事业部的摄像头初始为空。
- [ ] 每个事业部最多 4 台摄像头。
- [ ] 摄像头、ROI、运行状态、历史、告警和统计没有跨事业部泄漏。
- [ ] viewer 只能读取自己事业部，admin 可以管理四个事业部。
- [ ] 同名摄像头可以存在于不同事业部。
- [ ] 旧通用电气数据幂等迁移且保留源文件。
- [ ] 拖拽生成矩形，点击生成多边形，已有顶点可以拖动。
- [ ] 一台摄像头可以保存多个独立 ROI。
- [ ] 人体逗留检测的现有 ROI 交互没有回归。
- [ ] 公共 VLM 队列按事业部公平调度，结果写入对应工作区。
- [ ] 后端测试、前端构建和 Lint 全部通过。
