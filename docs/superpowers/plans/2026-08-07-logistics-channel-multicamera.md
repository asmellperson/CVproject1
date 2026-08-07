# 物流通道多摄像头联合单人检测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为四个物流通道单人检测模块增加具名物流通道、最多 9 路摄像头、逐路 ROI、自动拼接和通道级联合告警。

**Architecture:** 在 `AiVision/platform/logistics_channel` 中建立共享领域层，数据库服务负责通道和成员，纯状态机负责联合判定，共享消费者基类负责逐路推理并把结果提交给每个 feature 独立的通道协调器。FastAPI 暴露白名单化的通道资源接口，统一前端使用一个参数化页面服务四个模块；现有摄像头、推理、配置事件和告警基础设施继续复用。

**Tech Stack:** Python 3、FastAPI、Pydantic、SQLAlchemy、OpenCV、pytest、React 19、TypeScript、Vite、Node test runner。

---

## 文件结构

新增后端领域文件：

- `AiVision/platform/logistics_channel/__init__.py`：公开领域常量、服务和运行时类型。
- `AiVision/platform/logistics_channel/constants.py`：四个允许的 feature、默认检测时间、默认过期阈值和 9 路上限。
- `AiVision/platform/logistics_channel/orm.py`：物流通道及通道成员 ORM。
- `AiVision/platform/logistics_channel/schema.py`：通道、成员、配置、状态的 Pydantic DTO。
- `AiVision/platform/logistics_channel/state.py`：纯通道判定、持续计时、ROI 人体框去重和线程安全快照仓库。
- `AiVision/platform/logistics_channel/compositor.py`：1/2/4/9 格拼接与离线占位。
- `AiVision/platform/logistics_channel/service.py`：CRUD、事务式摄像头绑定、排序和幂等迁移。
- `AiVision/platform/logistics_channel/runtime.py`：按 feature 聚合逐路结果、生成状态/拼接帧、通道级告警请求。
- `AiVision/api/v2/logistics_channels.py`：物流通道 REST、状态和 JPEG 帧接口。
- `AiVision/features/_base/logistics_single_person_consumer.py`：四个物流消费者共享的推理、计数、标注和通道提交逻辑。

新增或扩展测试：

- `AiVision/tests/test_logistics_channel_state.py`
- `AiVision/tests/test_logistics_channel_compositor.py`
- `AiVision/tests/test_logistics_channel_service.py`
- `AiVision/tests/test_logistics_channel_runtime.py`
- `AiVision/tests/test_logistics_channel_api.py`
- `unified_backend/tests/test_logistics_channel_alarms.py`
- `unified_frontend/tests/logistics-channel-api-contract.test.mjs`
- `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`

新增前端共享文件：

- `unified_frontend/src/components/logistics_single_person/types.ts`：物流通道 API 类型。
- `unified_frontend/src/components/logistics_single_person/api.ts`：通道资源请求函数和帧 URL。
- `unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts`：通道列表、选择、状态和帧轮询。
- `unified_frontend/src/components/logistics_single_person/LogisticsChannelMonitorView.tsx`：通道级仪表盘。
- `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx`：通道、成员、逐路 ROI 和通道规则管理。
- `unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx`：四模块共用页面容器。

保留四个现有 section 文件作为轻量路由包装器，删除其中重复业务逻辑。旧摄像头级兼容 API 暂时保留。

### Task 1: 建立物流通道 ORM、常量和响应模型

**Files:**
- Create: `AiVision/platform/logistics_channel/__init__.py`
- Create: `AiVision/platform/logistics_channel/constants.py`
- Create: `AiVision/platform/logistics_channel/orm.py`
- Create: `AiVision/platform/logistics_channel/schema.py`
- Modify: `AiVision/core/db.py:163-171`
- Test: `AiVision/tests/test_logistics_channel_service.py`

- [ ] **Step 1: 写 ORM 和 schema 的失败测试**

```python
def test_channel_defaults_and_member_constraints(db_session):
    channel = LogisticsChannel(
        name="一号物流通道",
        feature_name="detect_logistics_single_person",
    )
    db_session.add(channel)
    db_session.flush()
    assert channel.enabled is True
    assert channel.detection_start == dt.time(8, 0)
    assert channel.detection_end == dt.time(20, 0)
    assert channel.empty_grace_seconds == 2.0
    assert channel.multi_grace_seconds == 1.0


def test_feature_name_rejects_non_logistics_feature():
    with pytest.raises(ValueError, match="不支持的物流检测功能"):
        require_logistics_feature("blocks")
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `cd AiVision && pytest tests/test_logistics_channel_service.py -v`

Expected: FAIL，提示 `platform.logistics_channel` 不存在。

- [ ] **Step 3: 增加固定常量和 ORM**

```python
LOGISTICS_FEATURES = frozenset({
    "detect_logistics_single_person",
    "detect_logistics_single_person_electronics_electrician",
    "detect_logistics_single_person_electrical_components",
    "detect_logistics_single_person_precious_metal_recycling",
})
MAX_CAMERAS_PER_CHANNEL = 9
DEFAULT_DETECTION_START = dt.time(8, 0)
DEFAULT_DETECTION_END = dt.time(20, 0)
DEFAULT_STATUS_STALE_SECONDS = 5.0
```

`LogisticsChannel` 使用表 `ai_logistics_channel`，字段为 `id/name/feature_name/enabled/sort_order/detection_start/detection_end/empty_grace_seconds/multi_grace_seconds/alarm_interval/sql_enable/horn_enable/horn_id/horn_event_id/wechat_enable/wechat_user/created_at/updated_at`。为 `(feature_name, name)` 建唯一约束。

`LogisticsChannelCamera` 使用表 `ai_logistics_channel_camera`，字段为 `id/channel_id/camera_id/enabled/sort_order/created_at/updated_at`；为 `(channel_id, camera_id)` 建唯一约束，并让服务层额外保证同一 `feature_name` 下唯一归属。

- [ ] **Step 4: 增加明确 DTO**

```python
class LogisticsChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class LogisticsChannelConfigUpdate(BaseModel):
    enabled: bool
    detection_start: datetime.time
    detection_end: datetime.time
    empty_grace_seconds: float = Field(ge=0)
    multi_grace_seconds: float = Field(ge=0)
    alarm_interval: float = Field(gt=0)
    alarm: LogisticsChannelAlarm


class LogisticsChannelMemberCreate(BaseModel):
    camera_id: int | None = None
    name: str | None = None
    url: str | None = None
    fps: int = Field(5, gt=0)
```

`feature_name` 由 API 路径提供并通过 `require_logistics_feature()` 校验，不允许请求体覆盖。为列表、详情、成员和实时状态分别定义响应模型；校验“已有摄像头 ID”和“新摄像头名称 + URL”只能选择一种输入方式，开始时间必须早于结束时间。

- [ ] **Step 5: 注册 ORM 并确认测试通过**

在 `ensure_schema_compatible()` 的强制导入区加入：

```python
from platform.logistics_channel import orm as _logistics_channel_orm  # noqa: F401
```

Run: `cd AiVision && pytest tests/test_logistics_channel_service.py -v`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add AiVision/platform/logistics_channel AiVision/core/db.py AiVision/tests/test_logistics_channel_service.py
git commit -m "feat: add logistics channel data model"
```

### Task 2: 实现纯联合判定、持续时间和 ROI 去重

**Files:**
- Create: `AiVision/platform/logistics_channel/state.py`
- Test: `AiVision/tests/test_logistics_channel_state.py`

- [ ] **Step 1: 写完整判定表失败测试**

```python
@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ([0, 0], "empty"),
        ([1, 0], "normal"),
        ([1, 1], "normal"),
        ([2, 0], "multiple"),
        ([3, 1], "multiple"),
        ([None, 0], "unknown"),
        ([None, 1], "normal"),
        ([None, 2], "multiple"),
        ([], "unconfigured"),
    ],
)
def test_classify_channel_counts(counts, expected):
    snapshots = [CameraSnapshot(camera_id=i + 1, count=count, updated_at=100.0) for i, count in enumerate(counts)]
    assert classify_channel(snapshots, now=100.0, stale_seconds=5.0).reason == expected
```

同时增加结果过期、停用成员、停用通道、非检测时间、无人和多人分别持续计时、状态切换清零、配置变更清零的测试。

- [ ] **Step 2: 写 ROI 去重失败测试**

```python
def test_deduplicate_person_boxes_across_overlapping_rois():
    detections = [
        PersonDetection((100, 100, 200, 300), 0.91),
        PersonDetection((104, 102, 202, 302), 0.88),
        PersonDetection((500, 100, 600, 300), 0.95),
    ]
    unique = deduplicate_person_detections(detections, iou_threshold=0.5)
    assert [item.bbox for item in unique] == [(100, 100, 200, 300), (500, 100, 600, 300)]
```

- [ ] **Step 3: 运行并确认失败**

Run: `cd AiVision && pytest tests/test_logistics_channel_state.py -v`

Expected: FAIL，缺少状态类型和判定函数。

- [ ] **Step 4: 实现纯状态类型和判定优先级**

```python
@dataclass(frozen=True)
class CameraSnapshot:
    camera_id: int
    count: int | None
    updated_at: float
    online: bool = True


def classify_channel(snapshots, *, now, stale_seconds, active=True):
    if not active:
        return ChannelDecision("inactive", False, 0.0)
    if not snapshots:
        return ChannelDecision("unconfigured", False, 0.0)
    counts = [
        item.count if item.online and now - item.updated_at <= stale_seconds else None
        for item in snapshots
    ]
    if any(count is not None and count >= 2 for count in counts):
        return ChannelDecision("multiple", False, 0.0)
    if any(count == 1 for count in counts):
        return ChannelDecision("normal", False, 0.0)
    if all(count == 0 for count in counts):
        return ChannelDecision("empty", False, 0.0)
    return ChannelDecision("unknown", False, 0.0)
```

实现 `ChannelPresenceState.evaluate(reason, now, empty_grace, multi_grace)`：仅 `empty` 和 `multiple` 连续累计；其他状态清零；返回 `alarm/duration_seconds/threshold_seconds`。

- [ ] **Step 5: 实现全画面坐标映射和 IoU 去重**

将每个 ROI 的框加上 `(x_offset, y_offset)`，按置信度降序执行 NMS 风格去重，只对 `person/human` 框计数。输出全画面坐标，供画框和告警证据复用。

- [ ] **Step 6: 运行并确认通过**

Run: `cd AiVision && pytest tests/test_logistics_channel_state.py -v`

Expected: PASS，判定表、计时和去重全部通过。

- [ ] **Step 7: 提交**

```bash
git add AiVision/platform/logistics_channel/state.py AiVision/tests/test_logistics_channel_state.py
git commit -m "feat: add logistics channel decision state"
```

### Task 3: 实现通道 CRUD、事务式绑定和幂等迁移

**Files:**
- Create: `AiVision/platform/logistics_channel/service.py`
- Modify: `AiVision/platform/camera/service.py:71-130`
- Test: `AiVision/tests/test_logistics_channel_service.py`

- [ ] **Step 1: 扩展服务失败测试**

覆盖：按 feature 列表、新增/重命名/删除、同 feature 名称唯一、最多 9 路、同 feature 唯一归属、跨通道移动、只解除绑定不删除摄像头、新建摄像头绑定失败时事务回滚。

```python
def test_create_camera_and_bind_rolls_back_as_one_transaction(service, camera_service, monkeypatch):
    channel = service.create_channel("detect_logistics_single_person", "一号通道")
    monkeypatch.setattr(service, "_validate_member_limit", Mock(side_effect=ValueError("最多 9 路")))
    with pytest.raises(ValueError, match="最多 9 路"):
        service.create_camera_and_bind(channel.id, {"name": "新摄像头", "url": "rtsp://example/live"})
    assert camera_service.get_camera("新摄像头") is None
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd AiVision && pytest tests/test_logistics_channel_service.py -v`

Expected: FAIL，服务方法不存在。

- [ ] **Step 3: 抽取可复用的摄像头事务写入**

在 `CameraService` 中增加 `_create_camera_record(session, payload)`，让现有 `create_camera()` 和通道服务共用同一套名称、`shm_name`、FPS、部门及默认 feature 配置校验。事件发布保留在事务提交之后：

```python
with session_scope() as session:
    camera = camera_service.create_camera_record(session, payload)
    member = self._bind_record(session, channel, camera.id)
camera_service.notify_camera_created(camera.id, camera.shm_name)
self._publish_channel_change(channel.feature_name, channel.id)
```

`shm_name` 未提供时使用稳定格式 `camera_<数据库ID>`，不得从用户名称直接拼接出不安全标识。

- [ ] **Step 4: 实现通道服务方法**

实现 `list_channels/get_channel/create_channel/update_channel/delete_channel/add_existing_camera/create_camera_and_bind/move_camera/reorder_members/remove_camera/update_config`。所有入口先调用 `require_logistics_feature(feature_name)`，并在事务内锁定目标通道后校验 9 路和唯一归属。

移除成员时把对应 feature ORM 的 `enable` 设为 `False`，但保留 ROI 和过滤参数；移动成员时保持 `enable=True`，不得产生中间停用事件。

- [ ] **Step 5: 实现幂等迁移**

```python
def migrate_existing_feature_cameras(self) -> MigrationSummary:
    for feature_name in sorted(LOGISTICS_FEATURES):
        for camera, feature_cfg in self._enabled_unassigned_cameras(feature_name):
            channel_name = self._available_migration_name(feature_name, camera.name, camera.id)
            channel = self._create_from_legacy_config(feature_name, channel_name, feature_cfg)
            self._bind_record(session, channel, camera.id)
```

迁移复制 `empty_grace_seconds/multi_grace_seconds/alarm_interval` 和扁平告警字段；ROI、置信度、IoU、面积和宽高比继续留在原 feature ORM。重复运行时以已绑定关系判定并跳过。名称冲突稳定使用 `f"{camera.name}-{camera.id}"`。

- [ ] **Step 6: 运行并确认通过**

Run: `cd AiVision && pytest tests/test_logistics_channel_service.py -v`

Expected: PASS，包括事务回滚和迁移运行两次不重复。

- [ ] **Step 7: 提交**

```bash
git add AiVision/platform/camera/service.py AiVision/platform/logistics_channel/service.py AiVision/tests/test_logistics_channel_service.py
git commit -m "feat: manage logistics channels and memberships"
```

### Task 4: 实现稳定的多画面拼接

**Files:**
- Create: `AiVision/platform/logistics_channel/compositor.py`
- Test: `AiVision/tests/test_logistics_channel_compositor.py`

- [ ] **Step 1: 写布局失败测试**

```python
@pytest.mark.parametrize(("count", "shape"), [(1, (360, 640)), (2, (360, 1280)), (4, (720, 1280)), (9, (1080, 1920))])
def test_compose_layout_shapes(count, shape):
    tiles = [CameraTile(i, f"cam-{i}", np.zeros((240, 320, 3), np.uint8), "normal", 1) for i in range(count)]
    assert compose_channel_frame(tiles, tile_size=(640, 360)).shape[:2] == shape


def test_missing_frame_uses_named_placeholder():
    frame = compose_channel_frame([CameraTile(1, "北门", None, "unknown", None)])
    assert frame is not None
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd AiVision && pytest tests/test_logistics_channel_compositor.py -v`

Expected: FAIL，拼接模块不存在。

- [ ] **Step 3: 实现布局和补边**

实现 `layout_for_count()` 返回 `1x1/1x2/2x2/3x3`；`letterbox()` 按比例缩放到固定格子；`render_placeholder()` 显示摄像头名和离线原因；`compose_channel_frame()` 按成员排序填充剩余空格并绘制名称、人数和状态条。禁止对拼接结果再次推理。

- [ ] **Step 4: 运行并确认通过**

Run: `cd AiVision && pytest tests/test_logistics_channel_compositor.py -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add AiVision/platform/logistics_channel/compositor.py AiVision/tests/test_logistics_channel_compositor.py
git commit -m "feat: compose logistics channel frames"
```

### Task 5: 抽取四模块共享消费者并停止单摄像头报警

**Files:**
- Create: `AiVision/features/_base/logistics_single_person_consumer.py`
- Modify: `AiVision/features/detect_logistics_single_person/consumer.py`
- Modify: `AiVision/features/detect_logistics_single_person_electronics_electrician/consumer.py`
- Modify: `AiVision/features/detect_logistics_single_person_electrical_components/consumer.py`
- Modify: `AiVision/features/detect_logistics_single_person_precious_metal_recycling/consumer.py`
- Modify: `AiVision/tests/test_logistics_single_person.py`
- Test: `AiVision/tests/test_logistics_channel_runtime.py`

- [ ] **Step 1: 写共享行为失败测试**

```python
@pytest.mark.parametrize("consumer_cls", LOGISTICS_CONSUMER_CLASSES)
def test_all_logistics_consumers_publish_camera_snapshot_without_camera_alarm(consumer_cls):
    consumer = build_consumer(consumer_cls)
    result = consumer._process([roi_with_two_people()], camera_id=7)
    assert all(alarm is False for alarm, _detail in result)
    assert sum(len(detail["detections"]) for _alarm, detail in result) == 2
```

增加四个 class 都继承共享基类、检测时间不再读取 class 常量、重叠 ROI 只计一次、标注帧仍包含 ROI 和人体框的测试。

- [ ] **Step 2: 运行并确认失败**

Run: `cd AiVision && pytest tests/test_logistics_single_person.py tests/test_logistics_channel_runtime.py -v`

Expected: FAIL，现有消费者仍逐 ROI 计时和报警。

- [ ] **Step 3: 实现共享消费者基类**

共享基类复用现有推理过滤和画框代码，但 `_process()` 只返回检测明细，所有 `alarm_flag` 固定为 `False`。`post_process()` 将 ROI 框映射回完整帧、去重、生成单路 `CameraSnapshot` 和标注帧，再提交给注入的 `LogisticsChannelRuntime`。

```python
class LogisticsSinglePersonConsumerBase(BaseFunctionConsumer):
    def __init__(self, *args, logistics_runtime=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.logistics_runtime = logistics_runtime

    def _should_process_now(self, camera_id, cfg):
        return self.logistics_runtime.camera_should_run(self.feature_name, camera_id)

    def _handle_alarm(self, camera_id, result, frame):
        self.logistics_runtime.evaluate_after_camera_update(self.feature_name, camera_id)
```

四个现有 `consumer.py` 只保留原公开类名并继承共享基类，确保 feature 注册和外部导入不变。

- [ ] **Step 4: 运行并确认通过**

Run: `cd AiVision && pytest tests/test_logistics_single_person.py tests/test_logistics_channel_runtime.py -v`

Expected: PASS，四个模块共享同一行为且不再产生摄像头级人数告警。

- [ ] **Step 5: 提交**

```bash
git add AiVision/features/_base/logistics_single_person_consumer.py AiVision/features/detect_logistics_single_person*/consumer.py AiVision/tests/test_logistics_single_person.py AiVision/tests/test_logistics_channel_runtime.py
git commit -m "refactor: share logistics single person consumer"
```

### Task 6: 接入通道运行时、告警元数据和 Orchestrator

**Files:**
- Create: `AiVision/platform/logistics_channel/runtime.py`
- Modify: `AiVision/core/alarm/dispatcher.py`
- Modify: `AiVision/platform/violation/orm.py`
- Modify: `AiVision/platform/violation/service.py`
- Modify: `AiVision/platform/orchestrator.py`
- Modify: `AiVision/core/settings.py`
- Test: `AiVision/tests/test_logistics_channel_runtime.py`
- Test: `AiVision/tests/test_alarm_config_hot_update.py`

- [ ] **Step 1: 写通道运行时与告警失败测试**

验证：部分未知不触发无人、未知不阻止已知多人、达到通道阈值后只分发一次、恢复后可再次告警、告警使用通道冷却键和拼接帧、配置事件清空旧计时。

```python
def test_runtime_dispatches_channel_subject(runtime, dispatcher):
    runtime.update_snapshot(FEATURE, channel_id=3, camera_snapshot=snapshot(10, count=2))
    runtime.evaluate(FEATURE, 3, now=101.0)
    request = dispatcher.requests[0]
    assert request.subject_type == "logistics_channel"
    assert request.subject_id == "3"
    assert request.subject_name == "一号物流通道"
    assert request.metadata["camera_counts"] == {"10": 2}
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd AiVision && pytest tests/test_logistics_channel_runtime.py tests/test_alarm_config_hot_update.py -v`

Expected: FAIL，缺少通道运行时和告警主体字段。

- [ ] **Step 3: 扩展告警请求和持久化字段**

向 `AlarmRequest` 增加默认兼容字段：

```python
subject_type: str = "camera"
subject_id: str = ""
subject_name: str = ""
reason: str = ""
metadata: dict = field(default_factory=dict)
```

冷却 key 改为 `(request.subject_type, request.subject_id or str(request.camera_id), request.feature_name)`。`AiViolationImage` 添加 nullable 的 `subject_type/subject_id/subject_name/reason/event_metadata(JSON)`；异步 writer 和 `save_now()` 原样传递这些字段。非物流告警继续使用默认摄像头主体。

- [ ] **Step 4: 实现通道运行时**

每个 `feature_name` 维护独立的线程安全快照和 `ChannelPresenceState`。收到逐路更新后读取通道成员、标记离线/过期成员、执行判定；达到阈值时调用 compositor，并使用通道配置构造 `AlarmRequest`。`camera_should_run()` 从通道启用状态和每日时间段决定是否推理；状态切换为正常、未知、未配置或停用时重置相应计时。

- [ ] **Step 5: 注入 Orchestrator 并执行迁移**

在 schema 完成、feature 默认配置补齐之后调用 `logistics_channel_service.migrate_existing_feature_cameras()`。Orchestrator 创建一个共享 `LogisticsChannelRuntime`，构造四个物流消费者时传入；其他消费者构造参数不变。

新增 `get_logistics_channel_status(feature, channel_id)` 和 `get_logistics_channel_frame(feature, channel_id)`。配置事件命中通道时刷新 service 缓存、清理受影响状态；成员新增/移除仍发布对应 feature 的摄像头启停事件。

在 `RuntimeSettings` 增加环境项 `LOGISTICS_STATUS_STALE_SECONDS: float = 5.0`，通道运行时统一读取。构造运行时时注入 `frame_reader_registry.is_active` 作为在线状态提供者，不能只凭最近一次人数快照推断在线状态。

- [ ] **Step 6: 运行并确认通过**

Run: `cd AiVision && pytest tests/test_logistics_channel_runtime.py tests/test_alarm_config_hot_update.py tests/test_orchestrator_camera_update.py -v`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add AiVision/platform/logistics_channel/runtime.py AiVision/core/alarm/dispatcher.py AiVision/platform/violation/orm.py AiVision/platform/violation/service.py AiVision/platform/orchestrator.py AiVision/core/settings.py AiVision/tests/test_logistics_channel_runtime.py AiVision/tests/test_alarm_config_hot_update.py
git commit -m "feat: dispatch logistics channel alarms"
```

### Task 7: 暴露物流通道 API 和拼接 JPEG

**Files:**
- Create: `AiVision/api/v2/logistics_channels.py`
- Modify: `AiVision/api/app.py:19-25,106-112`
- Modify: `AiVision/api/deps.py`
- Test: `AiVision/tests/test_logistics_channel_api.py`

- [ ] **Step 1: 写 API 失败测试**

覆盖以下路径及 admin/viewer 行为：

```text
GET    /api/v2/logistics-channels/{feature}
POST   /api/v2/logistics-channels/{feature}
GET    /api/v2/logistics-channels/{feature}/{channel_id}
PUT    /api/v2/logistics-channels/{feature}/{channel_id}
DELETE /api/v2/logistics-channels/{feature}/{channel_id}
POST   /api/v2/logistics-channels/{feature}/{channel_id}/cameras
PUT    /api/v2/logistics-channels/{feature}/{channel_id}/cameras/order
DELETE /api/v2/logistics-channels/{feature}/{channel_id}/cameras/{camera_id}
GET    /api/v2/logistics-channels/{feature}/{channel_id}/status
GET    /api/v2/logistics-channels/{feature}/{channel_id}/frame.jpg
GET    /api/v2/logistics-channels/{feature}/{channel_id}/alarms
GET    /api/v2/logistics-channels/{feature}/{channel_id}/statistics
```

```python
def test_viewer_cannot_create_channel(client, viewer_headers):
    response = client.post(
        f"/api/v2/logistics-channels/{FEATURE}",
        json={"name": "一号通道"},
        headers=viewer_headers,
    )
    assert response.status_code == 403
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd AiVision && pytest tests/test_logistics_channel_api.py -v`

Expected: FAIL 或 404。

- [ ] **Step 3: 实现路由和依赖注入**

所有写接口依赖 `require_admin`，所有接口先校验 feature 白名单和用户部门权限。业务 `ValueError` 映射 400，不存在映射 404，重复资源映射 409。`frame.jpg` 从 Orchestrator 获取帧，`cv2.imencode('.jpg', frame)` 后返回 `image/jpeg` 和 `Cache-Control: no-store`；没有可用画面时返回 503，而非伪造成功。

- [ ] **Step 4: 注册 router 并运行测试**

Run: `cd AiVision && pytest tests/test_logistics_channel_api.py tests/test_logistics_monitor_status_api.py tests/test_camera_frame_response.py -v`

Expected: PASS，旧单摄像头状态和帧接口仍兼容。

- [ ] **Step 5: 提交**

```bash
git add AiVision/api/v2/logistics_channels.py AiVision/api/app.py AiVision/api/deps.py AiVision/tests/test_logistics_channel_api.py
git commit -m "feat: expose logistics channel api"
```

### Task 8: 让统一告警接口识别物流通道主体

**Files:**
- Modify: `AiVision/api/v2/alarms.py`
- Modify: `unified_backend/app.py:270-330`
- Test: `unified_backend/tests/test_logistics_channel_alarms.py`

- [ ] **Step 1: 写告警归一化失败测试**

```python
def test_aivision_channel_alarm_keeps_channel_identity():
    alarm = normalize_aivision_alarm({
        "id": "42",
        "event_type": "detect_logistics_single_person",
        "subject_type": "logistics_channel",
        "subject_id": "3",
        "subject_name": "一号物流通道",
        "reason": "multiple",
        "metadata": {"camera_counts": {"10": 2, "11": 1}},
    })
    assert alarm["camera_name"] == "一号物流通道"
    assert alarm["channel_id"] == "3"
    assert alarm["reason"] == "multiple"
```

- [ ] **Step 2: 运行并确认失败**

Run: `pytest unified_backend/tests/test_logistics_channel_alarms.py -v`

Expected: FAIL，现有归一化只识别 `camera_no`。

- [ ] **Step 3: 扩展 AiVision 告警响应和统一后端映射**

`AiVision/api/v2/alarms.py::_event_dict` 优先返回持久化的 `subject_*`、`reason` 和 `event_metadata`，旧记录回退摄像头字段。统一后端保留现有 `camera_name` 契约，但物流通道告警将其映射为 `subject_name`，同时增加 `channel_id/subject_type/metadata`，避免破坏现有前端告警页。

- [ ] **Step 4: 运行并确认通过**

Run: `pytest unified_backend/tests/test_logistics_channel_alarms.py unified_backend/tests/test_guard_room_sites.py -v`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add AiVision/api/v2/alarms.py unified_backend/app.py unified_backend/tests/test_logistics_channel_alarms.py
git commit -m "feat: expose logistics channel alarm metadata"
```

### Task 9: 增加前端物流通道客户端和状态 Hook

**Files:**
- Create: `unified_frontend/src/components/logistics_single_person/types.ts`
- Create: `unified_frontend/src/components/logistics_single_person/api.ts`
- Create: `unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts`
- Modify: `unified_frontend/src/lib/api.ts`
- Test: `unified_frontend/tests/logistics-channel-api-contract.test.mjs`

- [ ] **Step 1: 写客户端契约失败测试**

```javascript
test('logistics channel client uses canonical v2 resources', () => {
  const source = read('src/components/logistics_single_person/api.ts')
  assert.match(source, /\/api\/v2\/logistics-channels/)
  assert.match(source, /credentials:\s*['"]include['"]/)
  assert.match(source, /frame\.jpg/)
})
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd unified_frontend && node --test tests/logistics-channel-api-contract.test.mjs`

Expected: FAIL，客户端文件不存在。

- [ ] **Step 3: 定义前端类型和 API**

```typescript
export type LogisticsChannelReason = 'normal' | 'empty' | 'multiple' | 'unknown' | 'unconfigured' | 'inactive'

export type LogisticsChannelStatus = {
  channelId: number
  channelName: string
  feature: LogisticsFeatureName
  reason: LogisticsChannelReason
  alarm: boolean
  durationSeconds: number
  thresholdSeconds: number | null
  cameras: LogisticsChannelCameraStatus[]
  updatedAt: string | null
}
```

实现通道 CRUD、成员创建/绑定/移动/排序/移除、配置读写、状态、通道告警、统计读取和 `logisticsChannelFrameUrl()`。JSON 请求给现有 `apiGet/apiPost/apiPut/apiDelete` 传入 `/v2/logistics-channels/...`，由 `API_PREFIX=/api` 组成规范 `/api/v2/...` 路径；帧请求保留 `credentials: 'include'`、401 通知、AbortController 和对象 URL 回收。

- [ ] **Step 4: 实现 Hook**

`useLogisticsChannels(feature)` 管理通道列表、选中通道和刷新；`useLogisticsChannelStatus(feature, channelId)` 每秒状态轮询并每 5 秒读取该通道当日告警/统计；帧轮询沿用 200ms 调度但按请求实际耗时延后，旧对象 URL 必须 revoke。切换通道时清除上一通道状态、告警和事件。

- [ ] **Step 5: 运行并确认通过**

Run: `cd unified_frontend && node --test tests/logistics-channel-api-contract.test.mjs`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add unified_frontend/src/components/logistics_single_person unified_frontend/src/lib/api.ts unified_frontend/tests/logistics-channel-api-contract.test.mjs
git commit -m "feat: add logistics channel frontend client"
```

### Task 10: 构建共享监控和配置视图

**Files:**
- Create: `unified_frontend/src/components/logistics_single_person/LogisticsChannelMonitorView.tsx`
- Create: `unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx`
- Create: `unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx`
- Test: `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`

- [ ] **Step 1: 写 UI 契约失败测试**

断言共享 section 包含物流通道选择、状态卡、拼接帧、离线成员列表；配置视图包含新增通道、新增/绑定已有摄像头、排序、逐路 ROI、开始/结束时间和两类持续时间；viewer 控件由 `isAdmin` 禁用。

```javascript
assert.match(section, /LogisticsChannelMonitorView/)
assert.match(config, /新增物流通道/)
assert.match(config, /每日检测开始时间/)
assert.match(config, /逐路 ROI/)
assert.match(config, /isAdmin/)
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd unified_frontend && node --test tests/logistics-channel-ui-contract.test.mjs`

Expected: FAIL，共享视图不存在。

- [ ] **Step 3: 实现监控视图**

状态卡显示通道状态、在线/离线数、各路人数和今日通道告警数；主画面只显示后端拼接 JPEG；成员列表将 `unknown` 区分为离线、结果过期和等待结果。状态色固定：正常绿色、无人/多人红色、未知橙色、停用/未配置灰色。

- [ ] **Step 4: 实现配置视图**

通道管理与成员管理分区；新增摄像头表单包含名称、RTSP、FPS，已有摄像头选择器只显示当前 feature 可绑定项；成员顺序使用明确的上移/下移操作，不新增拖拽依赖。选择成员后复用现有 `AiVisionRoiEditor` 读取该摄像头最新帧和 feature 配置，只保存摄像头级 ROI/推理过滤字段。通道规则表单保存时间、持续时间、告警间隔和告警渠道。

- [ ] **Step 5: 运行并确认通过**

Run: `cd unified_frontend && node --test tests/logistics-channel-ui-contract.test.mjs tests/logistics-single-person-monitor-contract.test.mjs`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add unified_frontend/src/components/logistics_single_person/LogisticsChannelMonitorView.tsx unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx unified_frontend/src/components/logistics_single_person/LogisticsChannelSection.tsx unified_frontend/tests/logistics-channel-ui-contract.test.mjs
git commit -m "feat: add logistics channel management views"
```

### Task 11: 用共享容器替换四套重复页面

**Files:**
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonElectronicsElectricianDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonElectricalComponentsDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/LogisticsSinglePersonPreciousMetalRecyclingDetectionSection.tsx`
- Modify: `unified_frontend/tests/logistics-single-person-monitor-contract.test.mjs`
- Test: `unified_frontend/tests/logistics-channel-ui-contract.test.mjs`

- [ ] **Step 1: 更新页面复用失败测试**

```javascript
for (const page of logisticsPages) {
  const source = read(page.path)
  assert.match(source, /LogisticsChannelSection/)
  assert.match(source, new RegExp(page.feature))
  assert.doesNotMatch(source, /requestLogisticsSinglePersonConfig/)
}
```

- [ ] **Step 2: 运行并确认失败**

Run: `cd unified_frontend && node --test tests/logistics-channel-ui-contract.test.mjs tests/logistics-single-person-monitor-contract.test.mjs`

Expected: FAIL，四个 section 仍保留重复摄像头级逻辑。

- [ ] **Step 3: 将四个 section 缩减为参数包装器**

```tsx
export function LogisticsSinglePersonDetectionSection() {
  return (
    <LogisticsChannelSection
      feature="detect_logistics_single_person"
      title="物流通道单人检测监控与配置"
    />
  )
}
```

其余三个文件分别传入已有完整 feature 名称和部门标题。删除页面内重复请求、表单和监控状态逻辑，但不改变 `App.tsx` 的懒加载导出名称、导航 ID 或权限 ID。

- [ ] **Step 4: 运行前端测试和构建**

Run: `cd unified_frontend && node --test tests/logistics-channel-api-contract.test.mjs tests/logistics-channel-ui-contract.test.mjs tests/logistics-single-person-monitor-contract.test.mjs`

Expected: PASS。

Run: `cd unified_frontend && npm run build`

Expected: TypeScript 编译和 Vite 构建成功。

- [ ] **Step 5: 提交**

```bash
git add unified_frontend/src/sections/LogisticsSinglePerson* unified_frontend/tests
git commit -m "refactor: unify logistics channel pages"
```

### Task 12: 完整回归、迁移演练和文档收尾

**Files:**
- Modify: `README.md`
- Modify: `run_guide.txt`
- Modify: `docs/superpowers/specs/2026-08-07-logistics-channel-multicamera-design.md` only if implementation revealed a necessary factual correction

- [ ] **Step 1: 运行 AiVision 物流和编排测试**

Run: `cd AiVision && pytest tests/test_logistics_channel_state.py tests/test_logistics_channel_compositor.py tests/test_logistics_channel_service.py tests/test_logistics_channel_runtime.py tests/test_logistics_channel_api.py tests/test_logistics_single_person.py tests/test_logistics_monitor_status_api.py tests/test_orchestrator_camera_update.py tests/test_orchestrator_camera_frame.py tests/test_alarm_config_hot_update.py -v`

Expected: PASS，无失败或错误。

- [ ] **Step 2: 运行统一后端回归**

Run: `pytest unified_backend/tests/test_logistics_channel_alarms.py unified_backend/tests/test_guard_room_sites.py unified_backend/tests/test_async_proxy.py -v`

Expected: PASS。

- [ ] **Step 3: 运行前端测试、lint 和构建**

Run: `cd unified_frontend && node --test tests/logistics-channel-api-contract.test.mjs tests/logistics-channel-ui-contract.test.mjs tests/logistics-single-person-monitor-contract.test.mjs`

Expected: PASS。

Run: `cd unified_frontend && npm run lint`

Expected: 无 ESLint error。

Run: `cd unified_frontend && npm run build`

Expected: 成功生成 `dist`。

- [ ] **Step 4: 在隔离测试库演练迁移**

准备至少两个不同物流 feature 的旧摄像头配置，连续调用两次 `migrate_existing_feature_cameras()`；确认第一次为每个已启用摄像头创建一个通道，第二次创建数为 0，ROI 和启用状态不变。不得直接在正式数据库上试跑。

- [ ] **Step 5: 更新运行文档**

在 README 和运行指南记录：物流通道入口、最多 9 路、自动布局、独立 ROI、通道级时间/阈值、离线未知规则、环境项 `LOGISTICS_STATUS_STALE_SECONDS`，以及旧摄像头自动迁移行为。

- [ ] **Step 6: 检查最终差异和未提交文件**

Run: `git diff --check && git status --short`

Expected: `git diff --check` 无输出；状态只包含本任务预期文档变更。

- [ ] **Step 7: 提交文档**

```bash
git add README.md run_guide.txt docs/superpowers/specs/2026-08-07-logistics-channel-multicamera-design.md
git commit -m "docs: document logistics channel monitoring"
```

## 实施完成标准

- 四个物流单人检测模块均按物流通道显示和配置；
- 每个通道可以管理 1–9 路摄像头并逐路设置 ROI；
- 两路各 1 人不报警，任一路 2 人或更多报警，全部明确为 0 人报警；
- 离线或过期结果不会被当作 0 人；
- 每日检测时间和持续阈值由通道级前端配置；
- 告警记录和截图以物流通道为主体并保留各路人数；
- 旧摄像头幂等迁移且不丢失 ROI；
- 后端测试、统一后端回归、前端契约、lint 和构建全部通过；
- 若缺少 GPU、模型或 RTSP，只允许真实推理/实时流人工集成项标记未验证，不能跳过纯逻辑、接口和构建验证。
