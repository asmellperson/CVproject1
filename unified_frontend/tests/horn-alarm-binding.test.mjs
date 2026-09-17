import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const source = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
const paths = ['components/AiVisionRoiEditor.geometry.ts', 'lib/aivision.ts', 'lib/feature-cameras.ts', 'lib/alarm-config.ts', 'lib/horn-alarm-binding.ts', 'components/horn/hornDeviceForm.ts',
  'components/horn/HornAlarmBinding.tsx', 'components/horn/useHornCatalog.ts', 'components/AlarmPushConfig.tsx',
  'components/logistics_single_person/alarmBinding.ts',
  ...['Face', 'Human', 'Phone', 'Door', 'Intrusion'].map((name) => `sections/${name}DetectionSection.tsx`)]
const sources = Object.fromEntries(await Promise.all(paths.map(async (path) => [path, await source(path)])))
function moduleOf(path, dependencies = {}, extra = '') {
  const context = { exports: {}, Error, Number, console,
    require(name) {
      if (name in dependencies) return dependencies[name]
      if (name === '@/lib/feature-cameras') return moduleOf('lib/feature-cameras.ts')
      if (name === 'react/jsx-runtime') return { Fragment: 'Fragment', jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
      return new Proxy({}, { get: (_, key) => String(key) })
    },
  }
  vm.runInNewContext(ts.transpileModule(sources[path].replaceAll('import.meta.env', '({})') + extra, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText, context)
  return context.exports
}
const plain = (value) => JSON.parse(JSON.stringify(value))
const binding = (id = 1, task = 7, enable = true) => ({ enable, parm: { horn_id: id, horn_event_id: task } })
const device = (id, enable = true, state = 'online') => ({ id, name: `喇叭 ${id}`, enable, runtime: { state, online: state === 'online' } })
const alarmModule = moduleOf('lib/alarm-config.ts')
const rules = moduleOf('lib/horn-alarm-binding.ts')
const labels = moduleOf('components/horn/hornDeviceForm.ts')
const adapter = moduleOf('components/logistics_single_person/alarmBinding.ts', { '@/lib/alarm-config': alarmModule })
function nodes(tree) {
  if (tree == null || typeof tree === 'boolean') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (typeof tree !== 'object') return [tree]
  return [tree, ...nodes(tree.props?.children)]
}
const component = (tree, type) => nodes(tree).find((node) => node?.type === type)
const textOf = (tree) => nodes(tree).filter((node) => typeof node === 'string').join(' ')

function hooks({ effects = false } = {}) {
  const slots = []; let cursor = 0
  return {
    react: {
      lazy: () => 'Lazy', useId: () => 'binding',
      useEffect: (callback) => { if (effects) callback() },
      useState(initial) {
        const index = cursor++
        if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial
        return [slots[index], (next) => { slots[index] = typeof next === 'function' ? next(slots[index]) : next }]
      },
      useRef(initial) { const index = cursor++; slots[index] ??= { current: initial }; return slots[index] },
    },
    render(callback) { cursor = 0; return callback() },
  }
}

function bindingView({ value = binding(), devices = [device(1)], admin = true, loadError = '', disabled = false } = {}) {
  let changed, error
  const view = moduleOf('components/horn/HornAlarmBinding.tsx', {
    react: hooks({ effects: true }).react, '@/auth/useAuth': { useAuth: () => ({ isAdmin: admin }) },
    './hornDeviceForm': labels, '@/lib/horn-alarm-binding': rules,
    './useHornCatalog': { useHornCatalog: (enabled) => { assert.equal(enabled, admin); return { devices, error: loadError } } },
  })
  const render = () => view.HornAlarmBinding({ value, disabled,
    onChange: (next) => { value = next; changed = next }, onValidationChange: (next) => { error = next } })
  return { render, changed: () => plain(changed), error: () => error }
}

test('binding switch retains device/task and controlled props follow the selected camera', () => {
  const view = bindingView()
  component(view.render(), 'Switch').props.onCheckedChange(false)
  assert.deepEqual(view.changed(), binding(1, 7, false))
  component(view.render(), 'Switch').props.onCheckedChange(true)
  assert.deepEqual(view.changed(), binding())
  const b = bindingView({ value: binding(2, 19), devices: [device(2)] })
  assert.equal(component(b.render(), 'Select').props.value, '2')
  assert.equal(component(b.render(), 'Input').props.value, '19')
})

test('only enabled devices are selectable; existing disabled and missing selections remain visible', () => {
  const view = bindingView({ devices: [device(1, false, 'disabled'), device(2), device(3, false)] })
  const tree = view.render()
  const options = nodes(tree).filter((node) => node?.type === 'SelectItem')
  assert.deepEqual(options.map((node) => node.props.value), ['none', '1', '2'])
  assert.equal(options[1].props.disabled, true)
  assert.match(textOf(tree), /已停用/)
  assert.match(view.error(), /已停用/)
  component(tree, 'Select').props.onValueChange('3')
  component(tree, 'Select').props.onValueChange('2')
  assert.deepEqual(view.changed(), binding(2))
  const missing = bindingView({ value: binding(999), devices: [] })
  assert.match(textOf(missing.render()), /不存在/)
  component(missing.render(), 'Select').props.onValueChange('none')
  assert.deepEqual(missing.changed(), binding(null))
})

test('disabled binding preserves disabled device and permits explicit clearing', () => {
  const view = bindingView({ value: binding(1, 7, false), devices: [device(1, false)] })
  assert.match(textOf(view.render()), /原绑定已保留/)
  assert.equal(view.error(), null)
  component(view.render(), 'Select').props.onValueChange('none')
  assert.deepEqual(view.changed(), binding(null, 7, false))
})

test('task id validation and runtime state labels match the existing API contract', () => {
  for (const task of [0, -1, 1.2, true, '7', 2147483648, Number.NaN]) assert.match(rules.validateHornBinding(binding(1, task)), /整数/)
  assert.match(rules.validateHornBinding(binding(null)), /必须选择/)
  assert.match(rules.validateHornBinding(binding(1, null)), /必须选择/)
  assert.equal(rules.validateHornBinding(binding(1, 2147483647)), null)
  for (const state of ['online', 'offline', 'connecting', 'failed', 'disabled', 'stopping']) {
    const view = bindingView({ devices: [device(1, state !== 'disabled', state)] })
    assert.ok(textOf(view.render()).includes(labels.HORN_STATE_LABELS[state]))
  }
  const view = bindingView()
  component(view.render(), 'Input').props.onChange({ target: { value: '42' } })
  assert.deepEqual(view.changed(), binding(1, 42))
})

test('catalog failures preserve bindings, block unknown selections, and viewer never reads device API', () => {
  const view = bindingView({ devices: null, loadError: '服务器不可用' })
  assert.match(textOf(view.render()), /服务器不可用/)
  assert.match(view.error(), /尚未读取成功/)
  const readonly = bindingView({ admin: false })
  const tree = readonly.render()
  for (const type of ['Switch', 'Select', 'Input']) assert.equal(component(tree, type).props.disabled, true)
  assert.match(textOf(tree), /仅管理员可查询/)
})

test('AlarmPushConfig changes horn without modifying WeChat/SQL and blocks invalid binding save', () => {
  const state = hooks(); let changed, saved = 0
  const alarm = { horn: binding(), sql: { enable: true, parm: {} }, wechat: { enable: true, parm: { user: 'test-user' } } }
  const view = moduleOf('components/AlarmPushConfig.tsx', { react: state.react, '@/lib/alarm-config': alarmModule, '@/lib/utils': { cn: (...items) => items.join(' ') } })
  const render = () => state.render(() => view.AlarmPushConfig({ alarm, onChange: (next) => { changed = next }, onSave: () => { saved++ } }))
  component(render(), 'HornAlarmBinding').props.onChange(binding(2, 11))
  assert.deepEqual(plain(changed), { ...alarm, horn: binding(2, 11) })
  const wechatProps = nodes(render()).find((node) => node?.type === view.WechatAlarmSettings).props
  const wechatView = () => state.render(() => view.WechatAlarmSettings(wechatProps))
  component(wechatView(), 'Switch').props.onCheckedChange(false)
  assert.deepEqual(plain(changed), { ...alarm, wechat: { ...alarm.wechat, enable: false } })
  component(wechatView(), 'Input').props.onChange({ target: { value: 'new-user|second-user' } })
  assert.deepEqual(plain(changed), { ...alarm, wechat: { enable: true, parm: { user: 'new-user|second-user' } } })
  component(render(), 'HornAlarmBinding').props.onValidationChange('invalid')
  assert.equal(component(render(), 'DetectionSaveBar').props.disabled, true)
  component(render(), 'DetectionSaveBar').props.onSave()
  assert.equal(saved, 0)
})

test('logistics adapter round trips the native alarm structure without losing SQL or WeChat', () => {
  const native = { sql_enable: true, horn: { enabled: true, horn_id: 2, horn_event_id: 11 }, wechat: { enabled: true, user: 'test-user' } }
  const shared = adapter.toFeatureAlarm(native)
  assert.deepEqual(plain(shared.horn), binding(2, 11))
  assert.deepEqual(plain(adapter.toLogisticsAlarm(shared)), native)
  shared.horn.enable = false
  assert.deepEqual(plain(adapter.toLogisticsAlarm(shared)), { ...native, horn: { ...native.horn, enabled: false } })
})

test('catalog uses the existing serial polling and ignores responses after permission is revoked', async () => {
  const state = hooks({ effects: true }); let task, options, resolve
  const api = moduleOf('components/horn/useHornCatalog.ts', { react: state.react,
    '@/lib/horns': { listHorns: () => new Promise((done) => { resolve = done }) },
    '@/hooks/use-serial-poll': { useSerialPoll: (next, opts) => { task = next; options = opts } },
  })
  const render = (admin) => state.render(() => api.useHornCatalog(admin))
  render(true); assert.equal(options.enabled, true)
  const pending = task(new AbortController().signal)
  render(false); assert.equal(options.enabled, false)
  resolve([device(1)]); await pending
  assert.equal(render(false).devices, null)
})

const settle = () => new Promise((resolve) => setImmediate(resolve))
const backendValues = {
  Face: { roi_pos: [], cap_interval: .1, alarm_interval: 5, FACE_SCORE_THR: .6, MAX_TIME: 10, MAX_LOST: 5, DETECTION_IOU_THR: .3, TRACK_IOU_THR: .3 },
  Human: { roi_pos: [], alarm_interval: 5, CONF_THRESHOLD: .3, MAX_TIME: 10, MAX_LOST: 5, DETECTION_IOU_THR: .3, TRACK_IOU_THR: .3,
    MIN_BOX_AREA: 0, ASPECT_RATIO_RANGE: [0, 10], CENTER_DIST_THR: .65, AREA_RATIO_THR: .55, MATCH_SCORE_THR: .35, TRACK_SMOOTH_ALPHA: .7 },
  Phone: { roi_pos: [], alarm_interval: 5, CONF_THRESHOLD: .7, IOU_THR: .5, PERSON_CONF_THRESHOLD: .3, MIN_CONFIRM_SECONDS: 1.2,
    MIN_CONSECUTIVE_HITS: 3, REQUIRE_PERSON_ASSOCIATION: true, PERSON_EXPAND_RATIO: .18 },
  Door: { roi_pos: [], alarm_interval: 5, threshold: .5, first_alarm: 60, env_threshold: null, min_local_change_ratio: .01,
    stable_confirm_seconds: 1, stable_confirm_hits: 3, global_motion_threshold: .22, background_update_alpha: .05 },
  Intrusion: { roi_pos: [], alarm_interval: 5, line_points: [], alarm_side: 1, foot_ratio: .93, threshold: .1 },
}
for (const [name, configKey] of [['Face', 'detect_face'], ['Human', 'detect_human'],
  ['Phone', 'detect_phone'], ['Door', 'detect_door'], ['Intrusion', 'blocks']]) {
  test(`${name}: independent camera load/save, late responses ignored, failed load cannot save old binding`, async () => {
    const state = hooks(); const pending = new Map(); const writes = []; let defer = false
    const api = {
      getAiVisionCameras: async () => ['a', 'b', 'bad'].map((key, index) => ({ id: key, camera_id: index + 1, shm_name: key, name: key, department: 'fulida_company', enabled: true, functions: { [configKey]: true } })), isAiVisionFeatureEnabled: () => true,
      getAiVisionFeatureConfig: async (_feature, key) => {
        if (defer) return new Promise((resolve, reject) => pending.set(key, { resolve, reject }))
        return response(key)
      },
      saveAiVisionFeatureConfig: async (feature, key, config) => { writes.push({ feature, key, config: plain(config) }); return response(key, config) },
    }
    const view = moduleOf(`sections/${name}DetectionSection.tsx`, {
      react: state.react, '@/auth/useAuth': { useAuth: () => ({ isAdmin: true }) },
      '@/lib/aivision': api, '@/lib/alarm-config': alarmModule,
      '@/components/AiVisionRoiEditor.geometry': moduleOf('components/AiVisionRoiEditor.geometry.ts'),
    })
    function response(key, config) {
      return { camera: { id: key === 'a' ? 1 : 2, shm_name: key, name: key, enable: true, department: 'fulida_company' }, feature: configKey,
        config: config || { value: backendValues[name], enable: true, alarm: { sql: { enable: false, parm: {} }, wechat: { enable: false, parm: { user: '' } }, horn: binding(key === 'a' ? 1 : 2, key === 'a' ? 7 : 9) } } }
    }
    const render = () => state.render(() => view[`${name}DetectionSection`]({ department: 'fulida_company' }))
    const select = (key) => component(render(), 'FeatureCameraManager').props.onSelectCamera(key)
    await component(render(), 'FeatureCameraManager').props.onCamerasChanged('a'); await settle()
    select('a'); await settle()
    assert.deepEqual(plain(component(render(), 'AlarmPushConfig').props.alarm.horn), binding())
    const alarm = component(render(), 'AlarmPushConfig').props.alarm
    component(render(), 'AlarmPushConfig').props.onChange({ ...alarm, horn: binding(1, 21, false) })
    await component(render(), 'AlarmPushConfig').props.onSave()
    assert.equal(writes.length, 1)
    assert.deepEqual(writes[0].config.alarm.horn, binding(1, 21, false))
    defer = true
    select('a'); select('b')
    pending.get('b').resolve(response('b')); await settle()
    pending.get('a').resolve(response('a')); await settle()
    assert.deepEqual(plain(component(render(), 'AlarmPushConfig').props.alarm.horn), binding(2, 9))
    defer = false
    await component(render(), 'AlarmPushConfig').props.onSave()
    assert.equal(writes.at(-1).key, 'b')
    assert.deepEqual(writes.at(-1).config.alarm.horn, binding(2, 9))
    defer = true; select('bad'); pending.get('bad').reject(new Error('network')); await settle()
    const count = writes.length
    await component(render(), 'AlarmPushConfig').props.onSave()
    assert.equal(writes.length, count)
  })
}

test('shared binding reaches existing feature pages and logistics, while guard/VLM only expose device management', async () => {
  for (const name of ['Face', 'Human', 'Phone', 'Door', 'Intrusion']) assert.match(sources[`sections/${name}DetectionSection.tsx`], /<AlarmPushConfig/)
  assert.match(await source('App.tsx'), /<HumanDetectionSection department=\{currentDepartment\}/)
  const logistics = await source('components/logistics_single_person/LogisticsChannelConfigView.tsx')
  assert.match(logistics, /alarm=\{toFeatureAlarm\(alarmDraft.alarm\)\}/)
  assert.match(logistics, /alarm: toLogisticsAlarm\(alarm\)/)
  for (const path of ['sections/ConfigSection.tsx', 'sections/SecurityVlmSection.tsx']) {
    const code = await source(path)
    assert.match(code, /DetectionConfigTabs/)
    assert.doesNotMatch(code, /HornAlarmBinding|AlarmPushConfig/)
  }
})

test('all ordinary feature save entrypoints reject invalid task IDs before making HTTP requests', async () => {
  const api = moduleOf('lib/aivision.ts', { '@/lib/horn-alarm-binding': rules })
  for (const task of [0, -1, 1.2, Number.NaN, 2147483648]) {
    await assert.rejects(api.saveAiVisionFeatureConfig('detect_human', 'cam_a', {
      enable: true, value: {}, alarm: { horn: binding(1, task, false) },
    }), /整数/)
  }
})
