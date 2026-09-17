import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const root = new URL('../src/', import.meta.url)
const source = async (path) => readFile(new URL(path, root), 'utf8')
const sources = Object.fromEntries(await Promise.all([
  'lib/horns.ts', 'components/horn/hornDeviceForm.ts', 'components/horn/useHornDevices.ts',
  'components/horn/HornDeviceManager.tsx', 'components/horn/HornDeviceDialog.tsx',
  'components/detection/DetectionConfigTabs.tsx',
].map(async (path) => [path, await source(path)])))

function moduleOf(path, dependencies = {}, globals = {}) {
  const context = {
    exports: {}, Error, URL, AbortController, ...globals,
    require(name) {
      if (name in dependencies) return dependencies[name]
      if (name === 'react/jsx-runtime') return {
        Fragment: 'Fragment', jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }),
      }
      return new Proxy({}, { get: (_, key) => String(key) })
    },
  }
  vm.runInNewContext(ts.transpileModule(sources[path], {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText, context)
  return context.exports
}

const plain = (value) => JSON.parse(JSON.stringify(value))
const form = moduleOf('components/horn/hornDeviceForm.ts')
const runtime = (state = 'disabled') => ({ state, online: state === 'online', heartbeat_alive: false, last_error: null, last_seen_at: null })
const device = (changes = {}) => ({ id: 1, name: '东门喇叭', url: 'http://speaker.local', username: 'operator',
  password_set: true, enable: false, description: '东门', runtime: runtime(), ...changes })

function hooks() {
  const slots = []
  const effects = []
  let cursor = 0
  return {
    react: {
      useState(initial) {
        const index = cursor++
        if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial
        return [slots[index], (next) => { slots[index] = typeof next === 'function' ? next(slots[index]) : next }]
      },
      useRef(initial) {
        const index = cursor++
        slots[index] ??= { current: initial }
        return slots[index]
      },
      useEffect(callback, dependencies) {
        const index = cursor++
        const previous = slots[index]
        if (previous && dependencies.every((item, i) => Object.is(item, previous.dependencies[i]))) return
        effects.push(() => {
          previous?.cleanup?.()
          slots[index] = { dependencies, cleanup: callback() }
        })
      },
    },
    render(callback) { cursor = 0; const result = callback(); effects.splice(0).forEach((effect) => effect()); return result },
    unmount() { slots.forEach((slot) => slot?.cleanup?.()) },
  }
}

function harness({ admin = true, items = [device()] } = {}) {
  const state = hooks()
  let poll, options
  const calls = []
  const api = {}
  const implementations = {
    listHorns: async () => items,
    getHorn: async (id) => device({ id }),
    createHorn: async (payload) => device({ ...payload, id: 2, password: undefined }),
    updateHorn: async (id, payload) => device({ ...payload, id, password: undefined }),
    deleteHorn: async () => undefined,
    testHornConnection: async () => ({ success: true, runtime: runtime('online') }),
    getHornStatus: async () => runtime('disabled'),
  }
  for (const name of Object.keys(implementations)) api[name] = (...args) => {
    calls.push({ name, args })
    return implementations[name](...args)
  }
  const hook = moduleOf('components/horn/useHornDevices.ts', {
    react: state.react, '@/lib/horns': api,
    '@/hooks/use-serial-poll': { useSerialPoll: (task, value) => { poll = task; options = value } },
  }, { window: { setTimeout, clearTimeout } })
  const manager = moduleOf('components/horn/HornDeviceManager.tsx', {
    react: state.react, './useHornDevices': hook,
    './hornDeviceForm': form, '@/auth/useAuth': { useAuth: () => ({ isAdmin: admin }) },
  }, { window: { confirm: () => true } })
  return {
    calls, implementations,
    render: () => state.render(() => hook.useHornDevices(admin)),
    renderManager: () => state.render(() => manager.HornDeviceManager()),
    poll: (signal = new AbortController().signal) => poll(signal),
    options: () => options,
    setAdmin: (next) => { admin = next },
    unmount: state.unmount,
  }
}

function nodes(tree) {
  if (tree == null || typeof tree === 'boolean') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (typeof tree !== 'object') return [tree]
  return [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.actions)]
}
const textOf = (tree) => nodes(tree).filter((node) => typeof node === 'string').join(' ')
const button = (tree, label) => nodes(tree).find((node) => node?.type === 'Button' && textOf(node).includes(label))
const field = (tree, id) => nodes(tree).find((node) => node?.props?.id === id)

test('all seven API wrappers use authenticated global endpoints and DELETE accepts 204', async () => {
  const calls = []
  const api = moduleOf('lib/horns.ts', { '@/lib/api': { apiUrl: (path) => `/api${path}` } }, {
    fetch: async (url, options) => {
      calls.push({ url, options })
      return { ok: true, status: options.method === 'DELETE' ? 204 : 200,
        json: () => { assert.notEqual(options.method, 'DELETE'); return Promise.resolve({}) } }
    },
  })
  const signal = new AbortController().signal
  await api.listHorns(signal)
  await api.getHorn(1, signal)
  await api.createHorn({ name: '新设备', password: 'test-only' }, signal)
  await api.updateHorn(1, { enable: false }, signal)
  assert.equal(await api.deleteHorn(1, signal), undefined)
  await api.getHornStatus(1, signal)
  await api.testHornConnection({ horn_id: 1 }, signal)
  assert.deepEqual(calls.map(({ url, options }) => [options.method, url]), [
    ['GET', '/api/horns'], ['GET', '/api/horns/1'], ['POST', '/api/horns'], ['PATCH', '/api/horns/1'],
    ['DELETE', '/api/horns/1'], ['GET', '/api/horns/1/status'], ['POST', '/api/horns/test-connection'],
  ])
  assert.ok(calls.every(({ options }) => options.credentials === 'include' && options.signal === signal))
  assert.deepEqual(JSON.parse(calls[3].options.body), { enable: false })
})

test('409 deletion identifies references and 401 preserves the shared login-expiry event', async () => {
  let status = 409
  const events = []
  const api = moduleOf('lib/horns.ts', { '@/lib/api': { apiUrl: (path) => `/api${path}` } }, {
    Event, window: { dispatchEvent: (event) => events.push(event.type) },
    fetch: async () => ({ ok: false, status, json: async () => ({ detail: 'conflict' }) }),
  })
  await assert.rejects(api.deleteHorn(1), (error) => error.status === 409 && /仍被检测配置引用.*物流通道/.test(error.message))
  status = 401
  await assert.rejects(api.listHorns())
  assert.deepEqual(events, ['aicv:unauthorized'])
  status = 403
  await assert.rejects(api.listHorns(), /管理员/)
})

test('password drafts never read a returned password and blank editing preserves it', () => {
  const draft = form.hornDraft(device({ password: 'must-not-be-used' }))
  assert.equal(draft.password, '')
  assert.equal(form.validateHornDraft(draft, true), null)
  assert.match(form.validateHornDraft(draft, false), /必须输入密码/)
  assert.equal('password' in form.hornWritePayload(draft), false)
  assert.equal('password' in form.hornConnectionPayload(draft, 1), false)
  draft.password = ' spaces are valid '
  assert.equal(form.hornWritePayload(draft).password, draft.password)
  assert.deepEqual(Object.keys(form.hornConnectionPayload(draft, 1)).sort(), ['horn_id', 'password', 'url', 'username'])
  draft.url = 'http://user:secret@speaker.local'
  assert.match(form.validateHornDraft(draft, true), /地址/)
})

test('device CRUD and enabled state use the backend responses', async () => {
  const page = harness()
  page.render()
  await page.poll()
  let state = page.render()
  assert.equal(state.devices.length, 1)
  assert.equal((await state.loadDevice(1)).id, 1)
  await state.saveDevice(undefined, { ...form.hornDraft(null), name: 'new', url: 'http://new', password: 'test-only' })
  state = page.render()
  assert.equal(state.devices.length, 2)
  await state.saveDevice(1, form.hornWritePayload(form.hornDraft(device())))
  const editCall = page.calls.find((call) => call.name === 'updateHorn')
  assert.equal('password' in editCall.args[1], false)
  await page.render().setEnabled(device(), true)
  assert.equal(page.render().devices.find((item) => item.id === 1).enable, true)
  await page.render().removeDevice(device())
  assert.deepEqual(plain(page.render().devices.map((item) => item.id)), [2])
  page.unmount()
})

test('failed deletion keeps the row and exposes a persistent reference warning', async () => {
  const page = harness()
  page.render(); await page.poll()
  page.implementations.deleteHorn = async () => { throw new Error('该设备仍被检测配置引用，请先解除绑定。') }
  assert.equal(await page.render().removeDevice(device()), undefined)
  assert.equal(page.render().devices.length, 1)
  assert.match(page.render().error, /仍被检测配置引用/)
  await page.poll()
  assert.match(page.render().error, /仍被检测配置引用/)
  page.unmount()
})

test('connection tests do not write configuration or turn disabled runtime online', async () => {
  const page = harness()
  page.render(); await page.poll()
  const result = await page.render().checkConnection({ horn_id: 1 })
  assert.equal(result.success, true)
  assert.equal(page.render().devices[0].runtime.state, 'disabled')
  assert.deepEqual(page.calls.map((call) => call.name), ['listHorns', 'testHornConnection', 'getHornStatus'])
  page.calls.length = 0
  await page.render().checkConnection({ url: 'http://new', username: 'operator', password: 'test-only' })
  assert.deepEqual(page.calls.map((call) => call.name), ['testHornConnection'])
  page.unmount()
})

test('viewer cannot query or invoke device operations even through event callbacks', async () => {
  const page = harness({ admin: false })
  const state = page.render()
  assert.equal(page.options().enabled, false)
  await page.poll()
  await state.loadDevice(1)
  await state.saveDevice(1, {})
  await state.removeDevice(device())
  await state.setEnabled(device(), true)
  await state.checkConnection({ horn_id: 1 })
  assert.deepEqual(page.calls, [])
  page.unmount()
  const viewer = harness({ admin: false })
  const tree = viewer.renderManager()
  assert.match(textOf(tree), /仅对管理员开放/)
  assert.equal(button(tree, '新增喇叭'), undefined)
  viewer.unmount()
})

test('late list response cannot overwrite a successful mutation', async () => {
  const page = harness()
  page.render(); await page.poll()
  let resolve
  page.implementations.listHorns = () => new Promise((next) => { resolve = next })
  const pending = page.poll()
  await page.render().setEnabled(device(), true)
  resolve([device({ enable: false })])
  await pending
  assert.equal(page.render().devices[0].enable, true)
  page.unmount()
})

test('overlapping mutations are gated and closing the manager aborts outstanding work', async () => {
  const page = harness()
  page.render()
  let signal, resolve
  page.implementations.updateHorn = (_id, _payload, currentSignal) => {
    signal = currentSignal
    return new Promise((next) => { resolve = next })
  }
  const pending = page.render().setEnabled(device(), true)
  assert.equal(await page.render().removeDevice(device()), undefined)
  assert.equal(page.calls.filter((call) => call.name === 'deleteHorn').length, 0)
  page.unmount()
  assert.equal(signal.aborted, true)
  resolve(device())
  assert.equal(await pending, undefined)
})

test('empty global manager still offers creation without a camera or channel', async () => {
  const page = harness({ items: [] })
  page.renderManager(); await page.poll()
  let tree = page.renderManager()
  const create = button(tree, '新增喇叭')
  assert.ok(create)
  assert.equal(create.props.disabled, false)
  create.props.onClick()
  tree = page.renderManager()
  const dialog = nodes(tree).find((node) => node?.type === 'HornDeviceDialog')
  assert.equal(dialog.props.device, null)
  assert.equal(await dialog.props.onSave({ name: 'global', url: 'http://new', username: 'admin', password: 'test', enable: false }), true)
  assert.equal(page.calls.filter((call) => call.name === 'createHorn').length, 1)
  page.unmount()
})

test('form requires new password, preserves blank edits, and tests without saving', async () => {
  const state = hooks()
  const dialog = moduleOf('components/horn/HornDeviceDialog.tsx', { react: state.react, './hornDeviceForm': form })
  const saves = [], tests = []
  let closed = 0
  const props = { device: null, busy: false, error: '', onClose: () => { closed += 1 },
    onSave: async (value) => { saves.push(value); return false },
    onTest: async (value) => { tests.push(value); return { success: true, runtime: runtime('online') } } }
  const render = () => state.render(() => dialog.HornDeviceDialog(props))
  let tree = render()
  field(tree, 'horn-name').props.onChange({ target: { value: 'test' } })
  field(tree, 'horn-url').props.onChange({ target: { value: 'http://new.local' } })
  tree = render()
  field(tree, 'horn-device-form').props.onSubmit({ preventDefault() {} })
  assert.match(textOf(render()), /必须输入密码/)
  assert.equal(saves.length, 0)
  field(render(), 'horn-password').props.onChange({ target: { value: 'test-only' } })
  button(render(), '测试连接').props.onClick()
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(tests.length, 1)
  assert.equal(saves.length, 0)
  assert.match(textOf(render()), /连接成功/)
  field(render(), 'horn-device-form').props.onSubmit({ preventDefault() {} })
  await new Promise((resolve) => setImmediate(resolve))
  assert.equal(saves.length, 1)
  assert.equal(closed, 0, 'failed save keeps the editor open')
  state.unmount()

  const editState = hooks()
  const editDialog = moduleOf('components/horn/HornDeviceDialog.tsx', { react: editState.react, './hornDeviceForm': form })
  const editTree = editState.render(() => editDialog.HornDeviceDialog({ ...props, device: device() }))
  assert.equal(field(editTree, 'horn-password').props.value, '')
  assert.match(textOf(editTree), /留空表示保留原密码/)
})

test('all runtime states have distinct labels', () => {
  for (const state of ['online', 'offline', 'connecting', 'failed', 'disabled', 'stopping', 'stopped', 'pending', 'not_started']) {
    assert.ok(form.HORN_STATE_LABELS[state])
  }
  assert.equal(new Set(Object.values(form.HORN_STATE_LABELS)).size, 9)
})

test('each detection configuration uses the single public horn container', async () => {
  const paths = ['FaceDetectionSection', 'HumanDetectionSection', 'IntrusionDetectionSection',
    'PhoneDetectionSection', 'DoorDetectionSection', 'SecurityVlmSection'].map((name) => `sections/${name}.tsx`)
  paths.push('components/logistics_single_person/LogisticsChannelConfigView.tsx')
  for (const path of paths) {
    const content = await source(path)
    assert.equal((content.match(/<DetectionConfigTabs\b/g) ?? []).length, 1, path)
    assert.doesNotMatch(content, /<HornDeviceManager\b/, path)
    if (!path.includes('SecurityVlm')) assert.match(content, /报警推送/, path)
  }
  assert.match(await source('App.tsx'), /<HumanDetectionSection department=\{currentDepartment\}/)
  for (const suffix of ['']) {
    assert.match(await source(`sections/LogisticsSinglePerson${suffix}DetectionSection.tsx`), /<LogisticsChannelSection/)
  }
  assert.match(await source('sections/GuardBehaviorSection.tsx'), /<GuardConfigView/)
  const guard = await source('components/guard_behavior/AlarmPolicies.tsx')
  assert.match(guard, /<HornDeviceManager/)
  const tabs = moduleOf('components/detection/DetectionConfigTabs.tsx')
  const tree = tabs.DetectionConfigTabs({ defaultValue: 'horns', tabs: [], children: null })
  assert.equal(nodes(tree).filter((node) => node?.type === 'HornDeviceManager').length, 1)
  assert.equal(nodes(tree).find((node) => node?.props?.value === 'horns' && node.type === 'DetectionConfigTab').props.disabled, undefined)
  assert.match(sources['components/horn/HornDeviceManager.tsx'], /dark:bg-slate-900/)
})
