import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)

async function readIfPresent(path) {
  try {
    return await readFile(new URL(path, frontendRoot), 'utf8')
  } catch (error) {
    if (error && typeof error === 'object' && error.code === 'ENOENT') return ''
    throw error
  }
}

const api = await readIfPresent('src/lib/aivision.ts')
const state = await readIfPresent('src/components/logistics_single_person/monitorState.ts')
const hook = await readIfPresent('src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts')
const view = await readIfPresent('src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx')
const monitor = await readIfPresent('src/components/AiVisionMonitor.tsx')
const logisticsPages = [
  {
    source: await readIfPresent('src/sections/LogisticsSinglePersonDetectionSection.tsx'),
    exportName: 'LogisticsSinglePersonDetectionSection',
    feature: 'detect_logistics_single_person',
    title: '物流通道单人检测监控与配置',
  },

]

test('provides typed logistics monitor status without changing the frame endpoint', () => {
  assert.match(api, /export type AiVisionLogisticsSinglePersonStatus/)
  assert.match(api, /getAiVisionLogisticsSinglePersonStatus\(cameraKey: string, feature: string\)/)
  assert.match(api, /features\/\$\{encodeURIComponent\(feature\)\}\/cameras\/\$\{encodeURIComponent\(cameraKey\)\}\/status/)
  assert.match(api, /fps\?: number/)
})

test('derives ROI single-person events without passage wording', () => {
  assert.match(state, /export function classifyLogisticsCount/)
  assert.match(state, /ROI 内人数恢复正常：1 人/)
  assert.match(state, /ROI 内无人异常：0 人/)
  assert.match(state, /ROI 内多人异常：\$\{count\} 人/)
  assert.doesNotMatch(state, /通行/)
})

test('renders the approved logistics dashboard hierarchy and states', () => {
  assert.match(view, /grid grid-cols-2 gap-4 lg:grid-cols-4/)
  assert.match(view, /ResizableMonitorLayout id="logistics-single-person"/)
  assert.match(view, /lg:col-span-2/)
  for (const label of ['摄像头状态', '当前画面人数', '摄像头数量', '今日告警次数']) {
    assert.match(view, new RegExp(label))
  }
  for (const label of ['监控对象', '判定说明', '实时事件']) {
    assert.match(view, new RegExp(label))
  }
  assert.match(view, /ROI 内 1 人/)
  assert.match(view, /ROI 内 0 人/)
  assert.match(view, /ROI 内 ≥ 2 人/)
  assert.match(view, /\{title\}/)
  assert.match(view, /人员异常告警/)
  assert.match(view, /bg-black\/45/)
  assert.match(view, /backdrop-blur/)
  assert.match(view, /from-black\/30 via-transparent to-black\/15/)
  assert.doesNotMatch(view, /通行|alarm_line|loitering_roi/)
})

test('polls display data separately while preserving the existing frame lifecycle', () => {
  assert.match(hook, /getAiVisionLogisticsSinglePersonStatus/)
  assert.match(hook, /feature: string/)
  assert.match(hook, /getAlarms\(1000, \[feature\]\)/)
  assert.match(state, /feature: string/)
  assert.match(state, /\(alarm\.feature_name \|\| alarm\.event_type\) === feature/)
  assert.match(state, /alarm\.subject_type === 'logistics_channel'/)
  assert.match(hook, /cameraChanged/)
  assert.match(hook, /window\.setTimeout\(loadStatus, STATUS_POLL_MS\)/)
  assert.match(hook, /window\.setTimeout\(loadAlarms, ALARM_POLL_MS\)/)
  assert.doesNotMatch(hook, /window\.setInterval/)

  assert.match(monitor, /buildAiVisionPreviewFrameUrl\(selectedCamera, feature, Date\.now\(\)\)/)
  assert.match(monitor, /window\.setTimeout\(loadFrame, Math\.max\(0, FRAME_REFRESH_MS - elapsed\)\)/)
  assert.match(monitor, /URL\.revokeObjectURL/)
  assert.match(monitor, /readFrameCoordinateSize\(response\.headers\)/)
  assert.match(monitor, /image\.naturalWidth/)
  assert.match(monitor, /presentation\?: 'default' \| 'logistics-single-person'/)
})

test('maps every logistics page to the shared channel section without legacy camera APIs', () => {
  const allFeatures = logisticsPages.map(({ feature }) => feature)
  assert.equal(new Set(allFeatures).size, logisticsPages.length)

  for (const { source, exportName, feature, title } of logisticsPages) {
    assert.match(source, /LogisticsChannelSection/)
    assert.match(source, new RegExp(`export function ${exportName}\\(`))
    assert.match(source, new RegExp(`feature="${feature}"`))
    assert.match(source, new RegExp(`title="${title}"`))
    assert.match(source, new RegExp(`export default ${exportName}`))

    for (const legacyBinding of [
      'requestLogisticsSinglePersonConfig',
      'getAiVisionCameras',
      'AiVisionMonitor',
      'FeatureCameraManager',
      'AiVisionRoiEditor',
      'useLogisticsSinglePersonMonitor',
    ]) {
      assert.doesNotMatch(source, new RegExp(legacyBinding))
    }
    assert.doesNotMatch(source, /logistics-single-person(?:-[a-z-]+)?-config/)
  }
})
