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
function overview(departments) {
  return { departments, department_summaries: {}, ok: true, level: 'healthy', generated_at: 1, inventory_complete: true, inventory_errors: {},
    capabilities: ids.map((id, index) => ({ id, name: labels[index], source: index === 0 ? 'security_vlm' : 'aivision', camera_count: 0, online_camera_count: 0, running: false, model_ready: false })),
    cameras: [], guard_behavior_sites: [], services: { aivision: service, security_vlm: service },
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
const admin = { employee_id: 'admin', role: 'admin', departments: [] }
deps['@/auth/useAuth'] = { useAuth: () => ({ isAdmin: true, user: admin }) }
const { HomeSection } = await compile('sections/HomeSection.tsx', deps)

for (const department of permissions.DEPARTMENTS) {
  test(`${department} 总览始终展示九个能力和本事业部清单`, () => {
    const data = overview([department])
    data.cameras = [{ key: 'aivision:1', name: `${department}摄像头`, department, source: 'aivision', identifier: 'camera_1', online: false, capabilities: [], aivision_camera: null }]
    const html = renderToStaticMarkup(React.createElement(HomeSection, { onNavigate() {}, overviewState: { data, error: '', loading: false, refresh() {} } }))
    const board = html.slice(html.indexOf('运行状态看板'), html.indexOf('监管概况'))
    for (const label of labels) assert.equal(board.split(label).length - 1, 1, label)
    assert.ok(html.includes(`${department}摄像头`))
    assert.equal(html.includes('其他事业部摄像头'), false)
  })
}
test('清单失败显示明确错误，不显示空清单结论', () => {
  const html = renderToStaticMarkup(React.createElement(HomeSection, { onNavigate() {}, overviewState: { data: null, error: '摄像头清单加载失败：测试网络错误', loading: false, refresh() {} } }))
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
      slots[i] ??= { value: typeof initial === 'function' ? initial() : initial }
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

test('平台标题不显示任何事业部名称，清单同时显示多个授权事业部', () => {
  const data = overview(permissions.DEPARTMENTS)
  data.cameras = permissions.DEPARTMENTS.map((department, i) => ({ key: `aivision:${i}`, name: `${department}摄像头`, department,
    source: 'aivision', identifier: `camera_${i}`, online: false, capabilities: [], aivision_camera: null }))
  const html = renderToStaticMarkup(React.createElement(HomeSection, { onNavigate() {}, overviewState: { data, error: '', loading: false, refresh() {} } }))
  const hero = html.slice(0, html.indexOf('</section>'))
  assert.ok(hero.includes('福达 AI 视觉安全监管平台'))
  for (const label of Object.values(permissions.DEPARTMENT_LABELS)) assert.equal(hero.includes(label), false)
  for (const department of permissions.DEPARTMENTS) assert.ok(html.includes(`${department}摄像头`))
})

test('管理员从不同事业部检测页点击总览后清空事业部，URL 与总览范围保持平台级', async () => {
  const h = hooks()
  const previous = globalThis.window
  const browser = new EventTarget()
  browser.location = new URL(`http://test/?page=face-recognition&department=${permissions.DEPARTMENTS[0]}`)
  browser.history = { replaceState(_state, _title, url) { browser.location = new URL(url) } }
  browser.localStorage = { getItem() { return null } }
  globalThis.window = browser
  const sidebar = () => null
  const home = () => null
  const overviewUsers = []
  const data = overview(permissions.DEPARTMENTS)
  const { default: App } = await compile('App.tsx', {
    react: { ...React, ...h.hooks },
    '@/components/Sidebar': { Sidebar: sidebar }, '@/components/Topbar': { Topbar: () => null },
    '@/sections/HomeSection': { HomeSection: home }, '@/components/ui/sonner': { Toaster: () => null },
    '@/lib/utils': { cn: (...items) => items.filter(Boolean).join(' ') },
    '@/hooks/use-mobile': { useIsMobile: () => false },
    '@/hooks/use-overview': { useOverview: (user) => { overviewUsers.push(user); return { data, error: '', loading: false, refresh() {} } } },
    '@/auth/useAuth': { useAuth: () => ({ user: admin }) }, '@/auth/permissions': permissions,
  })
  function find(node, type) {
    if (!node || typeof node !== 'object') return null
    if (node.type === type) return node
    for (const child of React.Children.toArray(node.props?.children)) {
      const result = find(child, type)
      if (result) return result
    }
    return null
  }
  try {
    let tree = h.render(() => App())
    for (const department of permissions.DEPARTMENTS) {
      find(tree, sidebar).props.onPageChange('face-recognition', department)
      tree = h.render()
      assert.equal(find(tree, sidebar).props.currentDepartment, department)
      assert.equal(browser.location.search, `?page=face-recognition&department=${department}`)
      find(tree, sidebar).props.onPageChange('overview')
      tree = h.render()
      assert.equal(find(tree, sidebar).props.currentPage, 'overview')
      assert.equal(find(tree, sidebar).props.currentDepartment, null)
      assert.equal(browser.location.search, '?page=overview')
      assert.equal(find(tree, home).props.department, undefined)
      assert.equal(find(tree, home).props.overviewState.data, data)
    }
    find(tree, sidebar).props.onPageChange('face-recognition')
    tree = h.render()
    assert.equal(find(tree, sidebar).props.currentPage, 'overview')
    assert.equal(find(tree, sidebar).props.currentDepartment, null)
    assert.ok(overviewUsers.every((user) => user === admin))
    browser.location = new URL(`http://test/?page=overview&department=${permissions.DEPARTMENTS[2]}`)
    browser.dispatchEvent(new Event('popstate'))
    h.render()
    assert.equal(browser.location.search, '?page=overview')
  } finally { h.dispose(); globalThis.window = previous }
})

test('账号或权限切换后旧成功、失败响应不能覆盖当前总览，刷新可以恢复错误', async () => {
  const h = hooks(), requests = []
  let task, pollOptions, user = admin
  const viewer = { employee_id: 'viewer', role: 'viewer', departments: [permissions.DEPARTMENTS[1]] }
  const previous = globalThis.window
  globalThis.window = new EventTarget()
  const { useOverview } = await compile('hooks/use-overview.ts', {
    react: h.hooks,
    '../lib/api': { OVERVIEW_POLL_INTERVAL_MS: 30000, OVERVIEW_REQUEST_TIMEOUT_MS: 8000,
      getOverview: (...args) => new Promise((resolve, reject) => requests.push({ args, resolve, reject })) },
    './use-serial-poll': { useSerialPoll: (next, options) => { task = next; pollOptions = options } },
    '../lib/camera-events': { PLATFORM_CAMERAS_CHANGED_EVENT: 'cameras' },
    '../lib/runtime-events': { PLATFORM_RUNTIME_CHANGED_EVENT: 'runtime' },
  })
  try {
    h.render(() => useOverview(user))
    const first = task(new AbortController().signal)
    user = viewer
    assert.equal(h.render().data, null)
    const second = task(new AbortController().signal)
    requests[1].resolve(overview(viewer.departments)); await second
    requests[0].resolve(overview(permissions.DEPARTMENTS)); await first
    assert.deepEqual(h.render().data.departments, viewer.departments)
    const failing = task(new AbortController().signal)
    requests[2].reject(new Error('测试失败')); await failing
    assert.match(h.render().error, /摄像头清单加载失败/)
    h.render().refresh(); h.render()
    const recovery = task(new AbortController().signal)
    requests[3].resolve(overview(viewer.departments)); await recovery
    assert.equal(h.render().error, '')
    const lateError = task(new AbortController().signal)
    user = admin; h.render()
    const latest = task(new AbortController().signal)
    requests[5].resolve(overview(permissions.DEPARTMENTS)); await latest
    requests[4].reject(new Error('旧账号错误')); await lateError
    assert.deepEqual(h.render().data.departments, permissions.DEPARTMENTS)
    assert.equal(h.render().error, '')
    const beforeReturn = task(new AbortController().signal)
    user = viewer; h.render()
    user = admin; h.render()
    const afterReturn = task(new AbortController().signal)
    requests[7].resolve(overview(permissions.DEPARTMENTS)); await afterReturn
    requests[6].reject(new Error('切换前的旧错误')); await beforeReturn
    assert.equal(h.render().error, '')
    for (const { args } of requests) {
      assert.equal(args.length, 1)
      assert.deepEqual(Object.keys(args[0]), ['signal'])
    }
    user = null
    assert.equal(h.render().data, null)
    assert.equal(pollOptions.enabled, false)
  } finally { h.dispose(); globalThis.window = previous }
})

test('总览 API 不发送事业部查询参数', async () => {
  const api = await compile('lib/api.ts', {
    '@/lib/camera-events': { notifyPlatformCamerasChanged() {} },
    '@/lib/runtime-events': { notifyPlatformRuntimeChanged() {} },
  })
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return { ok: true, json: async () => overview(permissions.DEPARTMENTS) } }
  try {
    const signal = new AbortController().signal
    await api.getOverview({ signal })
    assert.equal(calls[0].url, '/api/overview')
    assert.equal(calls[0].init.credentials, 'include')
    assert.equal(calls[0].init.signal, signal)
  } finally { globalThis.fetch = original }
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
