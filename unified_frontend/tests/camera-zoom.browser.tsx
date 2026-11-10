// 启动 Vite 后访问 /tests/camera-zoom.browser.html；全部接口由本页模拟，不访问设备。
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthContext, type AuthContextValue } from '../src/auth/auth-context'
import { CameraZoomButton } from '../src/components/camera/CameraZoomButton'
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
const requests: { url: URL; method: string; action?: string; keepalive?: boolean; signal?: AbortSignal | null }[] = []
const camera = (id: number, feature = 'detect_phone'): AiVisionCamera => ({ id: `camera_${id}`, camera_id: id,
  shm_name: `camera_${id}`, name: `测试相机${id}`, department: 'general_electric', enabled: true, fps: 5,
  sort_order: id, feature_sort_orders: { [feature]: id }, functions: { [feature]: true } })
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const channel: LogisticsChannelDetail = { id: 11, name: '测试物流通道', department: 'general_electric',
  feature_name: 'detect_logistics_single_person', enabled: true, sort_order: 0, created_at: null, updated_at: null, status: null,
  config: { schedule: { weekdays: [0, 1, 2, 3, 4, 5, 6], start: '00:00', end: '23:59', timezone: 'Asia/Shanghai' },
    confidence_threshold: 0.5, model_iou_threshold: 0.5, min_box_area: 0, min_aspect_ratio: 0,
    max_aspect_ratio: 10, cap_interval: 0.2, empty_grace_seconds: 3, multi_grace_seconds: 3, alarm_interval: 30,
    alarm: { sql_enable: false, horn: { enabled: false, interval: null, horn_id: null, horn_event_id: null },
      wechat: { enabled: false, interval: null, user: '' } } },
  members: [{ id: 110, channel_id: 11, camera_id: 1, enabled: true, sort_order: 0, created_at: null, updated_at: null }] }
let status: 'supported' | 'unsupported' | 'unknown' = 'supported'
let failedControl = false
let denied = false
let slowCapability = false
let heldControl: (() => void) | null = null
let heldCapability: (() => void) | null = null
let holdControl = false
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin)
  const method = init?.method || 'GET'
  const action = method === 'POST' ? JSON.parse(String(init?.body)).action : undefined
  requests.push({ url, method, action, keepalive: init?.keepalive, signal: init?.signal })
  if (url.pathname === '/api/cameras') return json([camera(1, 'detect_logistics_single_person')])
  if (url.pathname === '/api/departments') return json([{ name: 'general_electric', display_name: '通用电气事业部' }])
  if (url.pathname === '/api/logistics-channels/detect_logistics_single_person/11') return json(channel)
  if (url.pathname.endsWith('/11/cameras/1/roi')) return json({ roi_pos: [], camera: { id: 1, name: '测试相机1', shm_name: 'camera_1', enable: true } })
  if (url.pathname.endsWith('/zoom')) {
    if (!url.searchParams.get('feature')) throw new Error('变焦请求缺少功能上下文')
    if (denied) return json({ detail: '当前摄像头权限已失效' }, 403)
    if (method === 'POST') {
      if (failedControl) return json({ detail: '停止变焦未获设备确认' }, 502)
      if (holdControl && action !== 'stop') return new Promise<Response>((resolve) => {
        heldControl = () => resolve(json({ action, stopped: true }))
      })
      return json({ action, stopped: true })
    }
    const response = () => json({ status, message: status === 'supported' ? '支持镜头变焦' : '当前设备未提供变焦能力',
      channel_id: 1, zoom_in: status === 'supported', zoom_out: status === 'supported', minimum: -100, maximum: 100 })
    if (slowCapability) return new Promise<Response>((resolve) => { heldCapability = () => resolve(response()) })
    return response()
  }
  if (url.pathname.endsWith('/preview')) return json({ enabled: false, mode: 'jpeg', url: null, raw: true })
  if (url.pathname.endsWith('/frame.jpg')) {
    if (url.searchParams.get('raw') !== 'true' || !url.searchParams.get('feature')) throw new Error('镜头预览丢失原始帧或功能授权')
    return new Response('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="100%" height="100%" fill="#284863"/></svg>', { headers: { 'Content-Type': 'image/svg+xml' } })
  }
  throw new Error(`意外请求：${method} ${url.pathname}`)
}

const context = (isAdmin: boolean): AuthContextValue => ({ user: null, loading: false, isAdmin,
  login: async () => {}, changePassword: async () => {}, logout: async () => {}, refreshMe: async () => {}, handleUnauthorized: () => {} })
const render = (id = 1, feature = 'detect_phone', isAdmin = true, manager = false, disabled = false) => {
  root.render(<StrictMode><AuthContext.Provider value={context(isAdmin)}>
    {manager ? <FeatureCameraManager key={`${feature}:${id}`} cameras={[camera(id, feature)]} feature={feature} department="general_electric"
      currentCameraName={`camera_${id}`} onSelectCamera={() => {}} onCamerasChanged={async () => {}} />
      : <CameraZoomButton camera={camera(id, feature)} feature={feature} disabled={disabled} />}
  </AuthContext.Provider></StrictMode>)
}
function renderMembers(kind: 'guard' | 'logistics') {
  const site = { id: 1, name: '测试保安室', department: 'general_electric' as const,
    enabled: true, sort_order: 0, created_at: '', updated_at: '' }
  root.render(<StrictMode><AuthContext.Provider value={context(true)}>
    {kind === 'guard' ? <CameraMembership site={site} busy={false} onChange={async () => {}} members={[{
      id: 1, camera_id: 1, name: '测试相机1', shm_name: 'camera_1', department: 'general_electric',
      physical_enabled: true, member_enabled: true, sort_order: 0, created_at: '', updated_at: '',
    }]} /> : <LogisticsChannelConfigView feature="detect_logistics_single_person" department="general_electric"
      channels={[channel]} selectedChannelId={11} selectedChannelDetail={channel} isAdmin
      onSelectChannel={() => {}} onChannelCreated={() => {}} onChannelDeleted={() => {}} onChanged={() => {}} />}
  </AuthContext.Provider></StrictMode>)
}
function assert(value: unknown, message: string) { if (!value) throw new Error(message) }
async function until(predicate: () => unknown, label: string) {
  const started = Date.now()
  while (!predicate()) {
    if (Date.now() - started > 6000) throw new Error(`等待超时：${label}`)
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}
const pause = () => new Promise((resolve) => setTimeout(resolve, 60))
const button = (text: string) => [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((item) => item.textContent === text)
const trigger = () => container.querySelector<HTMLButtonElement>('button[aria-label$="：变焦"]')!
async function open() {
  await pause()
  await until(() => trigger(), '变焦入口')
  trigger().click()
  await until(() => document.querySelector('[role="dialog"]'), '变焦弹窗')
}
async function ready() { await until(() => button('放大') && !button('放大')!.disabled, '可操作的镜头预览') }
async function close() {
  const closeButton = document.querySelector<HTMLButtonElement>('[role="dialog"] button[data-slot="dialog-close"]')
    ?? [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((item) => item.textContent === 'Close')
  assert(closeButton, '弹窗缺少关闭入口')
  closeButton!.click()
  await until(() => !document.querySelector('[role="dialog"]'), '弹窗关闭')
}

async function run() {
  render()
  await pause()
  assert(!requests.some((request) => request.url.pathname.endsWith('/zoom')), '未打开时提前查询或控制了设备')
  await open(); await ready()
  assert(!requests.some(({ method }) => method === 'POST'), '打开弹窗时发送了镜头动作')
  button('放大')!.click()
  await until(() => document.body.textContent?.includes('镜头已调整并停止'), '单步变焦完成')
  assert(requests.some(({ url, action }) => url.pathname.endsWith('/camera_1/zoom') && action === 'in'), '放大未操作当前设备')
  button('缩小')!.click()
  await until(() => requests.some(({ action }) => action === 'out'), '缩小请求')
  await ready()
  successes.push('按需查询真实设备能力，原始预览保留功能授权，放大/缩小使用当前设备')

  holdControl = true
  heldControl = null
  button('放大')!.click()
  await until(() => heldControl && button('放大中…'), '在途变焦')
  const before = requests.filter(({ action }) => action === 'in').length
  button('缩小')!.click()
  await pause()
  assert(requests.filter(({ action }) => action === 'in').length === before, '在途时允许重复提交')
  assert(!button('停止')!.disabled, '在途动作不能停止')
  button('停止')!.click()
  await until(() => document.body.textContent?.includes('镜头已停止'), '手动停止')
  heldControl!(); heldControl = null
  await pause()
  assert(document.body.textContent?.includes('镜头已停止'), '旧动作完成覆盖了较新的停止状态')
  successes.push('重复动作被阻止，停止可中断在途动作，旧回执不覆盖停止状态')

  button('放大')!.click()
  await until(() => heldControl, '关闭前在途动作')
  await close()
  assert(requests.some(({ action, keepalive }) => action === 'stop' && keepalive), '关闭弹窗未为旧设备发送 keepalive 停止')
  heldControl!(); heldControl = null; holdControl = false
  await pause()
  assert(!document.querySelector('[role="dialog"]'), '迟到的设备回执重新打开弹窗')
  successes.push('关闭弹窗时向旧设备发送停止，迟到回执不恢复页面')

  slowCapability = true
  render(2); await open()
  await until(() => heldCapability, '挂起能力查询')
  const oldRequests = requests.filter(({ url }) => url.pathname.endsWith('/camera_2/zoom'))
  render(3)
  await until(() => !document.querySelector('[role="dialog"]'), '切换设备关闭旧会话')
  assert(oldRequests.some(({ signal }) => signal?.aborted), '旧设备能力请求未取消')
  heldCapability!(); heldCapability = null; slowCapability = false
  await pause()
  await open(); await ready()
  assert(document.querySelector('[role="dialog"]')?.textContent?.includes('测试相机3'), '新会话显示了旧摄像头')
  await close()
  successes.push('切换摄像头取消旧能力查询，迟到响应不进入新设备会话')

  for (const value of ['unsupported', 'unknown'] as const) {
    status = value
    await open()
    await until(() => document.body.textContent?.includes(value === 'unsupported' ? '不支持变焦' : '能力未确认'), '不可用设备状态')
    assert(button('放大')!.disabled && button('缩小')!.disabled, '未支持的设备开放了变焦控制')
    await close()
  }
  successes.push('明确不支持与能力未确认分别展示，均不允许镜头动作')

  status = 'supported'
  await open(); await ready()
  failedControl = true
  button('放大')!.click()
  await until(() => document.querySelector('[role="alert"]')?.textContent?.includes('停止变焦未获设备确认'), '停止失败提示')
  assert(!button('停止')!.disabled, '停止失败后不能重试停止')
  failedControl = false
  button('停止')!.click()
  await until(() => document.body.textContent?.includes('镜头已停止'), '停止失败后恢复')
  await close()
  denied = true
  await open()
  await until(() => document.querySelector('[role="alert"]')?.textContent?.includes('权限已失效'), '权限失效')
  assert(button('放大')!.disabled && button('缩小')!.disabled && button('重新检测')!.disabled, '权限失效后继续提供控制')
  await close(); denied = false
  successes.push('动作和停止失败明确提示并允许重试，权限失效后停止操作')

  render(1, 'detect_phone', false)
  await until(() => trigger()?.disabled, '只读账号禁用入口')
  const requestCount = requests.length
  trigger().click(); await pause()
  assert(!document.querySelector('[role="dialog"]') && requests.length === requestCount, 'viewer 发起了设备请求')
  successes.push('viewer 不得打开镜头控制或发送设备查询')

  for (const feature of ['blocks', 'detect_door', 'detect_face', 'detect_human', 'detect_phone', 'recognize_face',
    'security_fence', 'tailgating', 'security_inspection', 'agv_person_check', 'visual_language_detection']) {
    render(1, feature, true, true)
    await open(); await ready()
    assert(requests.some(({ url }) => url.pathname.endsWith('/zoom') && url.searchParams.get('feature') === feature), `功能 ${feature} 未正确传递上下文`)
    await close()
  }
  successes.push('普通检测功能共用摄像头管理器均可打开变焦预览并正确传递功能上下文')

  renderMembers('guard')
  await open(); await ready()
  button('放大')!.click()
  await until(() => document.body.textContent?.includes('镜头已调整并停止'), '保安室成员变焦')
  assert(requests.some(({ url, action }) => action === 'in' && url.searchParams.get('feature') === 'guard_behavior'), '保安室未通过共用控件控制成员镜头')
  await close()
  renderMembers('logistics')
  await until(() => [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].some((tab) => tab.textContent === '摄像头'), '物流配置标签')
  const cameraTab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((tab) => tab.textContent === '摄像头')!
  cameraTab.focus(); cameraTab.click()
  await open(); await ready()
  button('缩小')!.click()
  await until(() => document.body.textContent?.includes('镜头已调整并停止'), '物流通道成员变焦')
  assert(requests.some(({ url, action }) => action === 'out' && url.searchParams.get('feature') === 'detect_logistics_single_person'), '物流通道未通过共用控件控制成员镜头')
  await close()
  successes.push('保安室与物流通道的实际成员列表均可操作变焦，成员绑定和功能上下文保持正确')

  root.unmount()
  result.dataset.status = 'passed'
  result.textContent = `${successes.length} 项验证通过\n${successes.join('\n')}`
}
void run().catch((cause) => { result.dataset.status = 'failed'; result.textContent = `${successes.join('\n')}\n${cause instanceof Error ? cause.stack : cause}` })
