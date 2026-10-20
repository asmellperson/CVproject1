import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const nativeRequire = createRequire(import.meta.url)
const sourceRoot = new URL('../src/', import.meta.url)

function loadSource(path, overrides = {}) {
  const cache = new Map()
  function load(url) {
    const key = String(url)
    if (cache.has(key)) return cache.get(key)
    const exports = {}
    cache.set(key, exports)
    const compiled = ts.transpileModule(readFileSync(url, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    const require = (name) => {
      if (name in overrides) return overrides[name]
      if (!name.startsWith('@/') && !name.startsWith('.')) return nativeRequire(name)
      const base = name.startsWith('@/') ? new URL(name.slice(2), sourceRoot) : new URL(name, url)
      const target = ['.ts', '.tsx'].map((extension) => new URL(`${base}${extension}`)).find((candidate) => existsSync(candidate))
      assert.ok(target, `找不到源码模块 ${name}`)
      return load(target)
    }
    vm.runInNewContext(compiled, { exports, require, window: overrides.window, setTimeout, clearTimeout, AbortController })
    return exports
  }
  return load(new URL(path, sourceRoot))
}

function deferred() {
  let resolve
  const promise = new Promise((accept) => { resolve = accept })
  return { promise, resolve }
}

function camera(key, department = 'general_electric') {
  return { id: key, camera_id: Number(key.split('_')[1]), shm_name: key, name: key, department,
    functions: { tailgating: true }, feature_sort_orders: { tailgating: 0 } }
}

function harness(apiChanges = {}, optionsChanges = {}) {
  const slots = []
  let cursor = 0
  let dirty = false
  let value
  let effects = []
  let updates = 0
  const same = (a, b) => a && a.length === b.length && a.every((item, index) => Object.is(item, b[index]))
  const react = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial
      return [slots[index], (next) => {
        const result = typeof next === 'function' ? next(slots[index]) : next
        if (!Object.is(result, slots[index])) { slots[index] = result; dirty = true; updates += 1 }
      }]
    },
    useRef(initial) {
      const index = cursor++
      return slots[index] ??= { current: initial }
    },
    useCallback(callback, dependencies) {
      const index = cursor++
      if (!same(slots[index]?.dependencies, dependencies)) slots[index] = { callback, dependencies }
      return slots[index].callback
    },
    useEffect(callback, dependencies) {
      const index = cursor++
      const previous = slots[index]
      if (same(previous?.dependencies, dependencies)) return
      slots[index] = { dependencies }
      effects.push(() => { previous?.cleanup?.(); slots[index].cleanup = callback() })
    },
  }
  const window = new EventTarget()
  const reads = []
  const saves = []
  const api = {
    getAiVisionCameras: async () => [camera('camera_1'), camera('camera_2')],
    getAiVisionFeatureConfig: async (feature, key) => { reads.push(key); return { config: { enable: true, value: { key } } } },
    saveAiVisionFeatureConfig: async (feature, key, payload) => { saves.push({ key, payload }); window.dispatchEvent(new Event('aivision:cameras-changed')) },
    ...apiChanges,
  }
  const { useCameraFeatureConfig } = loadSource('components/detection/useCameraFeatureConfig.ts', {
    react, window, '@/lib/aivision': api,
  })
  let options = { feature: 'tailgating', department: 'general_electric', isAdmin: true,
    createDraft: (config) => ({ config }), buildConfig: (draft) => draft.config, ...optionsChanges }
  function render(changes = {}) {
    options = { ...options, ...changes }
    cursor = 0
    dirty = false
    effects = []
    value = useCameraFeatureConfig(options)
    effects.forEach((run) => run())
    return value
  }
  async function settle() {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise(setImmediate)
      if (!dirty) return value
      render()
    }
    throw new Error('配置 Hook 未稳定')
  }
  render()
  return { render, settle, window, reads, saves, get value() { return value }, get updates() { return updates },
    dispose: () => slots.forEach((slot) => slot?.cleanup?.()) }
}

test('切换摄像头后，迟到的旧配置不能覆盖当前草稿', async () => {
  const first = deferred()
  const second = deferred()
  const app = harness({ getAiVisionFeatureConfig: async (feature, key) => key === 'camera_1' ? first.promise : second.promise })
  await app.settle()
  app.value.selectCamera('camera_2')
  second.resolve({ config: { enable: true, value: { key: 'camera_2' } } })
  await app.settle()
  first.resolve({ config: { enable: true, value: { key: 'camera_1' } } })
  await app.settle()
  assert.equal(app.value.cameraKey, 'camera_2')
  assert.equal(app.value.draft.config.value.key, 'camera_2')
  app.dispose()
})

test('部门切换后，旧部门的列表与响应不能串入新部门', async () => {
  const oldList = deferred()
  const app = harness({ getAiVisionCameras: async (department) => department === 'general_electric'
    ? oldList.promise : [camera('camera_3', department)] })
  app.render({ department: 'electronics_electrician' })
  await app.settle()
  oldList.resolve([camera('camera_1')])
  await app.settle()
  assert.equal(app.value.cameraKey, 'camera_3')
  assert.deepEqual(Array.from(app.value.enabledCameras, (item) => item.department), ['electronics_electrician'])
  app.dispose()
})

test('保存期间忽略自身广播，保存后回读当前摄像头且不丢失草稿', async () => {
  const app = harness()
  await app.settle()
  app.value.update((draft) => ({ config: { ...draft.config, value: { key: 'edited' } } }))
  app.render()
  await app.value.save()
  await app.settle()
  assert.equal(app.saves.length, 1)
  assert.equal(app.saves[0].key, 'camera_1')
  assert.equal(app.saves[0].payload.value.key, 'edited')
  assert.deepEqual(app.reads, ['camera_1', 'camera_1'])
  assert.equal(app.value.draft.config.value.key, 'camera_1')
  app.dispose()
})

test('普通用户可以读取配置，但不能编辑或保存', async () => {
  const app = harness({}, { isAdmin: false })
  await app.settle()
  app.value.update(() => ({ config: { enable: false, value: {} } }))
  await app.value.save()
  await app.settle()
  assert.equal(app.saves.length, 0)
  assert.equal(app.value.draft.config.enable, true)
  app.dispose()
})

test('卸载后迟到的配置请求不再更新页面状态', async () => {
  const pending = deferred()
  const app = harness({ getAiVisionFeatureConfig: async () => pending.promise })
  await app.settle()
  app.dispose()
  const before = app.updates
  pending.resolve({ config: { enable: true, value: {} } })
  await new Promise(setImmediate)
  assert.equal(app.updates, before)
})

test('通行参数与归一化 ROI、计数线校验拒绝非法值', () => {
  const { createTailgatingDraft, buildTailgatingConfig } = loadSource('components/tailgating/config.ts')
  const config = { enable: true, value: { roi_pos: [], line_points: [], direction: 1, overlap_seconds: 0.3,
    crossing_window_seconds: 3, max_frame_gap_seconds: 1, cap_interval: 0.1, threshold: 0.5, foot_ratio: 0.93, alarm_interval: 30 }, alarm: {} }
  const draft = createTailgatingDraft(config)
  assert.equal(buildTailgatingConfig(draft).value.overlap_seconds, 0.3)
  for (const invalid of ['', 'NaN', '-1', 'Infinity']) {
    assert.throws(() => buildTailgatingConfig({ ...draft, numbers: { ...draft.numbers, overlap_seconds: invalid } }), /超出有效范围/)
  }
  assert.throws(() => buildTailgatingConfig({ ...draft, line: '[[0.5,0.5],[0.5,0.5]]' }), /不同的端点/)
  assert.throws(() => buildTailgatingConfig({ ...draft, roi: '[[0,0],[1,1]]' }), /至少需要三个顶点/)
})

test('监控异常和等待状态不会展示为未发现尾随，报警显示人员与共同出现时长', () => {
  const { createElement } = nativeRequire('react')
  const { renderToStaticMarkup } = nativeRequire('react-dom/server')
  for (const state of ['waiting', 'stale', 'error', 'ready']) {
    const status = { state, reason: state, count: state === 'ready' ? 2 : null, alarm: state === 'ready',
      events: state === 'ready' ? [{ id: 'event-1', track_ids: [1, 2], overlap_seconds: 0.4, direction: 1 }] : [],
      sample_interval_seconds: 0.2, updated_at: null, error: state === 'error' ? '模型不可用' : null }
    const { TailgatingMonitorView } = loadSource('components/tailgating/TailgatingMonitorView.tsx', {
      './useTailgatingStatus': { useTailgatingStatus: () => ({ value: status }) },
      '@/components/monitor/ResizableMonitorLayout': { ResizableMonitorLayout: ({ children }) => createElement('div', null, children) },
    })
    const html = renderToStaticMarkup(createElement(TailgatingMonitorView, {
      department: 'general_electric', cameras: [camera('camera_1')], selectedCamera: 'camera_1', loading: false,
      message: '实时画面已连接', frameConnected: true, frameContent: createElement('img', { src: '/frame.jpg' }),
      onSelectCamera: () => {}, onRefreshCameras: () => {},
    }))
    assert.ok(!html.includes('未发现尾随'))
    if (state === 'ready') assert.match(html, /0\.40 秒/)
    else assert.match(html, /等待有效结果/)
  }
})

test('围栏复用配置 Hook 后保留独立参数校验与白名单', () => {
  const { useFenceConfig } = loadSource('components/security_fence/useFenceConfig.ts', {
    '@/components/detection/useCameraFeatureConfig': { useCameraFeatureConfig: (options) => options },
    '@/lib/api': { apiGet: () => assert.fail('参数校验不应发请求') },
  })
  const options = useFenceConfig('general_electric', true)
  const config = { enable: true, value: {
    roi_pos: [], allowed_person_ids: [123], forbidden_start: '22:00', forbidden_end: '08:00', timezone: 'Asia/Shanghai',
    threshold: 0.5, detection_threshold: 0.7, similarity_threshold: 0.5, unknown_similarity_threshold: 0.3,
    confirmation_frames: 3, min_face_size: 80, min_face_sharpness: 60, max_face_asymmetry: 0.35,
    cap_interval: 0.2, tracking_overlap_threshold: 0.2, tracking_gap_seconds: 2, alarm_interval: 30,
  }, alarm: {} }
  const draft = options.createDraft(config)
  assert.equal(options.feature, 'security_fence')
  assert.deepEqual(Array.from(options.buildConfig(draft).value.allowed_person_ids), [123])
  assert.throws(() => options.buildConfig({ ...draft, numbers: { ...draft.numbers, confirmation_frames: '2.5' } }), /超出有效范围/)
  assert.throws(() => options.buildConfig({ ...draft, numbers: { ...draft.numbers, unknown_similarity_threshold: '0.8' } }), /必须小于/)
})
