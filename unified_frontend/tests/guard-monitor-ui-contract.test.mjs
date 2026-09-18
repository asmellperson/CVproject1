import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
import vm from 'node:vm'

const root = new URL('../src/', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')
const page = await read('sections/GuardBehaviorSection.tsx')
const monitor = await read('components/guard_behavior/GuardMonitorView.tsx')
const preview = await read('components/guard_behavior/GuardCameraPreview.tsx')
const alarms = await read('components/guard_behavior/AlarmPolicies.tsx')
const config = await read('components/guard_behavior/GuardConfigView.tsx')
const ui = await read('components/guard_behavior/GuardMonitorUi.tsx')
const presentation = { exports: {} }
vm.runInNewContext(ts.transpileModule(await read('components/guard_behavior/monitorPresentation.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, presentation)

test('preserves shared detection styling, five config categories and resizable monitor', () => {
  assert.match(page, /DetectionPageHeader title="保安行为规范检测"/)
  assert.match(page, /departmentLabel=\{DEPARTMENT_LABELS\[department\]\}/)
  assert.match(page, /guard-site-selector/)
  assert.match(monitor, /<ResizableMonitorLayout id="guard-behavior"/)
  assert.equal((config.match(/<DetectionConfigTab value=/g) ?? []).length, 5)
  for (const label of ['保安室管理', '摄像头', '检测参数', '模型配置', '报警推送']) assert.ok(config.includes(label))
  for (const name of ['GuardMonitorStatCard', 'GuardDetectionStatusRow', 'GuardVideoStatusPill']) assert.ok(ui.includes(`export function ${name}`))
  assert.doesNotMatch(ui, /fetch\(/)
  assert.match(preview, /block h-auto w-full object-contain/)
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
function harness(source = monitor, exportName = 'GuardMonitorView') {
  const states = [], refs = [], polls = [], effects = [], revoked = [], requests = [], writes = []
  let isAdmin = true
  let cursor = 0, refCursor = 0, effectCursor = 0
  const unknown = { state: 'unknown', availability: 'unavailable', reason: '尚无数据', offending_camera_ids: [] }
  let status = { running: false, status: 'unavailable', camera_states: {}, camera_online: {}, updated_at: null, absence: unknown, phone: unknown, prone: unknown, vehicle: unknown }
  let members = [{ camera_id: 7, shm_name: 'camera_7', name: '大门', member_enabled: true, physical_enabled: true }]
  let frameResponse = { ok: false, status: 503 }
  const context = {
    exports: {}, Date, AbortController,
    URL: { createObjectURL: () => 'blob:frame', revokeObjectURL: (url) => revoked.push(url) },
    fetch: async (url) => { requests.push(url); return typeof frameResponse === 'function' ? frameResponse(url) : frameResponse },
    require(name) {
      if (name === 'react') return {
        useState(initial) { const id = cursor++; if (!(id in states)) states[id] = typeof initial === 'function' ? initial() : initial; return [states[id], (value) => { states[id] = typeof value === 'function' ? value(states[id]) : value }] },
        useCallback: (callback) => callback,
        useRef(initial) { const id = refCursor++; if (!(id in refs)) refs[id] = { current: initial }; return refs[id] },
        useEffect(effect, dependencies) {
          const id = effectCursor++, previous = effects[id]
          if (!previous || dependencies.some((item, index) => item !== previous.dependencies[index])) {
            previous?.cleanup?.()
            effects[id] = { dependencies, cleanup: effect() }
          }
        },
      }
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
      if (name === '@/hooks/use-serial-poll') return { useSerialPoll: (task, options) => polls.push({ task, options }) }
      if (name === '@/auth/useAuth') return { useAuth: () => ({ isAdmin }) }
      if (name === './monitorPresentation') return presentation.exports
      if (name === '@/lib/aivision') return { aiVisionFrameUrl: (key, feature) => `/api/cameras/${key}/frame.jpg${feature ? '?feature=' + feature : ''}` }
      if (name === './api') return { getSiteStatus: async () => status, getMembers: async () => members,
        updateAlarmPolicy: async (...args) => { writes.push(args) } }
      return new Proxy({}, { get: (_, key) => String(key) })
    },
  }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, context)
  return {
    polls, revoked, requests, writes, setAdmin: (next) => { isAdmin = next }, setStatus: (next) => { status = next }, setFrame: (next) => { frameResponse = next },
    setMembers: (next) => { members = next },
    render(props = { site: { id: 1, name: '南门', enabled: true } }) {
      cursor = 0; refCursor = 0; effectCursor = 0; polls.length = 0
      return context.exports[exportName](props)
    },
    cleanup() { effects.forEach((effect) => effect.cleanup?.()) },
  }
}

const normal = { state: 'normal', availability: 'available', reason: '正常', offending_camera_ids: [] }
const onlineMember = { camera_id: 7, shm_name: 'camera_7', name: '大门', member_enabled: true, physical_enabled: true }
const liveStatus = { running: true, status: 'healthy', updated_at: 100, camera_states: { 7: 'READY' }, camera_online: { 7: true }, absence: normal, phone: { ...normal, state: 'alarm', offending_camera_ids: [7] }, prone: normal, vehicle: { ...normal, state: 'idle' } }
const text = (tree) => nodes(tree).filter((node) => typeof node === 'string').join(' ')
const signal = () => new AbortController().signal

test('three online cameras without AI snapshots show raw video independently', async () => {
  const h = harness()
  const members = [63, 64, 65].map((id) => ({ ...onlineMember, camera_id: id, shm_name: `camera_${id}`, name: `Camera ${id}` }))
  h.setMembers(members)
  h.setStatus({ ...liveStatus, status: 'unavailable', camera_states: { 63: 'INFERENCE_ERROR', 64: 'INFERENCE_ERROR', 65: 'INFERENCE_ERROR' }, camera_online: { 63: true, 64: true, 65: true } })
  h.render(); await h.polls[0].task(signal())
  const tree = h.render()
  assert.doesNotMatch(text(tree), /离线/)
  assert.match(text(tree), /检测未就绪/)
  assert.ok(nodes(tree).some((node) => node?.props?.label === '摄像头状态' && node.props.detail === '3 / 3 路视频在线'))
  const tiles = nodes(tree).filter((node) => node?.type === 'GuardCameraPreview')
  assert.equal(tiles.length, 3)
  for (const [index, tile] of tiles.entries()) {
    assert.equal(tile.props.aiReady, false)
    const camera = harness(preview, 'GuardCameraPreview')
    camera.setFrame({ ok: true, blob: async () => ({}) })
    camera.render(tile.props)
    assert.equal(camera.polls[0].options.enabled, true)
    await camera.polls[0].task(signal())
    assert.deepEqual(camera.requests, [`/api/cameras/camera_${63 + index}/frame.jpg`])
    assert.equal(nodes(camera.render(tile.props)).find((node) => node?.type === 'img').props.src, 'blob:frame')
    camera.cleanup()
  }
})

test('only physical offline state renders offline and stops video polling', async () => {
  const h = harness()
  h.setStatus({ ...liveStatus, camera_states: { 7: 'OFFLINE' }, camera_online: { 7: false } })
  h.render(); await h.polls[0].task(signal())
  const tree = h.render()
  assert.match(text(tree), /视频： 离线/)
  const tile = nodes(tree).find((node) => node?.type === 'GuardCameraPreview')
  const camera = harness(preview, 'GuardCameraPreview')
  assert.equal(nodes(camera.render(tile.props)).filter((node) => node?.type === 'img').length, 0)
  assert.equal(camera.polls[0].options.enabled, false)
})

test('READY snapshots prefer Guard annotations and retain positive rule display', async () => {
  const h = harness()
  h.setStatus(liveStatus)
  h.render(); await h.polls[0].task(signal())
  const tree = h.render()
  assert.equal(nodes(tree).find((node) => node?.type === 'GuardDetectionStatusRow' && node.props.label === '手机使用检测').props.state, 'danger')
  const tile = nodes(tree).find((node) => node?.type === 'GuardCameraPreview')
  assert.equal(tile.props.aiReady, true)
  const camera = harness(preview, 'GuardCameraPreview')
  camera.setFrame({ ok: true, blob: async () => ({}) })
  camera.render(tile.props); await camera.polls[0].task(signal())
  assert.deepEqual(camera.requests, ['/api/cameras/camera_7/frame.jpg?feature=guard_behavior'])
  assert.match(nodes(camera.render(tile.props)).find((node) => node?.type === 'img').props.alt, /Guard 标注画面/)
  camera.render({ ...tile.props, online: false })
  assert.equal(camera.polls[0].options.enabled, false)
  assert.deepEqual(camera.revoked, ['blob:frame'])
})

for (const status of [404, 503]) test(`annotated frame ${status} uses platform raw frame without labeling video offline`, async () => {
  const h = harness(preview, 'GuardCameraPreview')
  const props = { member: onlineMember, online: true, aiReady: true }
  h.setFrame((url) => url.includes('?feature=') ? { ok: false, status } : { ok: true, blob: async () => ({}) })
  h.render(props); await h.polls[0].task(signal())
  assert.deepEqual(h.requests, ['/api/cameras/camera_7/frame.jpg?feature=guard_behavior', '/api/cameras/camera_7/frame.jpg'])
  assert.match(nodes(h.render(props)).find((node) => node?.type === 'img').props.alt, /原始画面/)
  h.cleanup()
})

test('unavailable AI status and status request failure do not hide physical preview', async () => {
  const h = harness()
  h.render(); await h.polls[0].task(signal())
  let tree = h.render()
  assert.ok(nodes(tree).some((node) => node?.props?.detail === '未运行 / 不可用'))
  h.polls[0].options.onError(new Error('status unavailable'))
  tree = h.render()
  const tile = nodes(tree).find((node) => node?.type === 'GuardCameraPreview')
  assert.equal(tile.props.aiReady, false)
  assert.equal(tile.props.online, undefined)
  const camera = harness(preview, 'GuardCameraPreview')
  camera.render(tile.props)
  assert.equal(camera.polls[0].options.enabled, true)
  assert.doesNotMatch(text(tree), /离线/)
})

test('alarm policy cards display business names without numeric IDs', () => {
  const h = harness(alarms, 'AlarmPolicies')
  const tree = h.render({ policies: [8, 9, 10, 11].map((violation_type) => ({ violation_type, alarm_interval: 30 })), busy: false, onChange: async () => {} })
  const cards = nodes(tree).filter((node) => typeof node?.type === 'function')
  const titles = cards.map((node) => nodes(node.type(node.props)).find((child) => child?.type === 'h3').props.children)
  assert.deepEqual(titles, ['离岗', '手机使用', '趴睡', '车辆出厂检查异常'])
  assert.doesNotMatch(titles.join(' '), /(?:8|9|10|11) ·/)
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


test('monitor metrics avoid duplicate counts and never invent values for unavailable cameras', () => {
  const members = [7, 8, 9].map((camera_id) => ({ ...onlineMember, camera_id }))
  const status = { ...liveStatus, camera_states: { 7: 'READY', 8: 'READY', 9: 'STALE' },
    camera_metrics: { 7: { guard_count: 2, guard_confidence: .8, fps: 4 }, 8: { guard_count: 3, guard_confidence: .9, fps: 6 }, 9: { guard_count: 50, guard_confidence: 1, fps: 100 } } }
  const result = presentation.exports.summarizeGuardMonitor(status, members)
  assert.equal(result.guards, 3)
  assert.equal(result.guardConfidence, .9)
  assert.equal(result.fps, 5)
  for (const unavailable of [null, { ...status, running: false }, { ...status, camera_states: {} }]) {
    const result = presentation.exports.summarizeGuardMonitor(unavailable, members)
    assert.equal(result.guards, null)
    assert.equal(result.fps, null)
  }
})

test('alarm form only saves changed policy and keeps other alarm types independent', async () => {
  const h = harness(alarms, 'AlarmPolicies')
  const policies = [8, 9, 10, 11].map((violation_type) => ({ site_id: 4, violation_type, alarm_interval: 30, wechat_enable: true, wechat_user: 'original', horn_enable: false }))
  const props = { policies, busy: false, onChange: (operation) => operation() }
  let tree = h.render(props)
  const phone = nodes(tree).find((node) => typeof node?.type === 'function' && node.props.policy.violation_type === 9)
  phone.props.onChange(9, { wechat_user: 'phone-user', alarm_interval: 45 })
  tree = h.render(props)
  const save = nodes(tree).find((node) => node?.type === 'DetectionSaveBar')
  assert.equal(save.props.disabled, false)
  await save.props.onSave()
  assert.equal(h.writes.length, 1)
  assert.equal(h.writes[0][0], 4)
  assert.equal(h.writes[0][1], 9)
  assert.equal(h.writes[0][2].wechat_user, 'phone-user')
  assert.equal(h.writes[0][2].alarm_interval, 45)
  assert.equal(policies[0].wechat_user, 'original')
  h.setAdmin(false)
  assert.equal(nodes(h.render(props)).find((node) => node?.type === 'DetectionSaveBar').props.disabled, true)
})

test('restored ROI opens in a dialog while current camera binding and runtime controls stay intact', async () => {
  const roi = await read('components/guard_behavior/VehicleRoiSettings.tsx')
  assert.match(roi, /<DialogContent[\s\S]*<VehicleRoiEditor/)
  assert.match(roi, /updateRoi\(siteId, member.camera_id, roi\)/)
  assert.match(roi, /disabled=\{!isAdmin \|\| loading \|\| !loaded \|\| saving \|\| busy\}/)
  assert.match(config, /<DetectionConfigTabs /)
  const policy = await read('components/guard_behavior/PolicySettings.tsx')
  assert.match(policy, /PolicyRuleGroup/)
  assert.match(policy, /PolicyAdvancedFields/)
  assert.match(policy, /PolicySliderField/)
})
