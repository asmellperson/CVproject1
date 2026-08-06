# Unified Feature Monitor Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the intrusion, face, phone, and door realtime monitor tabs with one shared human-dwell-style dashboard while preserving every backend API, configuration handler, video-frame lifecycle, ROI/line coordinate, and detection behavior.

**Architecture:** Add a pure feature-profile/alarm-summary layer, one serial alarm-polling hook, and one shared presentation component. `AiVisionMonitor` remains the owner of cameras, config, JPEG frame polling, Blob cleanup, source image dimensions, and overlays; the four Section components only opt into the new presentation and restyle their outer title/tabs.

**Tech Stack:** React 19, TypeScript 5.9, Tailwind CSS, lucide-react, Node test runner, TypeScript transpile API, Vite

---

### Task 1: Define feature profiles and executable alarm-summary behavior

**Files:**
- Create: `unified_frontend/src/components/feature_dashboard/monitorState.ts`
- Create: `unified_frontend/tests/feature-monitor-dashboards.test.mjs`

- [x] **Step 1: Write the failing executable state tests and source contracts**

Create a Node test which transpiles the pure TypeScript state module with the installed `typescript` package, imports it from a data URL, and verifies actual behavior:

```js
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')
const stateSource = await read('src/components/feature_dashboard/monitorState.ts').catch(() => '')

async function importTypeScript(source) {
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

test('filters current-camera local-day alarms and caps recent alarms at five', async () => {
  const { buildFeatureAlarmSummary } = await importTypeScript(stateSource)
  const now = new Date('2026-08-06T12:00:00+08:00')
  const matching = Array.from({ length: 6 }, (_, index) => ({
    id: `match-${index}`,
    event_type: 'detect_phone',
    camera_no: 'cam3',
    camera_name: '研究院入口',
    reason: 'phone',
    confidence: 0.9,
    created_at: `2026-08-06T0${index}:00:00+08:00`,
  }))
  const ignored = [
    { ...matching[0], id: 'other-camera', camera_no: 'cam4' },
    { ...matching[0], id: 'other-feature', event_type: 'detect_face' },
    { ...matching[0], id: 'yesterday', created_at: '2026-08-05T23:00:00+08:00' },
  ]
  const summary = buildFeatureAlarmSummary([...matching, ...ignored], 'detect_phone', 'cam3', '研究院入口', now)
  assert.equal(summary.todayCount, 6)
  assert.equal(summary.recent.length, 5)
  assert.equal(summary.recent[0].id, 'match-5')
})

test('uses camera name only when camera_no is absent', async () => {
  const { buildFeatureAlarmSummary } = await importTypeScript(stateSource)
  const alarms = [
    { id: 'fallback', event_type: 'blocks', camera_name: '北门', reason: 'alarm', confidence: 1, created_at: '2026-08-06T10:00:00+08:00' },
    { id: 'wrong-key', event_type: 'blocks', camera_no: 'cam9', camera_name: '北门', reason: 'alarm', confidence: 1, created_at: '2026-08-06T11:00:00+08:00' },
  ]
  const summary = buildFeatureAlarmSummary(alarms, 'blocks', 'cam1', '北门', new Date('2026-08-06T12:00:00+08:00'))
  assert.deepEqual(summary.recent.map((alarm) => alarm.id), ['fallback'])
})
```

Add source assertions for all four feature keys and profile labels. These assertions must fail while the new files do not exist.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd unified_frontend
node tests/feature-monitor-dashboards.test.mjs
```

Expected: FAIL because `buildFeatureAlarmSummary` and feature profiles are missing.

- [x] **Step 3: Implement the pure feature profiles and alarm summary**

Create `monitorState.ts` with no runtime imports:

```ts
import type { AlarmEvent } from '@/lib/api'

export type FeatureDashboardKey = 'blocks' | 'detect_face' | 'detect_phone' | 'detect_door'

export type FeatureDashboardProfile = {
  pageTitle: string
  pageSubtitle: string
  videoTitle: string
  metricLabel: string
  eventLabel: string
  overlayLabel: string
}

export const FEATURE_DASHBOARD_PROFILES: Record<FeatureDashboardKey, FeatureDashboardProfile> = {
  blocks: {
    pageTitle: '区域入侵检测监控与配置',
    pageSubtitle: '警戒区域实时监控面板',
    videoTitle: '区域入侵检测监控',
    metricLabel: '警戒方向',
    eventLabel: '入侵告警',
    overlayLabel: 'alarm_line',
  },
  detect_face: {
    pageTitle: '人脸检测监控与配置',
    pageSubtitle: '人脸识别实时监控面板',
    videoTitle: '人脸检测监控',
    metricLabel: '人脸置信度阈值',
    eventLabel: '人脸告警',
    overlayLabel: 'face_roi',
  },
  detect_phone: {
    pageTitle: '手机识别检测监控与配置',
    pageSubtitle: '手机使用识别监控面板',
    videoTitle: '手机识别检测监控',
    metricLabel: '确认持续时间',
    eventLabel: '手机告警',
    overlayLabel: 'phone_roi',
  },
  detect_door: {
    pageTitle: '大门开关检测监控与配置',
    pageSubtitle: '大门状态异常监控面板',
    videoTitle: '大门开关检测监控',
    metricLabel: '首次告警时间',
    eventLabel: '大门告警',
    overlayLabel: 'door_roi',
  },
}

function isSameLocalDay(value: string | undefined, now: Date) {
  if (!value) return false
  const parsed = new Date(value)
  return !Number.isNaN(parsed.getTime())
    && parsed.getFullYear() === now.getFullYear()
    && parsed.getMonth() === now.getMonth()
    && parsed.getDate() === now.getDate()
}

export function buildFeatureAlarmSummary(
  alarms: AlarmEvent[],
  feature: FeatureDashboardKey,
  cameraKey: string,
  cameraName: string,
  now = new Date(),
) {
  const today = alarms
    .filter((alarm) => alarm.event_type === feature)
    .filter((alarm) => alarm.camera_no === cameraKey || (!alarm.camera_no && alarm.camera_name === cameraName))
    .filter((alarm) => isSameLocalDay(alarm.created_at, now))
    .sort((left, right) => new Date(right.created_at || 0).getTime() - new Date(left.created_at || 0).getTime())
  return { todayCount: today.length, recent: today.slice(0, 5) }
}
```

- [x] **Step 4: Re-run the focused state tests**

Run `node tests/feature-monitor-dashboards.test.mjs`.

Expected: state behavior tests pass; later source contracts remain RED until the hook/view/integration exist.

### Task 2: Add serial alarm polling without adding an API

**Files:**
- Create: `unified_frontend/src/components/feature_dashboard/useFeatureDashboardAlarms.ts`
- Modify: `unified_frontend/tests/feature-monitor-dashboards.test.mjs`

- [x] **Step 1: Add failing hook contracts**

Assert that the hook:

```js
assert.match(hook, /getAlarms\(1000, \[feature\]\)/)
assert.match(hook, /window\.setTimeout\(loadAlarms, ALARM_POLL_MS\)/)
assert.match(hook, /setAlarmState\(null\)/)
assert.doesNotMatch(hook, /window\.setInterval/)
```

- [x] **Step 2: Run the focused test and verify the hook assertions fail**

Run `node tests/feature-monitor-dashboards.test.mjs`.

Expected: FAIL because the hook does not exist.

- [x] **Step 3: Implement serialized polling and camera isolation**

Create a hook with this public contract:

```ts
export function useFeatureDashboardAlarms({
  enabled,
  feature,
  selectedCamera,
  selectedCameraName,
}: {
  enabled: boolean
  feature: FeatureDashboardKey
  selectedCamera: string
  selectedCameraName: string
})
```

The hook must:

```ts
const ALARM_POLL_MS = 5000

useEffect(() => {
  setAlarmState(null)
}, [enabled, feature, selectedCamera])

useEffect(() => {
  if (!enabled || !selectedCamera) return
  let mounted = true
  let timer: number | undefined
  const loadAlarms = async () => {
    try {
      const value = await getAlarms(1000, [feature])
      if (mounted) setAlarmState({ cameraKey: selectedCamera, value })
    } catch {
      // Keep the latest successful list for this camera.
    } finally {
      if (mounted) timer = window.setTimeout(loadAlarms, ALARM_POLL_MS)
    }
  }
  loadAlarms()
  return () => {
    mounted = false
    if (timer !== undefined) window.clearTimeout(timer)
  }
}, [enabled, feature, selectedCamera])
```

Use `buildFeatureAlarmSummary` in `useMemo`, and expose `{ todayCount, recent }` only when the stored camera key matches the currently selected camera.

- [x] **Step 4: Re-run the focused test**

Run `node tests/feature-monitor-dashboards.test.mjs`.

Expected: state and hook contracts pass.

### Task 3: Build the shared dashboard and integrate it with `AiVisionMonitor`

**Files:**
- Create: `unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx`
- Modify: `unified_frontend/src/components/AiVisionMonitor.tsx`
- Modify: `unified_frontend/tests/feature-monitor-dashboards.test.mjs`

- [x] **Step 1: Add failing view and frame-preservation contracts**

Assert these exact visual/data boundaries:

```js
for (const label of ['摄像头状态', '启用摄像头', '监控对象', '判定说明', '最近报警']) {
  assert.match(view, new RegExp(label))
}
assert.match(view, /grid grid-cols-2 gap-4 lg:grid-cols-4/)
assert.match(view, /grid gap-5 lg:grid-cols-3/)
assert.match(view, /lg:col-span-2/)
assert.match(view, /#22D3EE/)
assert.match(view, /rgba\(34,211,238,0\.10\)/)
assert.match(view, /bg-black\/45/)
assert.match(view, /from-black\/30 via-transparent to-black\/15/)
assert.match(monitor, /presentation\?: 'default' \| 'logistics-single-person' \| 'human-dwell' \| 'feature-dashboard'/)
assert.match(monitor, /buildAiVisionPreviewFrameUrl\(selectedCamera, feature, Date\.now\(\)\)/)
assert.match(monitor, /window\.setTimeout\(loadFrame, Math\.max\(0, FRAME_REFRESH_MS - elapsed\)\)/)
assert.match(monitor, /scheduleFrameRequestAbort\(controller, FRAME_REQUEST_TIMEOUT_MS\)/)
assert.match(monitor, /URL\.revokeObjectURL/)
assert.match(monitor, /image\.naturalWidth/)
```

- [x] **Step 2: Run the focused test and verify RED**

Run `node tests/feature-monitor-dashboards.test.mjs`.

Expected: FAIL for the missing view and presentation.

- [x] **Step 3: Implement the shared pure view**

Define props that receive existing state rather than fetching:

```ts
export type FeatureDashboardMonitorViewProps = {
  feature: FeatureDashboardKey
  cameras: AiVisionCamera[]
  selectedCamera: string
  selectedCameraInfo?: AiVisionCamera
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  featureValue: Record<string, unknown> | null
  alarms: AlarmEvent[]
  todayAlarmCount: number
  roiPolygons: OverlayPoint[][]
  alarmLines: [OverlayPoint, OverlayPoint][]
  imageSize: { width: number; height: number }
  onSelectCamera: (cameraKey: string) => void
  onRefreshCameras: () => void
}
```

Add a pure metric formatter:

```ts
function formatBusinessMetric(feature: FeatureDashboardKey, value: Record<string, unknown> | null) {
  if (feature === 'blocks') {
    const side = Number(value?.alarm_side)
    return side === 1 ? '线左侧' : side === -1 ? '线右侧' : '--'
  }
  if (feature === 'detect_face') {
    const threshold = Number(value?.FACE_SCORE_THR)
    return Number.isFinite(threshold) ? threshold.toFixed(2) : '--'
  }
  if (feature === 'detect_phone') {
    const seconds = Number(value?.MIN_CONFIRM_SECONDS)
    return Number.isFinite(seconds) ? `${seconds} 秒` : '--'
  }
  const seconds = Number(value?.first_alarm)
  return Number.isFinite(seconds) ? `${seconds} 秒` : '--'
}
```

Render:

- four cards: frame connection, `cameras.length`, profile metric, selected-camera today alarm count;
- left cards: current camera select/refresh, profile-specific static rule rows, five alarm timeline entries;
- video header: profile video title, camera key/name, FPS, LIVE/offline;
- glass pills: realtime detection, camera online/offline, profile-specific status label;
- cyan polygons with `preserveAspectRatio="xMidYMid meet"` and source `viewBox`;
- red `alarmLines` without changing endpoints or coordinate conversion;
- vignette, browser timestamp, and a small realtime-frame badge;
- `pointer-events-none` on every overlay.

- [x] **Step 4: Integrate the presentation without touching the frame effect**

In `AiVisionMonitor.tsx`:

```ts
type AiVisionMonitorProps = {
  title: string
  feature: string
  department?: string
  presentation?: 'default' | 'logistics-single-person' | 'human-dwell' | 'feature-dashboard'
}
```

Enable the alarm hook only when the presentation is `feature-dashboard` and the feature is one of the four profile keys. Suppress the existing generic SVG only for this presentation, then pass `overlay.polygons`, `overlay.lines`, and `imageSize` into the new view. Do not edit the frame-fetch `useEffect` or `frameContent` image element.

- [x] **Step 5: Run the focused test and production build**

Run:

```bash
cd unified_frontend
node tests/feature-monitor-dashboards.test.mjs
npm run build
```

Expected: all focused tests pass and Vite exits 0.

### Task 4: Opt the four Section pages into the approved layout

**Files:**
- Modify: `unified_frontend/src/sections/IntrusionDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/FaceDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/PhoneDetectionSection.tsx`
- Modify: `unified_frontend/src/sections/DoorDetectionSection.tsx`
- Modify: `unified_frontend/tests/feature-monitor-dashboards.test.mjs`

- [x] **Step 1: Add failing Section contracts**

For each file, assert the approved title, subtitle, `presentation="feature-dashboard"`, `#F3F5FA` page background, rounded primary Tabs, and unchanged config symbols:

```js
const expected = [
  ['IntrusionDetectionSection.tsx', '区域入侵检测监控与配置', '警戒区域实时监控面板'],
  ['FaceDetectionSection.tsx', '人脸检测监控与配置', '人脸识别实时监控面板'],
  ['PhoneDetectionSection.tsx', '手机识别检测监控与配置', '手机使用识别监控面板'],
  ['DoorDetectionSection.tsx', '大门开关检测监控与配置', '大门状态异常监控面板'],
]
for (const [file, title, subtitle] of expected) {
  const source = await read(`src/sections/${file}`)
  assert.match(source, new RegExp(title))
  assert.match(source, new RegExp(subtitle))
  assert.match(source, /presentation="feature-dashboard"/)
  assert.match(source, /bg-\[#F3F5FA\]/)
  for (const binding of ['loadConfig', 'loadCameras', 'saveConfig', 'addCameraToFeature', 'removeCameraFromFeature', 'FeatureCameraManager', 'AiVisionRoiEditor', 'AiVisionModelConfig', 'AlarmPushConfig']) {
    assert.match(source, new RegExp(binding))
  }
}
```

- [x] **Step 2: Run the focused test and verify RED**

Run `node tests/feature-monitor-dashboards.test.mjs`.

Expected: FAIL because the four pages still use the old outer layout.

- [x] **Step 3: Restyle only each Section's outer monitor shell**

Use these exact replacement fragments in `IntrusionDetectionSection.tsx` while leaving its existing configuration `TabsContent` untouched:

```tsx
<div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 sm:p-5 lg:p-6">
  <Tabs defaultValue="monitor" className="space-y-5">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-black tracking-tight text-slate-950 sm:text-[28px]">区域入侵检测监控与配置</h1>
        <p className="mt-1 text-sm text-slate-500 sm:text-base">警戒区域实时监控面板</p>
      </div>
      <TabsList className="grid h-auto w-full shrink-0 grid-cols-2 rounded-full border border-slate-200/70 bg-white p-1 shadow-sm sm:w-auto">
        <TabsTrigger value="monitor" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">实时监控</TabsTrigger>
        <TabsTrigger value="config" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">配置管理</TabsTrigger>
      </TabsList>
    </div>
    <TabsContent value="monitor" className="mt-0 space-y-5">
      <AiVisionMonitor title="区域入侵检测监控" feature="blocks" presentation="feature-dashboard" />
    </TabsContent>
    <TabsContent value="config" className="mt-0 space-y-6">
```

After this opening tag, keep the exact nested configuration `Tabs` expression already present in the file and retain its existing closing tags. Apply the same wrapper to the other files with these exact values:

| File | Heading | Subtitle | `AiVisionMonitor` title | Feature |
|---|---|---|---|---|
| `FaceDetectionSection.tsx` | 人脸检测监控与配置 | 人脸识别实时监控面板 | 人脸检测监控 | `detect_face` |
| `PhoneDetectionSection.tsx` | 手机识别检测监控与配置 | 手机使用识别监控面板 | 手机识别检测监控 | `detect_phone` |
| `DoorDetectionSection.tsx` | 大门开关检测监控与配置 | 大门状态异常监控面板 | 大门开关检测监控 | `detect_door` |

Do not reformat, move, or edit nested configuration content or its handlers in any of the four files.

- [x] **Step 4: Run focused and full frontend verification**

Run:

```bash
cd unified_frontend
node tests/feature-monitor-dashboards.test.mjs
node --test tests/*.test.mjs
npm run build
npm run lint
```

Expected: all tests/build pass; lint exits 0 with no new warning in modified files. The four known logistics Section exhaustive-deps warnings may remain.

### Task 5: Review scope, verify no backend changes, and commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-06-feature-monitor-dashboards.md` (mark completed checkboxes)
- Review: all files listed above

- [x] **Step 1: Prove backend and unrelated frontend files are untouched**

Run:

```bash
git status --short
git diff --name-only
```

Expected: only the plan, four Section files, `AiVisionMonitor.tsx`, the new `feature_dashboard` files, and the new frontend test are listed. No `AiVision/` path appears.

- [x] **Step 2: Verify the preserved frame/config behavior in the diff**

Run:

```bash
git diff -- unified_frontend/src/components/AiVisionMonitor.tsx
git diff -- unified_frontend/src/sections/IntrusionDetectionSection.tsx unified_frontend/src/sections/FaceDetectionSection.tsx unified_frontend/src/sections/PhoneDetectionSection.tsx unified_frontend/src/sections/DoorDetectionSection.tsx
git diff --check
```

Expected: the frame-fetch effect and all nested configuration handlers are unchanged; `git diff --check` exits 0.

- [x] **Step 3: Request independent code review**

Ask the reviewer to check profile correctness, selected-camera alarm isolation, stale request behavior, ROI/line geometry, frame lifecycle preservation, config handler preservation, and absence of backend modifications. Fix every valid Critical or Important finding, then re-run Step 4 verification from Task 4.

- [x] **Step 4: Commit only the approved frontend work**

```bash
git add -- \
  docs/superpowers/plans/2026-08-06-feature-monitor-dashboards.md \
  unified_frontend/src/components/AiVisionMonitor.tsx \
  unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx \
  unified_frontend/src/components/feature_dashboard/monitorState.ts \
  unified_frontend/src/components/feature_dashboard/useFeatureDashboardAlarms.ts \
  unified_frontend/src/sections/IntrusionDetectionSection.tsx \
  unified_frontend/src/sections/FaceDetectionSection.tsx \
  unified_frontend/src/sections/PhoneDetectionSection.tsx \
  unified_frontend/src/sections/DoorDetectionSection.tsx \
  unified_frontend/tests/feature-monitor-dashboards.test.mjs
git commit -m "feat: unify feature monitor dashboards"
```

Expected: one commit containing only the approved frontend implementation and its plan/tests. Do not push or move the V4 tag unless the user explicitly requests it.
