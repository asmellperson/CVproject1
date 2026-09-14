import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const root = new URL('../', import.meta.url)

// Exercise actual component callbacks with the same lightweight hook harness used by recognition tests.
function harness() {
  const slots = []
  let cursor = 0, dirty = true, render, tree, effects = []
  const hooks = {
    ...React,
    lazy: () => () => null,
    useState(initial) {
      const index = cursor++
      slots[index] ??= { value: initial }
      return [slots[index].value, (value) => {
        slots[index].value = typeof value === 'function' ? value(slots[index].value) : value
        dirty = true
      }]
    },
    useRef(initial) { return slots[cursor++] ??= { current: initial } },
    useEffect(fn, deps) {
      const index = cursor++
      if (!slots[index] || deps.some((dep, i) => dep !== slots[index].deps[i])) {
        slots[index] = { deps }
        effects.push(fn)
      }
    },
  }
  return {
    hooks,
    async mount(fn) { render = fn; return this.flush() },
    async flush() {
      for (let i = 0; i < 40; i++) {
        if (dirty) {
          dirty = false; cursor = 0; effects = []; tree = render()
          effects.forEach((fn) => fn())
        }
        await Promise.resolve()
      }
      return tree
    },
  }
}

function elements(node, predicate) {
  if (!node || typeof node !== 'object') return []
  if (Array.isArray(node)) return node.flatMap((child) => elements(child, predicate))
  return [...(predicate(node) ? [node] : []), ...elements(node.props?.children, predicate)]
}

const alarm = {
  sql: { enable: false, parm: {} },
  horn: { enable: false, parm: { horn_id: null, horn_event_id: null } },
  wechat: { enable: false, parm: { user: '' } },
}
const common = { roi_pos: [], cap_interval: .2, alarm_interval: 7 }
const configs = {
  Face: { ...common, FACE_SCORE_THR: .65, MAX_TIME: 12, MAX_LOST: 2, DETECTION_IOU_THR: .21, TRACK_IOU_THR: .79 },
  Human: { ...common, CONF_THRESHOLD: .4, MAX_TIME: 12, MAX_LOST: 2, DETECTION_IOU_THR: .21, TRACK_IOU_THR: .79,
    MIN_BOX_AREA: 0, ASPECT_RATIO_RANGE: [0, 10], CENTER_DIST_THR: .65, AREA_RATIO_THR: .55,
    MATCH_SCORE_THR: .35, TRACK_SMOOTH_ALPHA: .7 },
  Door: { ...common, threshold: .5, env_threshold: null, first_alarm: 61, stable_confirm_seconds: 1,
    stable_confirm_hits: 3, background_update_alpha: .05, global_motion_threshold: .22,
    min_local_change_ratio: .01, diff_threshold: 5, diff_threshold_env: 10 },
  Phone: { ...common, CONF_THRESHOLD: .7, IOU_THR: .5, PERSON_CONF_THRESHOLD: .3,
    MIN_CONFIRM_SECONDS: 1.2, MIN_CONSECUTIVE_HITS: 3, REQUIRE_PERSON_ASSOCIATION: true, PERSON_EXPAND_RATIO: .18 },
}

async function mount(name, feature = `detect_${name.toLowerCase()}`) {
  const h = harness()
  const writes = []
  let config = { enable: true, value: structuredClone(configs[name]), alarm: structuredClone(alarm) }
  const response = () => ({ camera: { id: 1, name: '测试摄像头', shm_name: 'test', enable: true }, feature, config })
  const api = {
    getAiVisionCameras: async () => [{ id: '1', name: '测试摄像头', shm_name: 'test', functions: { [feature]: true } }],
    isAiVisionFeatureEnabled: (camera, key) => Boolean(camera.functions[key]),
    getAiVisionFeatureConfig: async () => response(),
    saveAiVisionFeatureConfig: async (_feature, _key, next) => {
      assert.equal(_feature, feature)
      writes.push(structuredClone(next)); config = next; return response()
    },
  }
  const stub = new Proxy({}, { get: (_target, key) => `mock-${String(key)}` })
  const imports = {
    react: h.hooks,
    '@/auth/useAuth': { useAuth: () => ({ isAdmin: true }) },
    '@/lib/aivision': api,
    '@/lib/alarm-config': { normalizeFeatureAlarmConfig: (value) => value },
    '@/components/AiVisionRoiEditor.geometry': { parseNormalizedRoi: JSON.parse },
  }
  const source = await readFile(new URL(`src/sections/${name}DetectionSection.tsx`, root), 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const module = { exports: {} }
  Function('require', 'exports', 'module', output)(
    (key) => imports[key] ?? (key.startsWith('@/') || key === 'lucide-react' ? stub : require(key)), module.exports, module)
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  const component = module.exports[`${name}DetectionSection`]
  await h.mount(() => component({ feature }))
  return {
    writes,
    async input(id, value) {
      const tree = await h.flush()
      const input = elements(tree, (node) => node.props?.id === id)[0]
      assert.ok(input, `missing input ${id}`)
      if (value !== undefined) { input.props.onChange({ target: { value } }); await h.flush() }
      return input.props
    },
    async save() {
      const tree = await h.flush()
      const bar = elements(tree, (node) => typeof node.props?.onSave === 'function')[0]
      await bar.props.onSave(); await h.flush()
    },
  }
}

test('face reads backend values, edits zero seconds/counts and independently saves/re-echoes both IOUs', async () => {
  const page = await mount('Face')
  assert.equal((await page.input('face-max-time')).value, '12')
  assert.equal((await page.input('face-max-lost')).step, '1')
  assert.equal((await page.input('face-cap-interval')).value, '0.2')
  await page.input('face-cap-interval', '0.5')
  await page.input('face-score', '0')
  await page.input('face-max-time', '0'); await page.input('face-max-lost', '0')
  await page.input('face-detection-iou', '0'); await page.input('face-track-iou', '1')
  await page.save()
  assert.equal(page.writes.length, 1)
  assert.equal(page.writes[0].value.MAX_TIME, 0)
  assert.equal(page.writes[0].value.MAX_LOST, 0)
  assert.equal(page.writes[0].value.DETECTION_IOU_THR, 0)
  assert.equal(page.writes[0].value.TRACK_IOU_THR, 1)
  assert.equal(page.writes[0].value.FACE_SCORE_THR, 0)
  assert.equal(page.writes[0].value.cap_interval, .5)
  assert.equal((await page.input('face-cap-interval')).value, '0.5')
  assert.equal((await page.input('face-track-iou')).value, '1')
  await page.input('face-max-lost', '1.2'); await page.save()
  assert.equal(page.writes.length, 1)
  await page.input('face-max-lost', '0')
  for (const [id, value] of [['face-cap-interval', '0'], ['face-cap-interval', '-1'], ['face-score', '1.1']]) {
    await page.input(id, value); await page.save()
    assert.equal(page.writes.length, 1)
    await page.input(id, id === 'face-score' ? '0.6' : '0.5')
  }
})

test('Haoda uses the shared human form and preserves independent IOUs', async () => {
  const page = await mount('Human', 'detect_human_haoda')
  assert.equal((await page.input('human-iou')).value, '0.21')
  await page.input('human-track-iou', '0'); await page.save()
  assert.equal(page.writes[0].value.DETECTION_IOU_THR, .21)
  assert.equal(page.writes[0].value.TRACK_IOU_THR, 0)
})

test('door blank environment means null, zero enables the filter, and out-of-range values are rejected', async () => {
  const page = await mount('Door')
  assert.equal((await page.input('door-env-threshold')).value, '')
  await page.save(); assert.equal(page.writes[0].value.env_threshold, null)
  await page.input('door-env-threshold', '0'); await page.save()
  assert.equal(page.writes[1].value.env_threshold, 0)
  await page.input('door-env-threshold', '1.1'); await page.save()
  assert.equal(page.writes.length, 2)
})

test('phone rejects fractional hit counts and preserves valid integers', async () => {
  const page = await mount('Phone')
  assert.equal((await page.input('phone-hit-count')).step, '1')
  await page.input('phone-hit-count', '1.5'); await page.save()
  assert.equal(page.writes.length, 0)
  await page.input('phone-hit-count', '1'); await page.save()
  assert.equal(page.writes[0].value.MIN_CONSECUTIVE_HITS, 1)
})
