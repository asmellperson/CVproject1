import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const root = new URL('../src/components/logistics_single_person/', import.meta.url)
const feature = 'detect_logistics_single_person'
function harness() {
  let cursor = 0, dirty = true, tree, render, effects = []
  const slots = []
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]))
  const hooks = {
    ...React,
    useState(initial) {
      const i = cursor++
      slots[i] ??= { value: typeof initial === 'function' ? initial() : initial }
      return [slots[i].value, (value) => {
        const next = typeof value === 'function' ? value(slots[i].value) : value
        if (!Object.is(slots[i].value, next)) { slots[i].value = next; dirty = true }
      }]
    },
    useReducer(reducer, initial) {
      const [value, setValue] = hooks.useState(initial)
      return [value, (action) => setValue((prev) => reducer(prev, action))]
    },
    useRef(initial) { return slots[cursor++] ??= { current: initial } },
    useMemo(factory, deps) {
      const i = cursor++
      if (!same(slots[i]?.deps, deps)) slots[i] = { value: factory(), deps }
      return slots[i].value
    },
    useEffect(effect, deps) {
      const i = cursor++
      if (!same(slots[i]?.deps, deps)) {
        slots[i]?.cleanup?.(); slots[i] = { deps }
        effects.push(() => { slots[i].cleanup = effect() })
      }
    },
  }
  return {
    hooks,
    async mount(fn) { render = fn; return this.flush() },
    async flush() {
      for (let i = 0; i < 60; i++) {
        if (dirty) { dirty = false; cursor = 0; effects = []; tree = render(); effects.forEach((fn) => fn()) }
        await Promise.resolve()
      }
      return tree
    },
  }
}
function find(node, predicate) {
  if (!node || typeof node !== 'object') return []
  if (Array.isArray(node)) return node.flatMap((child) => find(child, predicate))
  return [...(predicate(node) ? [node] : []), ...find(node.props?.children, predicate)]
}
async function mount(isAdmin = true) {
  const h = harness(), writes = []
  const camera = { id: '1', camera_id: 1, name: 'camera', shm_name: 'camera', department: 'general_electric', enable: true }
  let config = { enable: true, value: { IOU_THR: .67, MIN_BOX_AREA: 11, ASPECT_RATIO_RANGE: [.2, 3.7], cap_interval: .45, roi_pos: [] } }
  const response = () => ({ camera, feature, config: structuredClone(config) })
  const detail = { id: 1, name: 'channel', feature_name: feature, department: 'general_electric', enabled: true, sort_order: 0,
    config: { detection_start: '08:00:00', detection_end: '20:00:00', confidence_threshold: .4, empty_grace_seconds: 2, multi_grace_seconds: 1, alarm_interval: 5,
      alarm: { sql_enable: false, horn: { enabled: false, horn_id: null, horn_event_id: null }, wechat: { enabled: false, user: '' } } },
    members: [{ id: 1, camera_id: 1, channel_id: 1, enabled: true, sort_order: 0 }] }
  const api = {
    getLogisticsChannel: async () => detail,
    getLogisticsCameraConfig: async () => response(),
    updateLogisticsCameraConfig: async (_feature, channel, id, payload) => {
      assert.equal(_feature, feature); assert.equal(channel, 1); assert.equal(id, 1)
      writes.push(structuredClone(payload)); config = structuredClone(payload)
      config.value.MIN_BOX_AREA = 22 // Verify that the server response is echoed.
      return response()
    },
  }
  const stub = new Proxy({}, { get: (_, key) => key }), modules = new Map()
  function load(path) {
    if (modules.has(path)) return modules.get(path)
    const output = ts.transpileModule(readFileSync(new URL(path, root), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    const module = { exports: {} }
    Function('require', 'exports', 'module', output)((key) => {
      if (key === 'react') return h.hooks
      if (key === './api') return api
      if (key === '@/lib/aivision') return { getAiVisionCameras: async () => [camera] }
      if (key === '@/hooks/use-department-catalog') return { useDepartmentCatalog: () => ({ labels: {}, options: [] }) }
      if (key === '@/components/AiVisionRoiEditor.geometry') return { parseNormalizedRoi: JSON.parse }
      if (key === '@/lib/horn-alarm-binding') return { validateHornBinding: () => null }
      if (key === './alarmBinding') return { toFeatureAlarm: (value) => value, toLogisticsAlarm: (value) => value }
      if (key.startsWith('./') && (!key.includes('Dialog') || key.endsWith('State'))) return load(`${key.slice(2)}.ts`)
      if (key.startsWith('@/') || key.startsWith('./') || key === 'lucide-react') return stub
      return require(key)
    }, module.exports, module)
    modules.set(path, module.exports); return module.exports
  }
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  const Component = load('LogisticsChannelConfigView.tsx').LogisticsChannelConfigView
  await h.mount(() => Component({ feature, department: 'general_electric', channels: [detail], selectedChannelId: 1,
    selectedChannelDetail: detail, isAdmin, onChanged() {} }))
  return {
    writes,
    async input(id, value) {
      const element = find(await h.flush(), (node) => node.props?.id === id)[0]
      assert.ok(element, `missing ${id}`)
      if (value !== undefined) { element.props.onChange(value); await h.flush() }
      return element.props
    },
    async save() {
      const bar = find(await h.flush(), (node) => node.props?.saveLabel === '保存摄像头配置')[0]
      assert.ok(bar); bar.props.onSave(); await h.flush()
    },
  }
}

test('reads backend camera values and saves only camera parameters, including zero IOU', async () => {
  const page = await mount()
  assert.equal((await page.input('logistics-camera-iou')).value, '0.67')
  assert.equal((await page.input('logistics-camera-area')).value, '11')
  await page.input('logistics-camera-iou', '0'); await page.input('logistics-camera-area', '0')
  await page.input('logistics-camera-interval', '0.001'); await page.save()
  assert.equal(page.writes.length, 1)
  assert.deepEqual(Object.keys(page.writes[0]).sort(), ['enable', 'value'])
  assert.deepEqual(Object.keys(page.writes[0].value).sort(), ['ASPECT_RATIO_RANGE', 'IOU_THR', 'MIN_BOX_AREA', 'cap_interval', 'roi_pos'])
  assert.equal(page.writes[0].value.IOU_THR, 0); assert.equal(page.writes[0].value.MIN_BOX_AREA, 0)
  assert.equal(page.writes[0].value.cap_interval, .001)
  assert.equal((await page.input('logistics-camera-area')).value, '22')
})

test('blocks invalid camera geometry and intervals before sending a request', async () => {
  for (const [id, value] of [['logistics-camera-iou', '1.1'], ['logistics-camera-area', '1.5'],
    ['logistics-camera-min-aspect', '4'], ['logistics-camera-interval', '0']]) {
    const page = await mount(); await page.input(id, value); await page.save()
    assert.equal(page.writes.length, 0)
  }
})

test('viewer cannot save camera config through the handler', async () => {
  const page = await mount(false)
  assert.equal((await page.input('logistics-camera-iou')).disabled, true)
  await page.save(); assert.equal(page.writes.length, 0)
})
