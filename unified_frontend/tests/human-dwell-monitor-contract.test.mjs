import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')

const api = await read('src/lib/aivision.ts')
const state = await read('src/components/human_dwell/monitorState.ts').catch(() => '')
const hook = await read('src/components/human_dwell/useHumanDwellMonitor.ts').catch(() => '')
const view = await read('src/components/human_dwell/HumanDwellMonitorView.tsx').catch(() => '')
const monitor = await read('src/components/AiVisionMonitor.tsx')
const page = await read('src/sections/HumanDetectionSection.tsx')
const haodaPage = await read('src/sections/HaodaHumanDetectionSection.tsx')
const home = await read('src/sections/HomeSection.tsx')
const alarms = await read('src/sections/AlarmsSection.tsx')
const statistics = await read('src/sections/StatisticsSection.tsx')
const cameraManager = await read('src/components/FeatureCameraManager.tsx')
const nav = await read('src/lib/nav.ts')
const sidebar = await read('src/components/Sidebar.tsx')
const app = await read('src/App.tsx')

test('provides typed dwell status through the existing feature-status route', () => {
  assert.match(api, /export type AiVisionHumanDwellStatus/)
  assert.match(api, /duration_seconds: number \| null/)
  assert.match(api, /threshold_seconds: number \| null/)
  assert.match(api, /getAiVisionHumanDwellStatus/)
  assert.match(api, /features\/\$\{encodeURIComponent\(feature\)\}\/cameras\/\$\{encodeURIComponent\(cameraKey\)\}\/status/)
})

test('derives timeout and non-alarm leave events without persistence', () => {
  assert.match(state, /人员在区域内逗留 \$\{duration\} 秒，触发告警/)
  assert.match(state, /区域人数 \$\{count\}，停留 \$\{duration\} 秒后离开，未告警/)
  assert.match(state, /filterTodayHumanDwellAlarms/)
  assert.match(state, /\(alarm\.feature_name \|\| alarm\.event_type\) === feature/)
  assert.match(state, /alarm\.subject_type === 'camera'/)
  assert.match(state, /previous && !previous\.alarm/)
  assert.doesNotMatch(state, /fetch\(|localStorage|sessionStorage/)
})

test('polls status and existing alarms serially', () => {
  assert.match(hook, /getAiVisionHumanDwellStatus/)
  assert.match(hook, /getAlarms\(1000, \[feature\]\)/)
  assert.match(hook, /window\.setTimeout\(loadStatus, STATUS_POLL_MS\)/)
  assert.match(hook, /window\.setTimeout\(loadAlarms, ALARM_POLL_MS\)/)
  assert.match(hook, /setEventState\(null\)/)
  assert.match(hook, /previousRef\.current = null/)
  assert.doesNotMatch(hook, /window\.setInterval/)
})

test('renders the approved dwell dashboard and cyan ROI overlay', () => {
  for (const label of [
    '摄像头状态', '区域当前人数', '逗留阈值', '今日逗留告警次数',
    '监控对象', '判定说明', '实时事件', '人员违规逗留检测监控', '逗留超时告警',
  ]) assert.match(view, new RegExp(label))
  assert.match(view, /grid grid-cols-2 gap-4 lg:grid-cols-4/)
  assert.match(view, /ResizableMonitorLayout id="human-dwell"/)
  assert.match(view, /lg:col-span-2/)
  assert.match(view, /#22D3EE/)
  assert.match(view, /rgba\(34,211,238,0\.10\)/)
  assert.match(view, /loitering_roi/)
  assert.match(view, /bg-black\/45/)
  assert.match(view, /from-black\/30 via-transparent to-black\/15/)
  assert.match(view, /font-mono/)
  assert.match(view, /runtimeThreshold === null \? '--' :/)
})

test('preserves frame lifecycle and configuration behavior', () => {
  assert.match(monitor, /presentation\?: 'default' \| 'logistics-single-person' \| 'human-dwell' \| 'feature-dashboard'/)
  assert.match(monitor, /buildAiVisionPreviewFrameUrl\(selectedCamera, feature, Date\.now\(\)\)/)
  assert.match(monitor, /window\.setTimeout\(loadFrame, Math\.max\(0, FRAME_REFRESH_MS - elapsed\)\)/)
  assert.match(monitor, /scheduleFrameRequestAbort\(controller, FRAME_REQUEST_TIMEOUT_MS\)/)
  assert.match(monitor, /URL\.revokeObjectURL/)
  assert.match(monitor, /image\.naturalWidth/)
  assert.match(page, /DetectionPageHeader/)
  assert.match(page, /title = '人员违规逗留检测'/)
  assert.match(page, /区域逗留超时监控面板/)
  assert.match(page, /presentation="human-dwell"/)
  for (const binding of [
    'getAiVisionFeatureConfig', 'saveAiVisionFeatureConfig', 'loadConfig', 'loadCameras', 'saveConfig',
    'addCameraToFeature', 'removeCameraFromFeature', 'FeatureCameraManager', 'AiVisionRoiEditor',
  ]) assert.match(page, new RegExp(binding))
})

test('uses the personnel violation dwell name across user-facing views', () => {
  for (const source of [nav, home, page, haodaPage, view, alarms, statistics]) {
    assert.match(source, /人员违规逗留检测/)
    assert.doesNotMatch(source, /人体逗留|人员逗留检测/)
  }
})

test('offers the global camera pool without copying cameras into the Haoda feature', () => {
  assert.match(haodaPage, /feature="detect_human_haoda"/)
  assert.match(haodaPage, /department="haoda_company"/)
  assert.doesNotMatch(haodaPage, /cameraDepartment=/)
  assert.match(haodaPage, /departmentLabel="皓达公司"/)
  assert.match(page, /getAiVisionCameras\(cameraDepartment\)/)
  assert.match(page, /isAiVisionFeatureEnabled\(camera, feature\)/)
  assert.match(cameraManager, /从平台全局摄像头池选择/)
  assert.match(cameraManager, /加入当前功能不会修改摄像头的所属事业部或公司/)
  assert.match(cameraManager, /createAiVisionFeatureCamera\(feature, \{[\s\S]*?department,[\s\S]*?enabled: true/)
  assert.match(nav, /id: 'haoda-human-detection'/)
  assert.match(sidebar, /pages: departmentPermissions\.haoda_company\.pages/)
  assert.match(app, /case 'haoda-human-detection'/)
})

test('keeps the selected camera when ROI save emits a camera refresh event', () => {
  assert.match(page, /const selectedCameraRef = useRef\(''\)/)
  assert.match(page, /enabledCameras\.find\(\(camera\) => camera\.shm_name === selectedCameraRef\.current\)/)
  assert.match(page, /\|\| enabledCameras\[0\]/)
  assert.match(page, /selectedCameraRef\.current = payload\.camera\.shm_name/)
  assert.match(page, /selectedCameraRef\.current = cameraName/)
})
