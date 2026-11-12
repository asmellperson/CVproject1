// 启动 Vite 后访问 /tests/camera-select.browser.html，可由无头 Chromium 执行。
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthContext, type AuthContextValue } from '../src/auth/auth-context'
import { FEATURE_BY_PAGE } from '../src/auth/permissions'
import { DetectionDepartmentContext } from '../src/components/detection/DetectionDepartmentContext'
import { FeatureCameraManager } from '../src/components/FeatureCameraManager'
import { CameraMembership } from '../src/components/guard_behavior/CameraMembership'
import { LogisticsChannelConfigView } from '../src/components/logistics_single_person/LogisticsChannelConfigView'
import type { LogisticsChannelDetail } from '../src/components/logistics_single_person/types'
import type { AiVisionCamera } from '../src/lib/aivision'
import '../src/index.css'

const container = document.getElementById('app')!
const result = document.getElementById('result')!
const root = createRoot(container)
const successes: string[] = []
const requests: { path: string; method: string; body: Record<string, unknown> | null }[] = []
const features = Object.values(FEATURE_BY_PAGE)
const cameras: AiVisionCamera[] = Array.from({ length: 80 }, (_, index) => ({
  id: `camera_${index + 1}`, camera_id: index + 1, shm_name: `camera_${index + 1}`,
  name: `摄像头${String(index + 1).padStart(3, '0')} · 检测区域长名称回归`,
  department: 'general_electric', enabled: true, fps: 5, sort_order: index,
  feature_sort_orders: Object.fromEntries(features.map((feature) => [feature, index])),
  functions: Object.fromEntries(features.map((feature) => [feature, false])),
}))
const channel: LogisticsChannelDetail = {
  id: 1, name: '回归物流通道', feature_name: 'detect_logistics_single_person', department: 'general_electric',
  enabled: true, sort_order: 0, created_at: null, updated_at: null, members: [], status: null,
  config: {
    schedule: { weekdays: [1, 2, 3, 4, 5, 6, 7], start: '00:00:00', end: '00:00:00', timezone: 'Asia/Shanghai' },
    confidence_threshold: 0.3, model_iou_threshold: 0.3, min_box_area: 0,
    min_aspect_ratio: 0, max_aspect_ratio: 10, cap_interval: 0.2,
    empty_grace_seconds: 1, multi_grace_seconds: 1, alarm_interval: 30,
    alarm: { sql_enable: false, horn: { enabled: false, interval: null, horn_id: null, horn_event_id: null },
      wechat: { enabled: false, interval: null, user: '' } },
  },
}
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin)
  const method = init?.method || 'GET'
  const body = init?.body ? JSON.parse(String(init.body)) : null
  requests.push({ path: url.pathname, method, body })
  if (url.pathname === '/api/cameras') return json(cameras)
  if (url.pathname === '/api/departments') return json([{ name: 'general_electric', display_name: '通用电气事业部' }])
  const config = url.pathname.match(/^\/api\/features\/([^/]+)\/configs\/(camera_\d+)$/)
  if (config) return json({ camera: cameras.find((camera) => camera.shm_name === config[2]), feature: config[1],
    config: body ?? { enable: false, value: {}, alarm: {} } })
  if (url.pathname === '/api/guard-behavior/sites/1/cameras') return json({ camera_id: body?.camera_id })
  if (url.pathname === '/api/logistics-channels/detect_logistics_single_person/1') return json(channel)
  if (url.pathname === '/api/logistics-channels/detect_logistics_single_person/1/cameras') return json({ camera_id: body?.camera_id })
  throw new Error(`意外请求：${method} ${url.pathname}`)
}

function assert(value: unknown, message: string) { if (!value) throw new Error(message) }
async function until(predicate: () => unknown, label: string) {
  const started = Date.now()
  while (!predicate()) {
    if (Date.now() - started > 5000) throw new Error(`等待超时：${label}`)
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}
const pause = (milliseconds = 60) => new Promise((resolve) => setTimeout(resolve, milliseconds))
const context = (readOnly: boolean): AuthContextValue => ({
  user: { employee_id: 'test', name: '测试用户', role: readOnly ? 'viewer' : 'admin', departments: ['general_electric'],
    feature_access: { general_electric: features } },
  loading: false, isAdmin: !readOnly, login: async () => {}, changePassword: async () => {},
  logout: async () => {}, refreshMe: async () => {}, handleUnauthorized: () => {},
})
let renderRevision = 0
function render(feature: string, readOnly = false) {
  const revision = ++renderRevision
  const content = feature === 'guard_behavior'
    ? <CameraMembership key={revision} site={{ id: 1, name: '回归保安室', department: 'general_electric', enabled: true,
      sort_order: 0, created_at: '', updated_at: '' }} members={[]} busy={false} onChange={async (operation) => { await operation() }} />
    : feature === 'detect_logistics_single_person'
      ? <LogisticsChannelConfigView key={revision} feature={feature} department="general_electric" channels={[channel]}
        selectedChannelId={1} selectedChannelDetail={channel} canConfigure={!readOnly} onSelectChannel={() => {}}
        onChannelCreated={() => {}} onChannelDeleted={() => {}} onChanged={() => {}} />
      : <FeatureCameraManager key={revision} cameras={cameras} feature={feature} department="general_electric"
        currentCameraName="" onSelectCamera={() => {}} onCamerasChanged={async () => {}} />
  root.render(<StrictMode><AuthContext.Provider value={context(readOnly)}>
    <DetectionDepartmentContext.Provider value="general_electric"><div data-camera-test-render={revision}>{content}</div></DetectionDepartmentContext.Provider>
  </AuthContext.Provider></StrictMode>)
}
async function picker(feature: string) {
  await until(() => container.querySelector('[data-camera-test-render]')?.getAttribute('data-camera-test-render') === String(renderRevision), '配置组件切换')
  if (feature === 'detect_logistics_single_person') {
    await until(() => container.querySelector('[role="tab"]'), '物流配置标签')
    const tab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((element) => element.textContent === '摄像头')!
    tab.focus(); tab.click()
  }
  await until(() => {
    const element = feature === 'detect_logistics_single_person'
      ? container.querySelector<HTMLButtonElement>('#logistics-existing-camera')
      : container.querySelector<HTMLButtonElement>('[aria-label="添加已有摄像头"]')
    return element && !element.disabled
  }, `${feature} 摄像头选项加载`)
  return (feature === 'detect_logistics_single_person'
    ? container.querySelector('#logistics-existing-camera')
    : container.querySelector('[aria-label="添加已有摄像头"]')) as HTMLButtonElement
}
async function open(trigger: HTMLButtonElement) {
  trigger.scrollIntoView({ block: 'center' })
  trigger.focus()
  trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  await until(() => document.querySelector('[role="listbox"]'), '下拉框打开')
  await pause()
  return document.querySelector<HTMLElement>('[role="listbox"]')!
}
async function scrollAndChooseLast(trigger: HTMLButtonElement, label: string) {
  const content = await open(trigger)
  const viewport = content.querySelector<HTMLElement>('[data-radix-select-viewport]')!
  const initial = content.getBoundingClientRect()
  if (initial.height > 322) {
    const trace = [{ requested: 0, scrollTop: viewport.scrollTop, top: initial.top, height: initial.height }]
    for (let step = 0; step < 3; step += 1) {
      const requested = viewport.scrollTop + 140
      viewport.scrollTop = requested
      await pause()
      const rect = content.getBoundingClientRect()
      trace.push({ requested, scrollTop: viewport.scrollTop, top: rect.top, height: rect.height })
    }
    throw new Error(`${label}：长列表没有限制高度，滚动轨迹 ${JSON.stringify(trace)}`)
  }
  assert(viewport.scrollHeight > viewport.clientHeight + 1000, `${label}：没有内部滚动范围`)
  for (let step = 0; step < 4; step += 1) {
    const target = viewport.scrollTop + 140
    viewport.scrollTop = target
    await pause()
    const rect = content.getBoundingClientRect()
    const hovered = Array.from(content.querySelectorAll<HTMLElement>('[role="option"]')).find((element) => {
      const item = element.getBoundingClientRect()
      return item.top > rect.top + 10 && item.bottom < rect.bottom - 10
    })!
    const itemRect = hovered.getBoundingClientRect()
    hovered.dispatchEvent(new PointerEvent('pointermove', { pointerType: 'mouse', bubbles: true,
      clientX: itemRect.left + 12, clientY: itemRect.top + itemRect.height / 2 }))
    await pause()
    assert(viewport.scrollTop >= target - 2, `${label}：向下滚动后回跳 (${viewport.scrollTop} < ${target})`)
    assert(Math.abs(content.getBoundingClientRect().top - initial.top) <= 2, `${label}：滚动时弹层向上扩展或重定位`)
  }
  viewport.scrollTop = viewport.scrollHeight
  await pause()
  const last = Array.from(content.querySelectorAll<HTMLElement>('[role="option"]')).at(-1)!
  assert(last.textContent?.includes('摄像头080'), `${label}：缺少末尾摄像头`)
  const lastRect = last.getBoundingClientRect()
  last.dispatchEvent(new PointerEvent('pointermove', { pointerType: 'mouse', bubbles: true,
    clientX: lastRect.left + 12, clientY: lastRect.top + lastRect.height / 2 }))
  last.dispatchEvent(new PointerEvent('pointerup', { pointerType: 'mouse', bubbles: true, button: 0,
    clientX: lastRect.left + 12, clientY: lastRect.top + lastRect.height / 2 }))
  await until(() => !document.querySelector('[role="listbox"]'), `${label} 选择关闭`)
  assert(trigger.textContent?.includes('摄像头080'), `${label}：末尾摄像头选择没有保留`)
}

async function run() {
  for (const feature of features) {
    render(feature)
    const trigger = await picker(feature)
    await scrollAndChooseLast(trigger, feature)
    const previous = requests.length
    const add = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.includes('添加到当前功能'))!
    assert(add && !add.disabled, `${feature}：选择后添加按钮不可用`)
    add.click()
    const path = feature === 'guard_behavior' ? '/api/guard-behavior/sites/1/cameras'
      : feature === 'detect_logistics_single_person' ? '/api/logistics-channels/detect_logistics_single_person/1/cameras'
        : `/api/features/${feature}/configs/camera_80`
    await until(() => requests.slice(previous).some((request) => request.path === path && request.method !== 'GET'), `${feature} 提交末尾摄像头`)
    const saved = requests.slice(previous).find((request) => request.path === path && request.method !== 'GET')!
    assert(feature === 'guard_behavior' || feature === 'detect_logistics_single_person'
      ? saved.body?.camera_id === 80 : saved.body?.enable === true, `${feature}：提交设备或启用值错误`)
    successes.push(`${feature}：80项列表限高、连续滚动与鼠标悬停稳定，末尾摄像头可选择并正确添加`)
  }

  render('detect_human')
  const trigger = await picker('detect_human')
  const content = await open(trigger)
  content.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }))
  await until(() => document.activeElement?.textContent?.includes('摄像头080'), '键盘末项焦点')
  document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await until(() => !document.querySelector('[role="listbox"]'), '键盘选择关闭')
  assert(trigger.textContent?.includes('摄像头080'), '键盘选择未保留末尾摄像头')
  successes.push('键盘 End/Enter 仍可选择末尾摄像头')

  render('detect_human', true)
  await until(() => container.querySelector<HTMLButtonElement>('[aria-label="添加已有摄像头"]')?.disabled, '普通账号只读')
  const count = requests.filter((request) => request.method !== 'GET').length
  container.querySelector<HTMLButtonElement>('[aria-label="添加已有摄像头"]')!.click()
  await pause()
  assert(!document.querySelector('[role="listbox"]'), '只读摄像头下拉框仍可打开')
  assert(requests.filter((request) => request.method !== 'GET').length === count, '只读模式提交了摄像头修改')
  successes.push('普通账号添加控件保持只读，不发送修改请求')
  root.unmount()
  result.textContent = `通过 ${successes.length} 项\n${successes.join('\n')}`
  result.dataset.result = 'passed'
}
const runTest = () => run().catch((error) => {
  const page = container.textContent
  root.unmount()
  result.textContent = `${String(error.stack || error)}\n页面：${page}\n请求：${requests.map(({ method, path }) => `${method} ${path}`).join(', ')}`
  result.dataset.result = 'failed'
})
// 手动模式供浏览器自动化发送真实鼠标滚轮，不以合成 WheelEvent 代替原生滚动。
if (new URLSearchParams(location.search).has('manual')) {
  render('detect_human')
  result.textContent = '手动滚动验证模式'
} else {
  void runTest()
}
