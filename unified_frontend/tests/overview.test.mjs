import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const root = new URL('../src/', import.meta.url)
async function compile(path, imports = {}) {
  const source = (await readFile(new URL(path, root), 'utf8')).replaceAll('import.meta.env', '({})')
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText
  const module = { exports: {} }
  Function('require', 'exports', 'module', output)((name) => imports[name] ?? require(name), module.exports, module)
  return module.exports
}
const permissions = await compile('auth/permissions.ts')
const ids = ['security-vlm', 'guard-behavior', 'intrusion-detection', 'door-detection', 'face-detection', 'face-recognition', 'human-detection', 'logistics-single-person', 'phone-detection']
const labels = ['安检流程规范检测', '保安行为规范检测', '区域入侵检测', '大门开关异常检测', '人脸逗留检测', '人脸身份识别', '人员违规逗留检测', '物流通道单人检测', '手机使用检测']
const service = { online: true, running: false, error: null, latency_ms: 1, camera_count: 0, online_camera_count: 0, model_ready: false }
function overview(department) {
  return { department, ok: true, level: 'healthy', generated_at: 1, inventory_complete: true, inventory_errors: {},
    capabilities: ids.map((id, index) => ({ id, name: labels[index], source: index === 0 ? 'security_vlm' : index === 1 ? 'guard_room' : 'aivision', camera_count: 0, online_camera_count: 0, running: false, model_ready: false })),
    cameras: [], guard_room_sites: [], services: { aivision: service, guard_room: service, security_vlm: service },
    summary: { capability_total: 9, capability_online: 9, capability_running: 0, camera_total: 0, camera_online: 0, camera_offline: 0 } }
}
const wrapper = ({ children }) => React.createElement('div', null, children)
const ui = new Proxy({}, { get: () => wrapper })
const icons = new Proxy({}, { get: () => () => null })
const deps = {
  react: React, 'lucide-react': icons, '@/lib/utils': { cn: (...items) => items.filter(Boolean).join(' ') },
  '@/components/OverviewMascot': { OverviewMascot: () => null },
  '@/auth/useAuth': { useAuth: () => ({ isAdmin: false, user: { role: 'admin' } }) },
  '@/auth/permissions': permissions,
  '@/hooks/use-department-catalog': { useDepartmentCatalog: () => ({ options: [], labels: {}, loading: false, error: '' }) },
  '@/lib/nav': { detectionNavItems: ids.map((id, i) => ({ id, label: labels[i] })) },
  '@/lib/api': {}, '@/lib/aivision': {}, '@/lib/security-vlm': {},
  './HomeSection.status': await compile('sections/HomeSection.status.ts'),
}
for (const name of ['button', 'badge', 'alert-dialog', 'dialog', 'input', 'label', 'select', 'switch']) deps[`@/components/ui/${name}`] = ui
const { HomeSection } = await compile('sections/HomeSection.tsx', deps)

for (const department of permissions.DEPARTMENTS) {
  test(`${department} 总览始终展示九个能力和本事业部清单`, () => {
    const data = overview(department)
    data.cameras = [{ key: 'aivision:1', name: `${department}摄像头`, department, source: 'aivision', identifier: 'camera_1', online: false, capabilities: [], aivision_camera: null }]
    const html = renderToStaticMarkup(React.createElement(HomeSection, { department, onNavigate() {}, overviewState: { data, error: '', loading: false, refresh() {} } }))
    const board = html.slice(html.indexOf('运行状态看板'), html.indexOf('监管概况'))
    for (const label of labels) assert.equal(board.split(label).length - 1, 1, label)
    assert.ok(html.includes(`${department}摄像头`))
    assert.equal(html.includes('其他事业部摄像头'), false)
  })
}
test('清单失败显示明确错误，不显示空清单结论', () => {
  const html = renderToStaticMarkup(React.createElement(HomeSection, { department: permissions.DEPARTMENTS[0], onNavigate() {}, overviewState: { data: null, error: '摄像头清单加载失败：测试网络错误', loading: false, refresh() {} } }))
  assert.ok(html.includes('role="alert"'))
  assert.ok(html.includes('摄像头清单加载失败'))
  assert.equal(html.includes('暂无摄像头。'), false)
})

function hooks() {
  const slots = []
  let cursor = 0, pending = [], render, value
  const hooks = {
    useState(initial) {
      const i = cursor++
      slots[i] ??= { value: initial }
      return [slots[i].value, (next) => { slots[i].value = typeof next === 'function' ? next(slots[i].value) : next }]
    },
    useRef(initial) { return slots[cursor++] ??= { current: initial } },
    useEffect(fn, deps) {
      const i = cursor++
      if (!slots[i] || deps.some((dep, index) => dep !== slots[i].deps[index])) { slots[i]?.cleanup?.(); slots[i] = { deps }; pending.push(() => { slots[i].cleanup = fn() }) }
    },
  }
  return { hooks, render(fn = render) { render = fn; cursor = 0; value = render(); pending.splice(0).forEach((fn) => fn()); return value }, dispose() { slots.forEach((slot) => slot.cleanup?.()) } }
}

test('切换事业部后旧成功或失败响应不能覆盖当前事业部；错误可刷新恢复', async () => {
  const h = hooks(), requests = []
  let task, department = permissions.DEPARTMENTS[0]
  const previous = globalThis.window
  globalThis.window = new EventTarget()
  const { useOverview } = await compile('hooks/use-overview.ts', {
    react: h.hooks,
    '../lib/api': { OVERVIEW_POLL_INTERVAL_MS: 30000, OVERVIEW_REQUEST_TIMEOUT_MS: 8000,
      getOverview: (department) => new Promise((resolve, reject) => requests.push({ department, resolve, reject })) },
    './use-serial-poll': { useSerialPoll: (next) => { task = next } },
    '../lib/camera-events': { PLATFORM_CAMERAS_CHANGED_EVENT: 'cameras' },
    '../lib/runtime-events': { PLATFORM_RUNTIME_CHANGED_EVENT: 'runtime' },
  })
  try {
    h.render(() => useOverview(department))
    const first = task(new AbortController().signal)
    department = permissions.DEPARTMENTS[1]
    assert.equal(h.render().data, null)
    const second = task(new AbortController().signal)
    requests[1].resolve(overview(department)); await second
    requests[0].resolve(overview(permissions.DEPARTMENTS[0])); await first
    assert.equal(h.render().data.department, department)
    const failing = task(new AbortController().signal)
    requests[2].reject(new Error('测试失败')); await failing
    assert.match(h.render().error, /摄像头清单加载失败/)
    h.render().refresh(); h.render()
    const recovery = task(new AbortController().signal)
    requests[3].resolve(overview(department)); await recovery
    assert.equal(h.render().error, '')
    const lateError = task(new AbortController().signal)
    department = permissions.DEPARTMENTS[2]; h.render()
    const latest = task(new AbortController().signal)
    requests[5].resolve(overview(department)); await latest
    requests[4].reject(new Error('旧事业部错误')); await lateError
    assert.equal(h.render().data.department, department)
    assert.equal(h.render().error, '')
    const beforeReturn = task(new AbortController().signal)
    const returningDepartment = department
    department = permissions.DEPARTMENTS[0]; h.render()
    department = returningDepartment; h.render()
    const afterReturn = task(new AbortController().signal)
    requests[7].resolve(overview(department)); await afterReturn
    requests[6].reject(new Error('切换前的旧错误')); await beforeReturn
    assert.equal(h.render().error, '')
    assert.equal(h.render().data.department, returningDepartment)
  } finally { h.dispose(); globalThis.window = previous }
})

test('前端正式源码没有旧业务入口或独立子服务地址', async () => {
  async function scan(path = '') {
    for (const entry of await readdir(new URL(path, root), { withFileTypes: true })) {
      const name = `${path}${entry.name}`
      if (entry.isDirectory()) { await scan(`${name}/`); continue }
      if (!/\.[tj]sx?$/.test(name) || /(?:\.test\.|\.type-test\.)/.test(name)) continue
      const source = await readFile(new URL(name, root), 'utf8')
      assert.doesNotMatch(source, /\/api\/platform\/status|\/aivision\/api|\/security-vlm\/api|fetch\(`\/security-vlm|\/api\/sites|\/integrations\/guard-room\/api|VITE_AIVISION_URL|AIVISION_URL|PlatformStatus|usePlatformStatus|PLATFORM_STATUS_/, name)
    }
  }
  await scan()
  const home = await readFile(new URL('sections/HomeSection.tsx', root), 'utf8')
  assert.doesNotMatch(home, /getAiVisionCameras|getLogisticsCameraInventory|getGuardRoomSites|getSecurityVlmCameras|mergeAiVision/)
  assert.match(home, /onNavigate\(page, camera.department\)/)
})
