import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import vm from 'node:vm'

const root = new URL('../src/', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')
const page = await read('sections/GuardBehaviorSection.tsx')
const monitor = await read('components/guard_behavior/GuardMonitorView.tsx')
const config = await read('components/guard_behavior/GuardConfigView.tsx')
const ui = await read('components/guard_behavior/GuardMonitorUi.tsx')

test('preserves shared detection styling, five config categories and resizable monitor', () => {
  assert.match(page, /DetectionPageHeader title="保安行为规范检测"/)
  assert.match(page, /departmentLabel=\{DEPARTMENT_LABELS\[department\]\}/)
  assert.match(page, /guard-site-selector/)
  assert.match(monitor, /<ResizableMonitorLayout id="guard-behavior"/)
  assert.equal((config.match(/<DetectionConfigTab value=/g) ?? []).length, 5)
  for (const label of ['保安室管理', '摄像头', '检测参数', '模型配置', '报警推送']) assert.ok(config.includes(label))
  for (const name of ['GuardMonitorStatCard', 'GuardDetectionStatusRow', 'GuardVideoStatusPill']) assert.ok(ui.includes(`export function ${name}`))
  assert.doesNotMatch(ui, /fetch\(/)
  assert.match(monitor, /block h-auto w-full object-contain/)
})

test('native configuration has no old backend contract or runtime controls', async () => {
  const directory = new URL('components/guard_behavior/', root)
  const files = await readdir(directory)
  const sources = await Promise.all(files.filter((name) => /\.(ts|tsx)$/.test(name)).map((name) => readFile(new URL(name, directory), 'utf8')))
  const combined = [page, await read('lib/api.ts'), ...sources].join('\n')
  assert.doesNotMatch(combined, /\/guard-room\/|AppConfigPayload|waitUntilRunning|RuntimeControl|rtsp_url|source_cam|vehicle_unattended/)
  assert.doesNotMatch(combined, /startGuard|stopGuard|restartGuard|\/control\//)
  assert.match(config, /<AiVisionModelConfig requiredModels=\{GUARD_MODELS\}/)
  for (const name of ['yolo_guard_person_phone', 'guard_uniform', 'yolo_guard_pose', 'yolo_vehicle']) assert.ok(config.includes(name))
  assert.match(await read('components/guard_behavior/VehicleRoiEditor.tsx'), /aiVisionFrameUrl\(String\(cameraId\)/)
  assert.match(await read('components/guard_behavior/VehicleRoiEditor.tsx'), /points.length === 0 \|\| points.length >= 3/)
})

test('policy controls cover every numeric API field and use server defaults', async () => {
  const fields = await read('components/guard_behavior/policyFields.ts')
  const types = await read('components/guard_behavior/types.ts')
  const policy = types.match(/export type SitePolicyValues = \{([\s\S]*?)\n\}/)[1]
  for (const match of policy.matchAll(/^  (\w+): number$/gm)) assert.ok(fields.includes(`key: '${match[1]}'`), match[1])
  assert.doesNotMatch(fields, /defaultValue|DEFAULT_CONFIG/)
})

function nodes(tree) {
  if (tree == null || typeof tree === 'boolean') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (typeof tree !== 'object') return [tree]
  return [tree, ...nodes(tree.props?.children)]
}
function harness() {
  const states = [], refs = [], polls = [], cleanups = [], revoked = []
  let cursor = 0, refCursor = 0
  const unknown = { state: 'unknown', availability: 'unavailable', reason: '尚无数据', offending_camera_ids: [] }
  let status = { running: false, status: 'unavailable', camera_states: {}, updated_at: null, absence: unknown, phone: unknown, prone: unknown, vehicle: unknown }
  let frameResponse = { ok: false, status: 503 }
  const context = {
    exports: {}, Date, AbortController,
    URL: { createObjectURL: () => 'blob:frame', revokeObjectURL: (url) => revoked.push(url) },
    fetch: async () => frameResponse,
    require(name) {
      if (name === 'react') return {
        useState(initial) { const id = cursor++; if (!(id in states)) states[id] = initial; return [states[id], (value) => { states[id] = value }] },
        useRef(initial) { const id = refCursor++; if (!(id in refs)) refs[id] = { current: initial }; return refs[id] },
        useEffect(effect) { cleanups.push(effect()) },
      }
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
      if (name === '@/hooks/use-serial-poll') return { useSerialPoll: (task, options) => polls.push({ task, options }) }
      if (name === './api') return { getSiteStatus: async () => status, getMembers: async () => [{ camera_id: 7, name: '大门', member_enabled: true, physical_enabled: true }], siteFrameUrl: () => '/api/guard-behavior/sites/1/frame.jpg' }
      return new Proxy({}, { get: (_, key) => String(key) })
    },
  }
  vm.runInNewContext(ts.transpileModule(monitor, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, context)
  return {
    polls, revoked, setStatus: (next) => { status = next }, setFrame: (next) => { frameResponse = next },
    render() { cursor = 0; refCursor = 0; polls.length = 0; return context.exports.GuardMonitorView({ site: { id: 1, name: '南门' } }) },
    cleanup() { cleanups.forEach((cleanup) => cleanup?.()) },
  }
}

test('monitor renders unavailable without inventing presence or polling empty frames', async () => {
  const h = harness()
  h.render(); await h.polls[0].task(new AbortController().signal)
  const tree = h.render()
  assert.equal(h.polls[1].options.enabled, false)
  assert.ok(nodes(tree).some((node) => node?.props?.value === '未运行 / 不可用'))
  assert.ok(nodes(tree).filter((node) => node?.type === 'GuardDetectionStatusRow').every((node) => node.props.stateLabel === '未知'))
  assert.equal(nodes(tree).filter((node) => node?.type === 'img').length, 0)
})

test('live frame and positive rule display clear on availability loss', async () => {
  const h = harness()
  const normal = { state: 'normal', availability: 'available', reason: '正常', offending_camera_ids: [] }
  h.setStatus({ running: true, status: 'healthy', updated_at: 100, camera_states: { 7: 'READY' }, absence: normal, phone: { ...normal, state: 'alarm', offending_camera_ids: [7] }, prone: normal, vehicle: { ...normal, state: 'idle' } })
  h.render(); await h.polls[0].task(new AbortController().signal)
  h.render(); assert.equal(h.polls[1].options.enabled, true)
  h.setFrame({ ok: true, blob: async () => ({}) })
  await h.polls[1].task(new AbortController().signal)
  let tree = h.render()
  assert.equal(nodes(tree).find((node) => node?.type === 'img').props.src, 'blob:frame')
  assert.equal(nodes(tree).find((node) => node?.type === 'GuardDetectionStatusRow' && node.props.label === '手机').props.state, 'danger')
  h.polls[0].options.onError(new Error('network down'))
  tree = h.render()
  assert.equal(h.polls[1].options.enabled, false)
  assert.equal(nodes(tree).filter((node) => node?.type === 'img').length, 0)
  assert.deepEqual(h.revoked, ['blob:frame'])
  assert.ok(nodes(tree).some((node) => typeof node === 'string' && node.includes('network down')))
  h.cleanup()
})

test('policy numeric validation accepts valid fractional durations and pixels but enforces counts', async () => {
  const context = { exports: {} }
  vm.runInNewContext(ts.transpileModule(await read('components/guard_behavior/policyFields.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context)
  const { POLICY_GROUPS, hasInvalidPolicyNumber } = context.exports
  const value = Object.fromEntries(POLICY_GROUPS.flatMap((group) => group.fields.map((field) => [field.key, field.exclusiveMin ? .001 : field.min])))
  value.phone_near_person_px = .5
  assert.equal(hasInvalidPolicyNumber(value), false)
  for (const changes of [{ cap_interval: 0 }, { phone_seconds: 0 }, { phone_min_hits_in_window: 1.5 }, { pose_imgsz: 31 }, { pose_imgsz: 4097 }, { model_iou_threshold: 1.1 }, { vehicle_near_px: -1 }, { phone_seconds: NaN }]) {
    assert.equal(hasInvalidPolicyNumber({ ...value, ...changes }), true)
  }
})
