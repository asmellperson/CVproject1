import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const root = new URL('../', import.meta.url)

async function compile(path, imports = {}) {
  const source = await readFile(new URL(path, root), 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const module = { exports: {} }
  Function('require', 'exports', 'module', output)((name) => imports[name] ?? require(name), module.exports, module)
  return module.exports
}

const wrapper = ({ children }) => React.createElement('div', null, children)
const icons = new Proxy({}, { get: () => () => React.createElement('svg') })
const ui = new Proxy({}, { get: () => wrapper })

test('所有正式事业部可以进入人脸身份识别及查询识别报警', async () => {
  const permissions = await compile('src/auth/permissions.ts')
  const electronic = { role: 'viewer', departments: ['electronics_electrician'] }
  assert.equal(permissions.hasPageAccess(electronic, 'face-recognition'), true)
  for (const department of permissions.DEPARTMENTS) {
    assert.equal(permissions.hasPageAccess({ role: 'viewer', departments: [department] }, 'face-recognition'), true)
  }
  assert.equal(permissions.hasPageAccess({ role: 'admin' }, 'face-recognition'), true)
  assert.equal(permissions.hasPageAccess(null, 'face-recognition'), false)
  assert.equal(permissions.getAccessibleAlarmEventTypes(electronic).includes('recognize_face'), true)
})

test('顶部页签按实时监控、识别记录、配置管理排列，原有页面仍然只有两个页签', async () => {
  const { DetectionPageHeader } = await compile('src/components/detection/DetectionPageHeader.tsx', {
    'lucide-react': icons, '@/components/ui/tabs': ui,
  })
  const props = { title: '人脸身份识别', subtitle: '', departmentLabel: '电子电工事业部' }
  const html = renderToStaticMarkup(React.createElement(DetectionPageHeader, { ...props, recordsValue: 'records' }))
  assert.ok(html.indexOf('实时监控') < html.indexOf('识别记录'))
  assert.ok(html.indexOf('识别记录') < html.indexOf('配置管理'))
  const other = renderToStaticMarkup(React.createElement(DetectionPageHeader, props))
  assert.equal(other.includes('识别记录'), false)
})

const cameraApi = {
  getAiVisionCameraKey: (camera) => camera.shm_name,
  isAiVisionFeatureEnabled: (camera, feature) => Boolean(camera.functions[feature]),
}
const faceApi = { FACE_FEATURE: 'recognize_face' }
const recognitionAlarm = {
  sql: { enable: false, parm: {} },
  wechat: { enable: true, parm: { user: 'test-user|second-user' } },
  horn: { enable: true, parm: { horn_id: 2, horn_event_id: 7 } },
}
const camera = (id, enabled = true, feature = true) => ({
  id: String(id), camera_id: id, sort_order: id - 1, shm_name: `camera_${id}`, name: `摄像头${id}`, enabled,
  department: 'electronics_electrician', functions: { recognize_face: feature },
})
const sharedUi = {
  'lucide-react': icons,
  '@/components/ui/button': ui, '@/components/ui/card': ui, '@/components/ui/label': ui,
  '@/components/ui/select': ui, '@/components/ui/badge': ui,
  '@/components/ui/table': ui,
  '@/components/monitor/ResizableMonitorLayout': { ResizableMonitorLayout: wrapper },
  '@/components/AlarmPushConfig': { WechatAlarmSettings: 'WechatAlarmSettings' },
  '@/components/horn/HornAlarmBinding': { HornAlarmBinding: 'HornAlarmBinding' },
  '@/components/horn/HornDeviceManager': { HornDeviceManager: 'HornDeviceManager' },
  '@/lib/aivision': cameraApi,
}

function hookHarness() {
  const slots = []
  let cursor = 0, dirty = true, render, output
  let effects = []
  const changed = (left, right) => !left || !right || left.some((value, index) => !Object.is(value, right[index]))
  const hooks = {
    useState(initial) {
      const index = cursor++
      if (!slots[index]) slots[index] = { value: typeof initial === 'function' ? initial() : initial }
      return [slots[index].value, (next) => {
        const value = typeof next === 'function' ? next(slots[index].value) : next
        if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true }
      }]
    },
    useRef(initial) {
      const index = cursor++
      return (slots[index] ??= { current: initial })
    },
    useMemo(fn, deps) {
      const index = cursor++
      if (!slots[index] || changed(slots[index].deps, deps)) slots[index] = { deps, value: fn() }
      return slots[index].value
    },
    useCallback(fn, deps) { return hooks.useMemo(() => fn, deps) },
    useEffect(fn, deps) {
      const index = cursor++
      const previous = slots[index]
      if (!previous || changed(previous.deps, deps)) {
        slots[index] = { deps, cleanup: previous?.cleanup }
        effects.push(() => { slots[index].cleanup?.(); slots[index].cleanup = fn() })
      }
    },
  }
  return {
    hooks,
    async mount(fn) { render = fn; return this.flush() },
    async flush() {
      for (let i = 0; i < 30; i++) {
        if (dirty) {
          dirty = false; cursor = 0; effects = []; output = render()
          const pending = effects; effects = []; pending.forEach((effect) => effect())
        }
        await Promise.resolve()
      }
      return output
    },
    rerender() { dirty = true },
    dispose() { slots.forEach((slot) => slot?.cleanup?.()) },
  }
}

function elements(node, predicate) {
  if (!node || typeof node !== 'object') return []
  if (Array.isArray(node)) return node.flatMap((child) => elements(child, predicate))
  return [...(predicate(node) ? [node] : []), ...elements(node.props?.children, predicate)]
}

const statusModule = await compile('src/components/face_recognition/useFaceRecognitionStatus.ts', {
  '@/hooks/use-serial-poll': {}, './api': faceApi,
})
const { StatCard } = await compile('src/components/feature_dashboard/FeatureDashboardMonitorView.tsx', {
  ...sharedUi, '@/lib/utils': { cn: (...items) => items.filter(Boolean).join(' ') }, './monitorState': {},
})

test('四张统一状态卡展示人数、身份和工号；视频失败不停止识别，过期或离线立即清空', async () => {
  const valid = {
    online: true, alarm: true, reason: 'unauthorized', updated_at: new Date().toISOString(), count: 3,
    detections: [
      { bbox: [10, 20, 100, 150], matched: true, is_allowed: true, person_id: 1, person_name: '测试甲', job_no: 'J001', similarity: .88 },
      { bbox: [200, 20, 300, 150], matched: true, is_allowed: false, person_id: 2, person_name: '测试乙', job_no: 'J002', similarity: .91 },
      { bbox: [400, 20, 500, 150], matched: false, is_allowed: false, person_id: null, person_name: '未知人员', similarity: .42 },
    ],
  }
  let status = valid, error = ''
  const polls = []
  const { FaceRecognitionMonitorView } = await compile('src/components/face_recognition/FaceRecognitionMonitorView.tsx', {
    ...sharedUi, './api': faceApi,
    '@/components/feature_dashboard/FeatureDashboardMonitorView': { StatCard },
    './useFaceRecognitionStatus': {
      freshFaceDetections: statusModule.freshFaceDetections,
      useFaceRecognitionStatus: (...args) => { polls.push(args); return { status, error } },
    },
  })
  const props = { department: 'electronics_electrician', cameras: [camera(1), camera(2), camera(3, true, false)], selectedCamera: 'camera_1', loading: false,
    message: '画面读取失败', frameConnected: false, frameContent: React.createElement('img', { src: '/frame.jpg', alt: '后端标注帧' }) }
  let html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, props))
  for (const text of ['摄像头状态', '在线', '摄像头1', '启用摄像头', '2 路', '当前检测人脸', '3 人', '允许 1 / 未授权 1 / 未知 1', '允许人员', '未授权人员报警',
    '测试甲', '测试乙', '未知人员', 'J001', 'J002', '88.0%', '91.0%', '42.0%', '/frame.jpg']) assert.ok(html.includes(text), text)
  assert.equal((html.match(/<article /g) || []).length, 4)
  assert.equal((html.match(/<rect |<text |<svg[^>]*viewBox/g) || []).length, 0)
  assert.deepEqual(polls.at(-1), ['camera_1', true])
  for (const change of [{ online: false }, { reason: 'unknown', count: null }, { detections: [] },
    { updated_at: new Date(Date.now() - 3000).toISOString() }, { updated_at: null }]) {
    status = { ...valid, ...change }
    html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, props))
    assert.equal(html.includes('测试甲'), false)
    assert.ok(html.includes('0 人') && html.includes('允许 0 / 未授权 0 / 未知 0'))
    assert.equal(html.includes('未授权人员报警'), false)
  }
  status = { ...valid, reason: 'unknown', count: 1, detections: [valid.detections[2]] }
  html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, props))
  assert.ok(html.includes('报警：当前画面存在未知人员'))
  status = valid
  html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, { ...props, cameras: [camera(1, false)] }))
  assert.ok(html.includes('离线') && html.includes('摄像头已停用'))
  assert.equal(html.includes('测试甲'), false)
  status = null; error = '识别状态异常'
  html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, { ...props, frameConnected: true }))
  assert.ok(html.includes('在线') && html.includes('识别状态异常') && html.includes('实时画面'))
  assert.equal(html.includes('测试甲'), false)
  renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, { ...props, cameras: [] }))
  assert.deepEqual(polls.at(-1), ['camera_1', false])
})

test('API 请求携带登录凭据、摄像头过滤和取消信号', async () => {
  const api = await compile('src/components/face_recognition/api.ts', { '@/lib/aivision': { AIVISION_URL: '/aivision/' } })
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return { ok: true, status: 200, json: async () => ({ items: [] }) }
  }
  try {
    const signal = new AbortController().signal
    await api.getFaceRecognitionStatus('camera / 一', signal)
    await api.getRecognitionRecords('haoda_company', 2, '7', signal)
    assert.equal(calls[0][0], `/aivision/api/features/recognize_face/cameras/${encodeURIComponent('camera / 一')}/status`)
    assert.equal(calls[1][0], '/aivision/api/face-recognition/records?department=haoda_company&page=2&page_size=20&camera_id=7')
    assert.equal(calls[0][1].credentials, 'include')
    assert.equal(calls[0][1].signal, signal)
    await api.getFacePersons({ page: 2, page_size: 10, keyword: '姓名', source: 'two', is_active: false, is_allowed: false }, signal)
    const params = new URL(calls[2][0], 'http://localhost').searchParams
    assert.deepEqual(Object.fromEntries(params), { page: '2', page_size: '10', keyword: '姓名', source: 'two', is_active: 'false', is_allowed: 'false' })
    await api.updateFacePerson(7, true, signal)
    assert.equal(calls[3][0], '/aivision/api/face-recognition/persons/7')
    assert.equal(calls[3][1].method, 'PATCH')
    assert.equal(calls[3][1].credentials, 'include')
    assert.deepEqual(JSON.parse(calls[3][1].body), { is_allowed: true })
    globalThis.fetch = async () => ({ ok: false, status: 403 })
    await assert.rejects(api.getRecognitionRecords('haoda_company', 1, ''), /HTTP 403/)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('status 使用单个串行轮询，请求挂起时按更新时间清空，切换和失败不残留结果', async () => {
  const harness = hookHarness()
  let poll, options, key = 'camera_1', enabled = true
  let reply = { camera_key: key, online: true, reason: 'normal', updated_at: new Date().toISOString(), detections: [{ person_name: '甲' }] }
  const timers = new Map()
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout
  let timerId = 0
  globalThis.setTimeout = (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId }
  globalThis.clearTimeout = (id) => timers.delete(id)
  try {
    const { useFaceRecognitionStatus } = await compile('src/components/face_recognition/useFaceRecognitionStatus.ts', {
      react: harness.hooks,
      '@/hooks/use-serial-poll': { useSerialPoll: (task, settings) => { poll = task; options = settings } },
      './api': { getFaceRecognitionStatus: async () => reply },
    })
    await harness.mount(() => useFaceRecognitionStatus(key, enabled))
    assert.equal(options.enabled, true)
    assert.equal(options.restartKey, key)
    await poll(new AbortController().signal)
    let state = await harness.flush()
    assert.equal(state.status.detections[0].person_name, '甲')
    assert.equal(timers.size, 1)
    const expiry = [...timers.values()][0]
    assert.ok(expiry.delay <= 2000)
    expiry.callback()
    state = await harness.flush()
    assert.equal(state.status, null)
    await poll(new AbortController().signal)
    await harness.flush()
    key = 'camera_2'; harness.rerender()
    assert.equal(await harness.flush(), null)
    assert.equal(options.restartKey, 'camera_2')
    reply = { ...reply, camera_key: key }
    await poll(new AbortController().signal)
    await harness.flush()
    options.onError(new Error('识别状态异常'))
    state = await harness.flush()
    assert.equal(state.status, null)
    assert.equal(state.error, '识别状态异常')
    enabled = false; harness.rerender()
    assert.equal(await harness.flush(), null)
    assert.equal(options.enabled, false)
  } finally {
    harness.dispose()
    globalThis.setTimeout = originalSet; globalThis.clearTimeout = originalClear
  }
})

test('配置读取全局池与真实检测阈值，保存后单事件刷新当前配置，移除后选择下一路或清空', async () => {
  const harness = hookHarness()
  const previousWindow = globalThis.window
  const target = new EventTarget()
  globalThis.window = target
  let pool = [camera(1), camera(2), camera(3, false, false)]
  const values = { roi_pos: [[0, 0], [1, 0], [1, 1]], detection_threshold: .37, similarity_threshold: .81, cap_interval: .5, record_cooldown_seconds: 30, record_enabled: true, alarm_interval: 5 }
  const configs = new Map(pool.map((item) => [item.shm_name, { enable: item.functions.recognize_face, value: { ...values }, alarm: structuredClone(recognitionAlarm) }]))
  const listCalls = [], configCalls = [], saves = []
  let added = 0, removed = 0
  const addListener = target.addEventListener.bind(target), removeListener = target.removeEventListener.bind(target)
  target.addEventListener = (...args) => { added++; addListener(...args) }
  target.removeEventListener = (...args) => { removed++; removeListener(...args) }
  try {
    const { useRecognitionConfig } = await compile('src/components/face_recognition/useRecognitionConfig.ts', {
      react: harness.hooks, '@/auth/useAuth': { useAuth: () => ({ isAdmin: true }) }, './api': faceApi,
      '@/components/AiVisionRoiEditor.geometry': { parseNormalizedRoi: JSON.parse },
      '@/lib/aivision': {
        ...cameraApi,
        getAiVisionCameras: async (...args) => { listCalls.push(args); return structuredClone(pool) },
        getAiVisionFeatureConfig: async (_feature, key) => {
          configCalls.push(key)
          return { camera: { enable: pool.find((item) => item.shm_name === key).enabled }, config: structuredClone(configs.get(key)) }
        },
        saveAiVisionFeatureConfig: async (_feature, key, config) => {
          saves.push({ key, config }); configs.set(key, structuredClone(config))
          pool = pool.map((item) => item.shm_name === key ? { ...item, functions: { recognize_face: config.enable } } : item)
          target.dispatchEvent(new Event('aivision:cameras-changed'))
          return { config }
        },
      },
    })
    let state = await harness.mount(() => useRecognitionConfig('electronics_electrician'))
    assert.deepEqual(listCalls, [['electronics_electrician']])
    assert.deepEqual(configCalls, ['camera_1'])
    assert.equal(state.cameras.length, 3)
    assert.equal(state.form.detectionThreshold, '0.37')
    assert.equal(state.form.threshold, '0.81')
    assert.equal(state.canSave, true)
    state.setForm((form) => ({ ...form, detectionThreshold: '0.62' }))
    state = await harness.flush()
    await state.save(); state = await harness.flush()
    assert.equal(saves[0].config.value.detection_threshold, .62)
    assert.equal(saves[0].config.value.similarity_threshold, .81)
    assert.deepEqual(saves[0].config.alarm, recognitionAlarm)
    assert.deepEqual(saves[0].config.value.roi_pos, values.roi_pos)
    assert.equal(state.form.detectionThreshold, '0.62')
    assert.equal(listCalls.length, 2)
    assert.deepEqual(configCalls, ['camera_1', 'camera_1'])
    state.setAlarm({ ...state.config.alarm,
      wechat: { enable: true, parm: { user: 'updated-user' } },
      horn: { enable: true, parm: { horn_id: 3, horn_event_id: 12 } },
    })
    state.setForm((form) => ({ ...form, alarmInterval: '15' }))
    state = await harness.flush()
    await state.save(); state = await harness.flush()
    assert.deepEqual(saves[1].config.value, { ...saves[0].config.value, alarm_interval: 15 })
    assert.deepEqual(state.config, saves[1].config)
    assert.equal(state.config.alarm.wechat.parm.user, 'updated-user')
    assert.deepEqual(state.config.alarm.horn, { enable: true, parm: { horn_id: 3, horn_event_id: 12 } })
    state.setHornError('已绑定的喇叭设备不存在')
    state = await harness.flush(); await state.save(); state = await harness.flush()
    assert.match(state.message, /不存在/)
    assert.equal(saves.length, 2)
    state.setHornError(null)
    for (const invalid of ['', '0', '-1', 'NaN']) {
      state.setForm((form) => ({ ...form, alarmInterval: invalid }))
      state = await harness.flush(); await state.save(); state = await harness.flush()
      assert.equal(saves.length, 2)
    }
    state.setForm((form) => ({ ...form, alarmInterval: '15' }))
    for (const invalid of ['', '-0.01', '1.01']) {
      state.setForm((form) => ({ ...form, detectionThreshold: invalid }))
      state = await harness.flush(); await state.save(); state = await harness.flush()
      assert.equal(saves.length, 2)
    }
    configs.get('camera_1').enable = false
    pool[0].functions.recognize_face = false
    target.dispatchEvent(new Event('aivision:cameras-changed')); state = await harness.flush()
    assert.equal(state.cameraKey, 'camera_1')
    assert.equal(state.config.enable, false)
    assert.equal(state.canSave, true)
    state.setForm((form) => ({ ...form, detectionThreshold: '0.44' }))
    state = await harness.flush(); await state.save(); state = await harness.flush()
    assert.equal(saves.at(-1).config.enable, false)
    assert.equal(saves.at(-1).config.value.detection_threshold, .44)
    // 停用摄像头保留编辑选择，新建后可以明确选中新摄像头。
    pool.push(camera(4)); configs.set('camera_4', { enable: true, value: { ...values, detection_threshold: .24 }, alarm: structuredClone(recognitionAlarm) })
    target.dispatchEvent(new Event('aivision:cameras-changed')); state = await harness.flush()
    assert.equal(state.cameraKey, 'camera_1')
    state.selectCamera('camera_4'); state = await harness.flush()
    assert.equal(state.form.detectionThreshold, '0.24')
    configs.get('camera_4').value.detection_threshold = .73
    target.dispatchEvent(new Event('aivision:cameras-changed')); state = await harness.flush()
    assert.equal(state.form.detectionThreshold, '0.73')
    assert.equal(added, 1)
  } finally {
    harness.dispose(); globalThis.window = previousWindow
  }
  assert.equal(removed, 1)
})

test('复制回调切换并读取目标真实参数与 ROI，快慢列表刷新均保留停用目标且不重复读取', async () => {
  for (const targetEnabled of [false, true]) {
    for (const slowList of [false, true]) {
      const harness = hookHarness()
      const previousWindow = globalThis.window
      const events = new EventTarget()
      globalThis.window = events
      const pool = [camera(1), camera(2, true, targetEnabled)]
      const original = { roi_pos: [], detection_threshold: .35, similarity_threshold: .8, cap_interval: .5, record_cooldown_seconds: 30, record_enabled: true, alarm_interval: 5 }
      const copied = { ...original, roi_pos: [[0, 0], [1, 0], [1, 1]], detection_threshold: .62, similarity_threshold: .77 }
      let deferList = false, releaseList, releaseConfig
      const reads = []
      try {
        const { useRecognitionConfig } = await compile('src/components/face_recognition/useRecognitionConfig.ts', {
          react: harness.hooks, '@/auth/useAuth': { useAuth: () => ({ isAdmin: true }) }, './api': faceApi,
          '@/components/AiVisionRoiEditor.geometry': { parseNormalizedRoi: JSON.parse },
          '@/lib/aivision': { ...cameraApi,
            getAiVisionCameras: async () => {
              if (deferList) await new Promise((resolve) => { releaseList = resolve })
              return structuredClone(pool)
            },
            getAiVisionFeatureConfig: async (_feature, key) => {
              reads.push(key)
              if (key === 'camera_2') await new Promise((resolve) => { releaseConfig = resolve })
              return { config: { enable: key === 'camera_1' || targetEnabled, value: key === 'camera_1' ? original : copied, alarm: structuredClone(recognitionAlarm) } }
            },
          },
        })
        let state = await harness.mount(() => useRecognitionConfig('electronics_electrician'))
        const { RecognitionConfigView } = await compile('src/components/face_recognition/RecognitionConfigView.tsx', {
          ...sharedUi, '@/components/detection/DetectionConfigUi': ui, '@/components/ui/input': ui,
          '@/components/ui/switch': ui, '@/components/ui/tabs': ui, '@/components/FeatureCameraManager': ui, './api': faceApi,
          './useRecognitionConfig': { useRecognitionConfig: () => state },
        })
        // saveAiVisionFeatureConfig 先发出事件，再由普通管理器调用 onConfigCopied。
        deferList = slowList
        events.dispatchEvent(new Event('aivision:cameras-changed'))
        if (!slowList) state = await harness.flush()
        const callback = elements(RecognitionConfigView({ department: 'electronics_electrician' }), (node) => Boolean(node.props?.onConfigCopied))[0].props.onConfigCopied
        const pending = callback('camera_2')
        state = await harness.flush()
        assert.equal(state.cameraKey, 'camera_2')
        assert.equal(state.canSave, false)
        releaseConfig()
        await pending
        state = await harness.flush()
        assert.equal(state.form.threshold, '0.77')
        if (slowList) { releaseList(); state = await harness.flush() }
        assert.equal(state.cameraKey, 'camera_2')
        assert.equal(state.canSave, true)
        assert.equal(state.form.detectionThreshold, '0.62')
        assert.equal(state.form.roi, JSON.stringify(copied.roi_pos))
        assert.equal(reads.filter((key) => key === 'camera_2').length, 1)
        assert.equal(pool[1].functions.recognize_face, targetEnabled)
        assert.equal(elements(RecognitionConfigView({ department: 'electronics_electrician' }), (node) => node.props?.value === 'camera_2').length > 0, true)
      } finally {
        harness.dispose(); globalThis.window = previousWindow
      }
    }
  }
})

test('七个配置页签复用企微与喇叭组件，参数边界及只读权限保持一致', async () => {
  let readonly = false, changedAlarm
  const state = {
    cameras: [camera(1)], cameraKey: 'camera_1', form: { detectionThreshold: '.37', alarmInterval: '5' },
    config: { enable: true, value: {}, alarm: recognitionAlarm },
    setAlarm: (alarm) => { changedAlarm = alarm },
  }
  const { RecognitionConfigView } = await compile('src/components/face_recognition/RecognitionConfigView.tsx', {
    ...sharedUi, '@/components/detection/DetectionConfigUi': { ...ui, DetectionConfigTab: 'DetectionConfigTab', DetectionSaveBar: 'DetectionSaveBar', DetectionConfigCardHeader: wrapper, DetectionConfigCardContent: wrapper, DetectionConfigTabsList: wrapper }, '@/components/ui/input': { Input: 'input' },
    '@/components/ui/switch': ui, '@/components/ui/tabs': ui, '@/components/FeatureCameraManager': ui, './api': faceApi,
    './useRecognitionConfig': { useRecognitionConfig: () => ({ ...state, disabled: readonly, canSave: !readonly }) },
  })
  const tree = RecognitionConfigView({ department: 'electronics_electrician' })
  const field = elements(tree, (node) => node.props?.id === 'identity-detectionThreshold')[0]
  assert.equal(field.props.value, '.37')
  assert.deepEqual([field.props.min, field.props.max, field.props.step], ['0', '1', '0.01'])
  assert.deepEqual(elements(tree, (node) => node.type === 'DetectionConfigTab').map((node) => node.props.children), ['摄像头', '识别参数', 'ROI 配置', '模型配置', '报警推送', '喇叭配置', '人员权限'])
  const wechat = elements(tree, (node) => node.type === 'WechatAlarmSettings')[0]
  const horn = elements(tree, (node) => node.type === 'HornAlarmBinding')[0]
  assert.deepEqual(wechat.props.value, recognitionAlarm.wechat)
  wechat.props.onChange({ enable: false, parm: { user: 'new-user' } })
  assert.deepEqual(changedAlarm.horn, recognitionAlarm.horn)
  assert.equal(changedAlarm.wechat.parm.user, 'new-user')
  horn.props.onChange({ enable: false, parm: { horn_id: 3, horn_event_id: 12 } })
  assert.deepEqual(changedAlarm.wechat, recognitionAlarm.wechat)
  assert.deepEqual(changedAlarm.horn.parm, { horn_id: 3, horn_event_id: 12 })
  assert.equal(elements(tree, (node) => node.type === 'HornDeviceManager').length, 1)
  readonly = true
  const readonlyTree = RecognitionConfigView({ department: 'electronics_electrician' })
  for (const type of ['WechatAlarmSettings', 'HornAlarmBinding', 'DetectionSaveBar']) {
    assert.ok(elements(readonlyTree, (node) => node.type === type).every((node) => node.props.disabled))
  }
})

test('人员权限保存等待后端并重新读取状态，查看用户不能修改', async () => {
  const harness = hookHarness()
  let isAdmin = true, finishSave, readCalls = 0
  const writes = []
  let page = { total: 1, page: 1, page_size: 20, items: [{ id: 1, is_allowed: false }] }
  const { useFacePersons } = await compile('src/components/face_recognition/useRecognitionConfig.ts', {
    react: harness.hooks, '@/auth/useAuth': { useAuth: () => ({ isAdmin }) },
    '@/components/AiVisionRoiEditor.geometry': { parseNormalizedRoi: JSON.parse }, '@/lib/aivision': cameraApi,
    './api': {
      ...faceApi,
      getFacePersons: async () => { readCalls++; return structuredClone(page) },
      updateFacePerson: (...args) => { writes.push(args); return new Promise((resolve) => { finishSave = resolve }) },
    },
  })
  try {
    let state = await harness.mount(useFacePersons)
    assert.equal(readCalls, 1)
    const pending = state.setPersonAllowed(1, true)
    state = await harness.flush()
    assert.equal(state.result.items[0].is_allowed, false)
    assert.equal(state.savingId, 1)
    page.items[0].is_allowed = true
    finishSave(page.items[0])
    await pending
    state = await harness.flush()
    assert.equal(readCalls, 2)
    assert.equal(state.result.items[0].is_allowed, true)
    assert.equal(state.savingId, null)
    assert.ok(state.message.includes('重新读取'))
    isAdmin = false; harness.rerender()
    state = await harness.flush()
    await state.setPersonAllowed(1, false)
    assert.equal(writes.length, 1)
  } finally { harness.dispose() }
})

test('记录筛选只包含 recognize_face 摄像头，缩略图使用受控 URL 并复用平台大图预览', async () => {
  const harness = hookHarness()
  const requests = []
  const Preview = (props) => React.createElement('aside', null, props.title)
  const { RecognitionRecordsView } = await compile('src/components/face_recognition/RecognitionRecordsView.tsx', {
    ...sharedUi, react: harness.hooks,
    '@/components/ImagePreviewDialog': { ImagePreviewDialog: Preview },
    '@/lib/aivision': { ...cameraApi, getAiVisionCameras: async (...args) => { requests.push(args); return [camera(1), camera(2, true, false)] } },
    './api': { ...faceApi, recognitionImageUrl: (path) => `/aivision${path}`, getRecognitionRecords: async () => ({ total: 1, page: 1, page_size: 20,
      items: [{ id: 1, camera_id: 1, person_name: '测试甲', similarity: .9, recognized_at: '2026-09-01T10:00:00Z', image_url: '/api/face-recognition/records/1/image' }] }) },
  })
  try {
    let tree = await harness.mount(() => RecognitionRecordsView({ department: 'electronics_electrician' }))
    assert.deepEqual(requests, [['electronics_electrician']])
    const html = renderToStaticMarkup(tree)
    assert.ok(html.includes('摄像头1') && !html.includes('摄像头2'))
    assert.ok(html.includes('src="/aivision/api/face-recognition/records/1/image"'))
    const button = elements(tree, (node) => node.props?.['aria-label'] === '放大查看识别截图')[0]
    button.props.onClick(); tree = await harness.flush()
    const preview = elements(tree, (node) => node.type === Preview)[0]
    assert.equal(preview.props.title, '识别截图')
    assert.equal(preview.props.src, '/aivision/api/face-recognition/records/1/image')
    preview.props.onClose(); tree = await harness.flush()
    assert.equal(elements(tree, (node) => node.type === Preview).length, 0)
  } finally { harness.dispose() }
})

async function mountCameraManager({ feature = 'recognize_face', isAdmin = true, failOrder = false, deferOrder = false } = {}) {
  const harness = hookHarness()
  let stored = [camera(1), camera(2, true, false), camera(3, false, false), camera(4, false, true)]
    .map((item) => ({ ...item, functions: { [feature]: item.functions.recognize_face } }))
  const foreign = { ...camera(5), department: 'fulida_company', functions: { [feature]: true } }
  let displayed = structuredClone([...stored, foreign]), releaseOrder
  const configs = new Map(stored.map((item) => [item.shm_name, { enable: item.functions[feature], value: { threshold: item.camera_id / 10 } }]))
  const writes = [], orders = [], selections = [], copied = [], events = []
  const refresh = async () => { events.push('reload'); displayed = structuredClone([...stored, foreign]) }
  const { FeatureCameraManager } = await compile('src/components/FeatureCameraManager.tsx', {
    ...sharedUi, react: harness.hooks,
    '@/auth/useAuth': { useAuth: () => ({ isAdmin }) },
    '@/components/ui/switch': ui,
    '@/components/detection/DetectionConfigUi': ui,
    '@/components/logistics_single_person/LogisticsCameraCreateDialog': ui,
    '@/lib/camera-events': { notifyPlatformCamerasChanged: () => events.push('notify') },
    '@/lib/aivision': {
      ...cameraApi,
      getAiVisionFeatureConfig: async (_feature, key) => ({ config: structuredClone(configs.get(key)) }),
      saveAiVisionFeatureConfig: async (requestedFeature, key, config) => {
        assert.equal(requestedFeature, feature)
        writes.push({ key, config: structuredClone(config) })
        configs.set(key, structuredClone(config))
        stored = stored.map((item) => item.shm_name === key ? { ...item, functions: { [feature]: config.enable } } : item)
        events.push('save')
      },
      saveAiVisionCameraOrder: async (department, cameraIds) => {
        orders.push({ department, cameraIds })
        if (deferOrder) await new Promise((resolve) => { releaseOrder = resolve })
        if (failOrder) throw new Error('摄像头集合已变化，请重新加载')
        stored = cameraIds.map((id, sort_order) => ({ ...stored.find((item) => item.camera_id === id), sort_order }))
        events.push('order')
      },
    },
  })
  const render = () => FeatureCameraManager({ cameras: displayed, feature, department: 'electronics_electrician',
    currentCameraName: 'camera_1', onSelectCamera: (key) => selections.push(key),
    onCamerasChanged: refresh, onConfigCopied: async (key) => copied.push(key) })
  const tree = await harness.mount(render)
  return { harness, tree, writes, orders, selections, copied, events, releaseOrder: () => releaseOrder(),
    stored: () => structuredClone(stored) }
}

const control = (tree, label) => {
  const found = elements(tree, (node) => node.props?.['aria-label'] === label)[0]
  assert.ok(found, label)
  return found.props
}

for (const feature of ['blocks', 'detect_door', 'detect_face', 'recognize_face', 'detect_human', 'detect_phone']) {
  test(`${feature} 复用统一 Switch，物理关闭时可停用现有检测，停用行保留且可选`, async () => {
    const page = await mountCameraManager({ feature })
    try {
      let tree = page.tree
      assert.equal(elements(tree, (node) => Boolean(node.props?.onCheckedChange)).length, 4)
      assert.equal(control(tree, '摄像头3：启用检测').disabled, true)
      assert.equal(Boolean(control(tree, '摄像头4：停用检测').disabled), false)
      control(tree, '摄像头3：启用检测').onCheckedChange(true)
      tree = await page.harness.flush()
      assert.deepEqual(page.writes, [])
      assert.ok(renderToStaticMarkup(tree).includes('请先在平台启用该摄像头'))
      control(tree, '摄像头2：启用检测').onCheckedChange(true)
      tree = await page.harness.flush()
      assert.equal(page.writes.at(-1).config.enable, true)
      assert.deepEqual(page.events.slice(-3), ['save', 'reload', 'notify'])
      control(tree, '摄像头2：停用检测').onCheckedChange(false)
      tree = await page.harness.flush()
      assert.equal(page.writes.at(-1).config.enable, false)
      control(tree, '摄像头4：停用检测').onCheckedChange(false)
      tree = await page.harness.flush()
      assert.equal(page.writes.at(-1).key, 'camera_4')
      assert.equal(page.writes.at(-1).config.enable, false)
      assert.equal(control(tree, '摄像头4：启用检测').disabled, true)
      assert.equal(elements(tree, (node) => Boolean(node.props?.onCheckedChange)).length, 4)
      const select = elements(tree, (node) => node.type === 'button' && node.props?.['aria-pressed'] === false)[0]
      select.props.onClick()
      assert.deepEqual(page.selections, ['camera_2'])
      const html = renderToStaticMarkup(tree)
      assert.ok(html.includes('当前正在编辑'))
      assert.equal(html.includes('从已有摄像头加入当前功能'), false)
      assert.equal(html.includes('摄像头5'), false)
    } finally { page.harness.dispose() }
  })
}

test('上下移提交完整主键顺序，等待持久化后重读；跨事业部摄像头不参与', async () => {
  const page = await mountCameraManager({ deferOrder: true })
  try {
    let tree = page.tree
    assert.equal(control(tree, '摄像头1上移').disabled, true)
    assert.equal(control(tree, '摄像头4下移').disabled, true)
    control(tree, '摄像头2上移').onClick()
    tree = await page.harness.flush()
    assert.deepEqual(page.orders[0], { department: 'electronics_electrician', cameraIds: [2, 1, 3, 4] })
    assert.deepEqual(page.stored().map((item) => item.camera_id), [1, 2, 3, 4])
    assert.ok(renderToStaticMarkup(tree).indexOf('摄像头1') < renderToStaticMarkup(tree).indexOf('摄像头2'))
    assert.ok(elements(tree, (node) => Boolean(node.props?.onCheckedChange)).every((node) => node.props.disabled))
    page.releaseOrder(); tree = await page.harness.flush()
    assert.deepEqual(page.stored().map((item) => item.camera_id), [2, 1, 3, 4])
    assert.deepEqual(page.events.slice(-3), ['order', 'reload', 'notify'])
    control(tree, '摄像头2下移').onClick(); await page.harness.flush()
    assert.deepEqual(page.orders[1].cameraIds, [1, 2, 3, 4])
    page.releaseOrder(); await page.harness.flush()
    assert.deepEqual(page.stored().map((item) => item.sort_order), [0, 1, 2, 3])
  } finally { page.harness.dispose() }
})

test('排序冲突重新加载，保留后端顺序并展示错误', async () => {
  const page = await mountCameraManager({ failOrder: true })
  try {
    control(page.tree, '摄像头2上移').onClick()
    const tree = await page.harness.flush()
    assert.deepEqual(page.stored().map((item) => item.camera_id), [1, 2, 3, 4])
    assert.deepEqual(page.events, ['reload'])
    assert.ok(renderToStaticMarkup(tree).includes('摄像头集合已变化'))
  } finally { page.harness.dispose() }
})

test('Viewer 的 Switch 和排序按钮只读，直接调用回调也不能提交', async () => {
  const page = await mountCameraManager({ isAdmin: false })
  try {
    const toggle = control(page.tree, '摄像头2：启用检测')
    const move = control(page.tree, '摄像头2上移')
    assert.equal(toggle.disabled, true)
    assert.equal(move.disabled, true)
    toggle.onCheckedChange(true); move.onClick(); await page.harness.flush()
    assert.deepEqual(page.writes, [])
    assert.deepEqual(page.orders, [])
  } finally { page.harness.dispose() }
})

test('复制当前功能配置保留停用目标开关、Camera 归属、物理开关及排序', async () => {
  const page = await mountCameraManager()
  try {
    const before = page.stored()
    const selects = elements(page.tree, (node) => Boolean(node.props?.onValueChange))
    selects[0].props.onValueChange('camera_1'); selects[1].props.onValueChange('camera_3')
    let tree = await page.harness.flush()
    const copy = elements(tree, (node) => node.props?.onClick && JSON.stringify(node.props.children).includes('复制配置'))[0]
    await copy.props.onClick(); tree = await page.harness.flush()
    assert.deepEqual(page.writes, [{ key: 'camera_3', config: { enable: false, value: { threshold: .1 } } }])
    assert.deepEqual(page.copied, ['camera_3'])
    assert.deepEqual(page.stored(), before)
    assert.deepEqual(page.orders, [])
    assert.equal(control(tree, '摄像头3：启用检测').disabled, true)
  } finally { page.harness.dispose() }
})
