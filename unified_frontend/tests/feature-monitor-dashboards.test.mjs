import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')
const stateSource = await read('src/components/feature_dashboard/monitorState.ts').catch(() => '')
const hookSource = await read('src/components/feature_dashboard/useFeatureDashboardAlarms.ts').catch(() => '')
const viewSource = await read('src/components/feature_dashboard/FeatureDashboardMonitorView.tsx').catch(() => '')
const monitorSource = await read('src/components/AiVisionMonitor.tsx')

async function importTypeScript(source) {
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

test('defines the four approved feature profiles', () => {
  for (const token of [
    'blocks',
    'detect_face',
    'detect_phone',
    'detect_door',
    '区域入侵检测监控与配置',
    '人脸检测监控与配置',
    '手机识别检测监控与配置',
    '大门开关检测监控与配置',
  ]) assert.match(stateSource, new RegExp(token))
})

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

test('never exposes another camera configuration after camera switching', async () => {
  const { resolveCameraFeatureValue } = await importTypeScript(stateSource)
  const cameraAState = { cameraKey: 'cam-a', value: { threshold: 0.6 } }
  assert.deepEqual(resolveCameraFeatureValue(cameraAState, 'cam-a'), { threshold: 0.6 })
  assert.equal(resolveCameraFeatureValue(cameraAState, 'cam-b'), null)
})

test('derives configured state from the feature overlay that is actually present', async () => {
  const { isFeatureOverlayConfigured } = await importTypeScript(stateSource)
  assert.equal(isFeatureOverlayConfigured('blocks', 2, 0), false)
  assert.equal(isFeatureOverlayConfigured('blocks', 0, 1), true)
  assert.equal(isFeatureOverlayConfigured('detect_face', 0, 1), false)
  assert.equal(isFeatureOverlayConfigured('detect_face', 1, 0), true)
})

test('polls the existing alarm endpoint serially and resets on camera changes', () => {
  assert.match(hookSource, /getAlarms\(1000, \[feature\]\)/)
  assert.match(hookSource, /window\.setTimeout\(loadAlarms, ALARM_POLL_MS\)/)
  assert.match(hookSource, /setAlarmState\(null\)/)
  assert.match(hookSource, /useMemo\(\s*\(\) => {\s*const alarms =/)
  assert.doesNotMatch(hookSource, /window\.setInterval/)
})

test('renders the approved shared dashboard and source-coordinate overlays', () => {
  for (const label of ['摄像头状态', '启用摄像头', '监控对象', '判定说明', '最近报警']) {
    assert.match(viewSource, new RegExp(label))
  }
  assert.match(viewSource, /grid grid-cols-2 gap-4 lg:grid-cols-4/)
  assert.match(viewSource, /ResizableMonitorLayout id=\{`feature-dashboard-\$\{feature\}`\}/)
  assert.match(viewSource, /lg:col-span-2/)
  assert.match(viewSource, /#22D3EE/)
  assert.match(viewSource, /rgba\(34,211,238,0\.10\)/)
  assert.match(viewSource, /bg-black\/45/)
  assert.match(viewSource, /from-black\/30 via-transparent to-black\/15/)
  assert.match(viewSource, /preserveAspectRatio="xMidYMid meet"/)
  assert.match(viewSource, /pointer-events-none/)
})

test('adds a presentation without changing the existing frame lifecycle', () => {
  assert.match(monitorSource, /presentation\?: 'default' \| 'logistics-single-person' \| 'human-dwell' \| 'feature-dashboard'/)
  assert.match(monitorSource, /buildAiVisionPreviewFrameUrl\(selectedCamera, feature, Date\.now\(\)\)/)
  assert.match(monitorSource, /window\.setTimeout\(loadFrame, Math\.max\(0, FRAME_REFRESH_MS - elapsed\)\)/)
  assert.match(monitorSource, /scheduleFrameRequestAbort\(controller, FRAME_REQUEST_TIMEOUT_MS\)/)
  assert.match(monitorSource, /URL\.revokeObjectURL/)
  assert.match(monitorSource, /image\.naturalWidth/)
})

test('opts the four pages into the approved shell while preserving configuration bindings', async () => {
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
    assert.match(source, /rounded-full border border-slate-200\/70 bg-white p-1/)
    for (const binding of [
      'loadConfig', 'loadCameras', 'saveConfig', 'addCameraToFeature', 'removeCameraFromFeature',
      'FeatureCameraManager', 'AiVisionRoiEditor', 'AiVisionModelConfig', 'AlarmPushConfig',
    ]) assert.match(source, new RegExp(binding))
  }
})
