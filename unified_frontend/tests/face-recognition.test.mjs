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

test('人脸身份识别只列在电子电工事业部，原有报警权限不变', async () => {
  const permissions = await compile('src/auth/permissions.ts')
  const electronic = { role: 'viewer', departments: ['electronics_electrician'] }
  assert.equal(permissions.hasPageAccess(electronic, 'face-recognition'), true)
  for (const department of ['research_institute', 'general_electric', 'electrical_components']) {
    assert.equal(permissions.hasPageAccess({ role: 'viewer', departments: [department] }, 'face-recognition'), false)
  }
  assert.equal(permissions.hasPageAccess({ role: 'admin' }, 'face-recognition'), true)
  assert.equal(permissions.hasPageAccess(null, 'face-recognition'), false)
  assert.equal(permissions.getAccessibleAlarmEventTypes(electronic).includes('recognize_face'), false)
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
const faceApi = { FACE_FEATURE: 'recognize_face', FACE_DEPARTMENT: 'electronics_electrician' }
const camera = (id, enabled = true, feature = true) => ({
  id: String(id), camera_id: id, shm_name: `camera_${id}`, name: `摄像头${id}`, enabled,
  functions: { recognize_face: feature },
})
const sharedUi = {
  'lucide-react': icons,
  '@/components/ui/button': ui, '@/components/ui/card': ui, '@/components/ui/label': ui,
  '@/components/ui/select': ui, '@/components/ui/badge': ui,
  '@/components/monitor/ResizableMonitorLayout': { ResizableMonitorLayout: wrapper },
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
    online: true, reason: 'normal', updated_at: new Date().toISOString(), count: 3,
    detections: [
      { bbox: [10, 20, 100, 150], matched: true, person_id: 1, person_name: '测试甲', job_no: 'J001', similarity: .88 },
      { bbox: [200, 20, 300, 150], matched: true, person_id: 2, person_name: '测试乙', job_no: 'J002', similarity: .91 },
      { bbox: [400, 20, 500, 150], matched: false, person_id: null, person_name: '未知人员', similarity: .42 },
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
  const props = { cameras: [camera(1), camera(2), camera(3, true, false)], selectedCamera: 'camera_1', loading: false,
    message: '画面读取失败', frameConnected: false, frameContent: React.createElement('img', { src: '/frame.jpg', alt: '后端标注帧' }) }
  let html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, props))
  for (const text of ['摄像头状态', '在线', '摄像头1', '启用摄像头', '2 路', '当前检测人脸', '3 人', '已识别 2 / 未知 1',
    '测试甲', '测试乙', '未知人员', 'J001', 'J002', '88.0%', '91.0%', '42.0%', '/frame.jpg']) assert.ok(html.includes(text), text)
  assert.equal((html.match(/<article /g) || []).length, 4)
  assert.equal((html.match(/<rect |<text |<svg[^>]*viewBox/g) || []).length, 0)
  assert.deepEqual(polls.at(-1), ['camera_1', true])
  for (const change of [{ online: false }, { reason: 'unknown' }, { detections: [] },
    { updated_at: new Date(Date.now() - 3000).toISOString() }, { updated_at: null }]) {
    status = { ...valid, ...change }
    html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, props))
    assert.equal(html.includes('测试甲'), false)
    assert.ok(html.includes('0 人') && html.includes('已识别 0 / 未知 0'))
  }
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
    await api.getRecognitionRecords(2, '7', signal)
    assert.equal(calls[0][0], `/aivision/api/features/recognize_face/cameras/${encodeURIComponent('camera / 一')}/status`)
    assert.equal(calls[1][0], '/aivision/api/face-recognition/records?page=2&page_size=20&camera_id=7')
    assert.equal(calls[0][1].credentials, 'include')
    assert.equal(calls[0][1].signal, signal)
    globalThis.fetch = async () => ({ ok: false, status: 403 })
    await assert.rejects(api.getRecognitionRecords(1, ''), /HTTP 403/)
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
  const values = { roi_pos: [], detection_threshold: .37, similarity_threshold: .81, cap_interval: .5, record_cooldown_seconds: 30, record_enabled: true }
  const configs = new Map(pool.map((item) => [item.shm_name, { enable: item.functions.recognize_face, value: { ...values } }]))
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
    let state = await harness.mount(useRecognitionConfig)
    assert.deepEqual(listCalls, [[]])
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
    assert.equal(state.form.detectionThreshold, '0.62')
    assert.equal(listCalls.length, 2)
    assert.deepEqual(configCalls, ['camera_1', 'camera_1'])
    for (const invalid of ['', '-0.01', '1.01']) {
      state.setForm((form) => ({ ...form, detectionThreshold: invalid }))
      state = await harness.flush(); await state.save(); state = await harness.flush()
      assert.equal(saves.length, 1)
    }
    await assert.rejects(state.setCameraEnabled('camera_3', true), /摄像头已停用/)
    assert.equal(saves.length, 1)
    await state.setCameraEnabled('camera_1', false); state = await harness.flush()
    assert.equal(state.cameraKey, 'camera_2')
    await state.setCameraEnabled('camera_2', false); state = await harness.flush()
    assert.equal(state.cameraKey, '')
    assert.equal(state.canSave, false)
    assert.equal(state.form.detectionThreshold, '')
    // 复用同一事件处理新建、加入与复制后的列表和配置刷新。
    pool.push(camera(4)); configs.set('camera_4', { enable: true, value: { ...values, detection_threshold: .24 } })
    target.dispatchEvent(new Event('aivision:cameras-changed')); state = await harness.flush()
    assert.equal(state.cameraKey, 'camera_4')
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

test('摄像头管理显示停用状态、禁止加入，并在复制时保留目标 Feature 开关', async () => {
  for (const targetEnabled of [false, true]) {
    const harness = hookHarness()
    const saves = [], reads = [], adds = []
    const pool = [camera(1), camera(2, true, targetEnabled), camera(3, false, false), camera(4, false, true)]
    const { FeatureCameraManager } = await compile('src/components/FeatureCameraManager.tsx', {
      ...sharedUi, react: harness.hooks,
      '@/components/detection/DetectionConfigUi': ui,
      '@/components/logistics_single_person/LogisticsCameraCreateDialog': ui,
      '@/lib/camera-events': { notifyPlatformCamerasChanged() {} },
      '@/lib/aivision': {
        ...cameraApi,
        getAiVisionFeatureConfig: async (_feature, key) => {
          reads.push(key)
          return { config: { enable: key === 'camera_1' || targetEnabled, value: { detection_threshold: key === 'camera_1' ? .38 : .9 } } }
        },
        saveAiVisionFeatureConfig: async (...args) => saves.push(args),
      },
    })
    try {
      let tree = await harness.mount(() => FeatureCameraManager({ cameras: pool, feature: 'recognize_face', department: 'electronics_electrician',
        currentCameraName: 'camera_1', disabled: false, onSelectCamera() {}, onAddCamera: async (key) => adds.push(key), onRemoveCamera: async () => {} }))
      let selects = elements(tree, (node) => Boolean(node.props?.onValueChange))
      selects[0].props.onValueChange('camera_3'); tree = await harness.flush()
      const join = elements(tree, (node) => node.props?.onClick && elements(node.props.children, () => false).length === 0
        && JSON.stringify(node.props.children).includes('加入当前功能'))[0]
      assert.equal(join.props.disabled, true)
      await join.props.onClick()
      assert.deepEqual(adds, [])
      const unavailable = elements(tree, (node) => node.props?.value === 'camera_3' && node.props.disabled)
      assert.ok(unavailable.length > 0)
      assert.ok(renderToStaticMarkup(tree).includes('摄像头已停用'))
      selects = elements(tree, (node) => Boolean(node.props?.onValueChange))
      selects[1].props.onValueChange('camera_1'); selects[2].props.onValueChange('camera_2')
      tree = await harness.flush()
      const copy = elements(tree, (node) => node.props?.onClick && JSON.stringify(node.props.children).includes('复制配置'))[0]
      await copy.props.onClick()
      assert.deepEqual(reads, ['camera_1', 'camera_2'])
      assert.equal(saves[0][2].enable, targetEnabled)
      assert.equal(saves[0][2].value.detection_threshold, .38)
    } finally { harness.dispose() }
  }
})

test('识别参数控件使用 detection_threshold 对应值及 0～1 / 0.01 边界', async () => {
  const { RecognitionConfigView } = await compile('src/components/face_recognition/RecognitionConfigView.tsx', {
    ...sharedUi, '@/components/detection/DetectionConfigUi': ui, '@/components/ui/input': { Input: 'input' },
    '@/components/ui/switch': ui, '@/components/ui/tabs': ui, '@/components/FeatureCameraManager': ui, './api': faceApi,
    './useRecognitionConfig': { useRecognitionConfig: () => ({ cameras: [], form: { detectionThreshold: '.37' }, disabled: false }) },
  })
  const tree = RecognitionConfigView()
  const field = elements(tree, (node) => node.props?.id === 'identity-detectionThreshold')[0]
  assert.equal(field.props.value, '.37')
  assert.deepEqual([field.props.min, field.props.max, field.props.step], ['0', '1', '0.01'])
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
    let tree = await harness.mount(RecognitionRecordsView)
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
