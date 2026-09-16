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
    invalidate() { dirty = true },
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
  const other = structuredClone(detail)
  other.id = 2; other.name = 'second channel'; other.members = []
  other.config.model_iou_threshold = .31
  other.config.alarm.wechat = { enabled: true, user: 'second-user' }
  const storedChannels = new Map([[1, detail], [2, other]])
  let selectedChannelId = 1, selectedChannelDetail = structuredClone(detail), saveGate = null
  const refreshDetail = () => {
    selectedChannelDetail = structuredClone(storedChannels.get(selectedChannelId))
    h.invalidate()
  }
  const api = {
    getLogisticsChannel: async (_feature, channel) => structuredClone(storedChannels.get(channel)),
    getLogisticsCameraRoi: async (_feature, _channel, id) => response(id),
    updateLogisticsChannel: async (_feature, channel, payload) => {
      assert.equal(_feature, feature)
      channelWrites.push(structuredClone(payload))
      if (saveGate) { const gate = saveGate; saveGate = null; await gate }
      const previous = storedChannels.get(channel)
      const saved = { ...previous, ...structuredClone(payload), config: { ...previous.config, ...structuredClone(payload.config) } }
      if (payload.config && 'min_box_area' in payload.config) saved.config.min_box_area = 22
      if (payload.config?.alarm) saved.config.alarm.wechat.user = saved.config.alarm.wechat.user.trim()
      storedChannels.set(channel, saved)
      return structuredClone(saved)
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
      if (key === '@/lib/horn-alarm-binding') return load('../../lib/horn-alarm-binding.ts')
      if (key === '@/lib/alarm-config') return load('../../lib/alarm-config.ts')
      if (key.startsWith('./') && (!key.includes('Dialog') || key.endsWith('State'))) return load(`${key.slice(2)}.ts`)
      if (key.startsWith('@/') || key.startsWith('./') || key === 'lucide-react') return stub
      return require(key)
    }, module.exports, module)
    modules.set(path, module.exports); return module.exports
  }
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  const Component = load('LogisticsChannelConfigView.tsx').LogisticsChannelConfigView
  const { toFeatureAlarm, toLogisticsAlarm } = load('alarmBinding.ts')
  await h.mount(() => Component({ feature, department: 'general_electric', channels: [...storedChannels.values()], selectedChannelId,
    selectedChannelDetail, isAdmin, onChanged: refreshDetail }))
  const editor = async () => find(await h.flush(), (node) => node.type === 'AiVisionRoiEditor')[0].props
  const alarmEditor = async () => find(await h.flush(), (node) => node.type === 'AlarmPushConfig')[0].props
  return {
    channelWrites, roiWrites, rois,
    stored(id = selectedChannelId) { return structuredClone(storedChannels.get(id)) },
    async refresh() { refreshDetail(); await h.flush() },
    async selectChannel(id) { selectedChannelId = id; refreshDetail(); await h.flush() },
    holdNextSave() {
      let release
      saveGate = new Promise((resolve) => { release = resolve })
      return async () => { release(); await h.flush() }
    },
    async tab(value) { return find(await h.flush(), (node) => node.type === 'TabsContent' && node.props.value === value)[0] },
    async input(id, value) {
      const element = find(await h.flush(), (node) => node.props?.id === id)[0]
      assert.ok(element, `missing ${id}`)
      if (value !== undefined) {
        element.props.onChange(element.type === 'Input' ? { target: { value } } : value)
        await h.flush()
      }
      return element.props
    },
    async save() {
      const bar = find(await h.flush(), (node) => node.props?.saveLabel === '保存检测参数')[0]
      assert.ok(bar); bar.props.onSave(); await h.flush()
    },
    async alarm(value) {
      if (value) { (await alarmEditor()).onChange(toFeatureAlarm(value)); await h.flush() }
      return toLogisticsAlarm((await alarmEditor()).alarm)
    },
    async saveAlarm() { (await alarmEditor()).onSave(); await h.flush() },
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
  assert.deepEqual(Object.keys(config).sort(), [
    'detection_start', 'detection_end', 'confidence_threshold', 'model_iou_threshold', 'min_box_area',
    'min_aspect_ratio', 'max_aspect_ratio', 'cap_interval', 'empty_grace_seconds', 'multi_grace_seconds', 'alarm_interval',
  ].sort())
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

test('blocks invalid detection fields and channel names before sending a request', async () => {
  for (const [id, value] of [['logistics-channel-iou', '1.1'], ['logistics-channel-area', '1.5'],
    ['logistics-channel-min-aspect', '4'], ['logistics-channel-interval', '0'],
    ['logistics-detection-start', '21:00'], ['logistics-detection-end', '08:00'], ['logistics-detection-start', ''],
    ['logistics-confidence-threshold', '-0.1'], ['logistics-confidence-threshold', 'NaN'],
    ['logistics-empty-grace', '-1'], ['logistics-multi-grace', '-1'], ['logistics-alarm-interval', '0'],
    ['logistics-channel-name', '  '], ['logistics-channel-name', 'x'.repeat(101)]]) {
    const page = await mount(); await page.input(id, value); await page.save()
    assert.equal(page.channelWrites.length, 0)
  }
})

test('viewer cannot save detection policy, alarms or ROI through the handlers', async () => {
  const page = await mount(false)
  assert.equal((await page.input('logistics-channel-iou')).disabled, true)
  await page.save(); await page.saveAlarm(); await page.saveRoi()
  assert.equal(page.channelWrites.length, 0); assert.equal(page.roiWrites.length, 0)
})

test('saving alarms preserves unsaved detection fields and name across the server refresh', async () => {
  const page = await mount()
  const before = page.stored()
  await page.input('logistics-channel-iou', '0.5')
  await page.input('logistics-channel-name', 'unsaved name')
  const alarm = { ...await page.alarm(), wechat: { enabled: true, user: '  alarm-user  ' } }
  await page.alarm(alarm)
  await page.saveAlarm()
  assert.deepEqual(page.channelWrites, [{ config: { alarm } }])
  assert.equal(page.stored().config.model_iou_threshold, before.config.model_iou_threshold)
  assert.equal(page.stored().name, before.name)
  assert.equal((await page.input('logistics-channel-iou')).value, '0.5')
  assert.equal((await page.input('logistics-channel-name')).value, 'unsaved name')
  assert.equal((await page.alarm()).wechat.user, 'alarm-user')
  await page.refresh()
  assert.equal((await page.input('logistics-channel-iou')).value, '0.5')
  await page.save()
  assert.equal(page.stored().config.model_iou_threshold, .5)
  assert.equal(page.stored().name, 'unsaved name')
  assert.equal(page.stored().config.alarm.wechat.user, 'alarm-user')
})

test('saving detection fields preserves the alarm draft without submitting it', async () => {
  const page = await mount()
  const savedAlarm = page.stored().config.alarm
  const alarm = { ...await page.alarm(), sql_enable: true, wechat: { enabled: true, user: 'pending-user' } }
  await page.alarm(alarm)
  await page.input('logistics-detection-start', '09:30')
  await page.input('logistics-channel-iou', '0.5')
  await page.input('logistics-alarm-interval', '12')
  await page.save()
  assert.equal('alarm' in page.channelWrites[0].config, false)
  assert.equal(page.channelWrites[0].config.detection_start, '09:30:00')
  assert.equal(page.stored().config.alarm_interval, 12)
  assert.deepEqual(page.stored().config.alarm, savedAlarm)
  assert.deepEqual(await page.alarm(), alarm)
  await page.refresh()
  assert.deepEqual(await page.alarm(), alarm)
  await page.saveAlarm()
  assert.deepEqual(page.stored().config.alarm, alarm)
  assert.equal(page.stored().config.alarm_interval, 12)
})

test('unsaved invalid horn binding blocks only alarm saving', async () => {
  const page = await mount()
  const before = page.stored().config.alarm
  const alarm = { ...await page.alarm(), horn: { enabled: true, horn_id: null, horn_event_id: null } }
  await page.alarm(alarm)
  await page.saveAlarm()
  assert.equal(page.channelWrites.length, 0)
  await page.save()
  assert.equal(page.channelWrites.length, 1)
  assert.equal('alarm' in page.channelWrites[0].config, false)
  assert.deepEqual(page.stored().config.alarm, before)
  assert.deepEqual(await page.alarm(), alarm)
})

test('unsaved invalid detection fields and name do not block alarm saving', async () => {
  const page = await mount()
  const before = page.stored()
  await page.input('logistics-detection-start', '21:00')
  await page.input('logistics-channel-iou', '2')
  await page.input('logistics-channel-name', '')
  const alarm = { ...await page.alarm(), sql_enable: true }
  await page.alarm(alarm)
  await page.save()
  assert.equal(page.channelWrites.length, 0)
  await page.saveAlarm()
  assert.deepEqual(page.channelWrites, [{ config: { alarm } }])
  assert.equal(page.stored().name, before.name)
  assert.deepEqual(page.stored().config, { ...before.config, alarm })
  assert.equal((await page.input('logistics-detection-start')).value, '21:00')
  assert.equal((await page.input('logistics-channel-iou')).value, '2')
  assert.equal((await page.input('logistics-channel-name')).value, '')
})

test('switching channels initializes both drafts and the name from the selected channel', async () => {
  const page = await mount()
  await page.input('logistics-channel-iou', '0.5')
  await page.input('logistics-channel-name', 'unsaved name')
  await page.alarm({ ...await page.alarm(), sql_enable: true })
  await page.selectChannel(2)
  assert.equal((await page.input('logistics-channel-iou')).value, '0.31')
  assert.equal((await page.input('logistics-channel-name')).value, 'second channel')
  assert.deepEqual(await page.alarm(), page.stored().config.alarm)
  await page.selectChannel(1)
  assert.equal((await page.input('logistics-channel-iou')).value, '0.67')
  assert.equal((await page.input('logistics-channel-name')).value, 'channel')
  assert.deepEqual(await page.alarm(), page.stored().config.alarm)
})

test('late saves cannot overwrite drafts after switching away and back to the same channel', async () => {
  for (const tab of ['detection', 'alarm']) {
    const page = await mount()
    const initial = page.stored()
    await page.input('logistics-channel-iou', '0.5')
    await page.alarm({ ...await page.alarm(), sql_enable: true })
    const release = page.holdNextSave()
    if (tab === 'detection') await page.save()
    else await page.saveAlarm()
    await page.selectChannel(2)
    await page.selectChannel(1)
    await release()
    assert.equal((await page.input('logistics-channel-iou')).value, String(initial.config.model_iou_threshold))
    assert.deepEqual(await page.alarm(), initial.config.alarm)
    if (tab === 'detection') assert.equal(page.stored().config.model_iou_threshold, .5)
    else assert.equal(page.stored().config.alarm.sql_enable, true)
  }
})
