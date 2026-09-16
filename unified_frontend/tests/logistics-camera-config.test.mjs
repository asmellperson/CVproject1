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
  const h = harness(), channelWrites = [], roiWrites = []
  const cameras = [1, 2].map((id) => ({ id: String(id), camera_id: id, name: `camera ${id}`, shm_name: `camera_${id}`,
    department: 'general_electric', enabled: true, sort_order: id, functions: {} }))
  const rois = new Map([[1, []], [2, [[0, 0], [1, 0], [1, 1]]]])
  const response = (id) => ({ camera: { id, name: `camera ${id}`, shm_name: `camera_${id}`, enable: true }, roi_pos: structuredClone(rois.get(id)) })
  const detail = { id: 1, name: 'channel', feature_name: feature, department: 'general_electric', enabled: true, sort_order: 0,
    config: { detection_start: '08:00:00', detection_end: '20:00:00', confidence_threshold: .4,
      model_iou_threshold: .67, min_box_area: 11, min_aspect_ratio: .2, max_aspect_ratio: 3.7, cap_interval: .45,
      empty_grace_seconds: 2, multi_grace_seconds: 1, alarm_interval: 5,
      alarm: { sql_enable: false, horn: { enabled: false, horn_id: null, horn_event_id: null }, wechat: { enabled: false, user: '' } } },
    members: cameras.map((camera) => ({ id: camera.camera_id, camera_id: camera.camera_id, channel_id: 1, enabled: true, sort_order: camera.camera_id })) }
  const api = {
    getLogisticsChannel: async () => detail,
    getLogisticsCameraRoi: async (_feature, _channel, id) => response(id),
    updateLogisticsChannel: async (_feature, channel, payload) => {
      assert.equal(_feature, feature); assert.equal(channel, 1)
      channelWrites.push(structuredClone(payload)); Object.assign(detail, structuredClone(payload))
      detail.config.min_box_area = 22
      return structuredClone(detail)
    },
    updateLogisticsCameraRoi: async (_feature, channel, id, payload) => {
      assert.equal(_feature, feature); assert.equal(channel, 1)
      roiWrites.push({ id, payload: structuredClone(payload) }); rois.set(id, structuredClone(payload.roi_pos))
      return response(id)
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
      if (key === '@/lib/aivision') return { getAiVisionCameras: async () => cameras }
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
  const editor = async () => find(await h.flush(), (node) => node.type === 'AiVisionRoiEditor')[0].props
  return {
    channelWrites, roiWrites, rois,
    async tab(value) { return find(await h.flush(), (node) => node.type === 'TabsContent' && node.props.value === value)[0] },
    async input(id, value) {
      const element = find(await h.flush(), (node) => node.props?.id === id)[0]
      assert.ok(element, `missing ${id}`)
      if (value !== undefined) { element.props.onChange(value); await h.flush() }
      return element.props
    },
    async save() {
      const bar = find(await h.flush(), (node) => node.props?.saveLabel === '保存检测参数')[0]
      assert.ok(bar); bar.props.onSave(); await h.flush()
    },
    async roi(value) {
      if (value) { (await editor()).onChange(JSON.stringify(value)); await h.flush() }
      return JSON.parse((await editor()).roiJson)
    },
    async saveRoi() { (await editor()).onSave(); await h.flush() },
    async selectCamera(id) {
      const roiTab = await this.tab('roi')
      find(roiTab, (node) => node.type === 'Select')[0].props.onValueChange(String(id))
      await h.flush()
    },
  }
}

test('channel parameters save once and never write camera ROI or lifecycle state', async () => {
  const page = await mount()
  assert.equal((await page.input('logistics-channel-iou')).value, '0.67')
  assert.equal((await page.input('logistics-channel-area')).value, '11')
  assert.equal(find(await page.tab('params'), (node) => node.type === 'Select').length, 0)
  await page.input('logistics-channel-iou', '0'); await page.input('logistics-channel-area', '0')
  await page.input('logistics-channel-interval', '0.001'); await page.save()
  assert.equal(page.channelWrites.length, 1)
  assert.equal(page.roiWrites.length, 0)
  const { config } = page.channelWrites[0]
  assert.equal(config.model_iou_threshold, 0); assert.equal(config.min_box_area, 0)
  assert.equal(config.cap_interval, .001)
  assert.equal(config.min_aspect_ratio, .2); assert.equal(config.max_aspect_ratio, 3.7)
  for (const field of ['roi_pos', 'enable', 'IOU_THR', 'MIN_BOX_AREA', 'ASPECT_RATIO_RANGE']) assert.equal(field in config, false)
  assert.equal((await page.input('logistics-channel-area')).value, '22')
})

test('ROI saves only geometry and cameras keep independent ROIs', async () => {
  const page = await mount()
  const roi = [[.1, .1], [.8, .1], [.8, .8]]
  const second = structuredClone(page.rois.get(2))
  await page.roi(roi); await page.saveRoi()
  assert.deepEqual(page.roiWrites, [{ id: 1, payload: { roi_pos: roi } }])
  assert.equal(page.channelWrites.length, 0)
  assert.equal(find(await page.tab('roi'), (node) => node.props?.id?.startsWith('logistics-channel-')).length, 0)
  await page.selectCamera(2); assert.deepEqual(await page.roi(), second)
  await page.selectCamera(1); assert.deepEqual(await page.roi(), roi)
})

test('blocks invalid channel geometry and intervals before sending a request', async () => {
  for (const [id, value] of [['logistics-channel-iou', '1.1'], ['logistics-channel-area', '1.5'],
    ['logistics-channel-min-aspect', '4'], ['logistics-channel-interval', '0']]) {
    const page = await mount(); await page.input(id, value); await page.save()
    assert.equal(page.channelWrites.length, 0)
  }
})

test('viewer cannot save channel policy or ROI through either handler', async () => {
  const page = await mount(false)
  assert.equal((await page.input('logistics-channel-iou')).disabled, true)
  await page.save(); await page.saveRoi()
  assert.equal(page.channelWrites.length, 0); assert.equal(page.roiWrites.length, 0)
})
