// 启动 Vite 后访问 /tests/fence-whitelist.browser.html，可由无头 Chromium 执行。
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthContext, type AuthContextValue } from '../src/auth/auth-context'
import { DetectionDepartmentContext } from '../src/components/detection/DetectionDepartmentContext'
import { canConfigureDepartment, getAccessibleDepartments, hasPageAccess, type UserRole, type DepartmentId } from '../src/auth/permissions'
import { FenceConfigView } from '../src/components/security_fence/FenceConfigView'
import { NUMBER_FIELDS } from '../src/components/security_fence/api'
import { facePersonPermissionsApi } from '../src/components/face_recognition/api'
import '../src/index.css'

const container = document.getElementById('app')!
const result = document.getElementById('result')!
const root = createRoot(container)
const requests: { url: URL; method: string; signal?: AbortSignal | null }[] = []
const allowed: Record<string, boolean> = { camera_1: false, camera_2: false }
const successes: string[] = []
let emptyCameras = false
let slowCamera = ''
let resolveSlow: (() => void) | null = null
let failSave = false
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const person = (camera: string) => ({ id: 123, person_name: `${camera}人员`, hik_person_id: '123', hik_source: 'one',
  is_active: true, is_allowed: allowed[camera], last_synced_at: '2026-11-05T08:00:00' })
const page = (camera: string) => ({ total: 1, page: 1, page_size: 20, items: [person(camera)] })
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin)
  const method = init?.method || 'GET'
  requests.push({ url, method, signal: init?.signal })
  if (url.pathname === '/api/cameras') return json(emptyCameras ? [] : [1, 2].map((id) => ({
    id, camera_id: id, name: `围栏相机${id}`, shm_name: `camera_${id}`, enabled: true,
    department: 'general_electric', functions: { security_fence: true }, sort_order: id,
    feature_sort_orders: { security_fence: id },
  })))
  if (url.pathname.startsWith('/api/features/security_fence/configs/')) return json({ config: {
    enable: true, value: { ...Object.fromEntries(NUMBER_FIELDS.map(([key, , min]) => [key, min])),
      roi_pos: [], forbidden_start: '22:00', forbidden_end: '08:00', timezone: 'Asia/Shanghai' }, alarm: {},
  } })
  const fence = url.pathname.match(/^\/api\/security-fence\/cameras\/(camera_[12])\/persons(?:\/123)?$/)
  if (fence) {
    if (url.searchParams.has('department')) throw new Error('围栏白名单不应按事业部请求')
    const camera = fence[1]
    if (method === 'PATCH') {
      if (failSave) return json({ detail: '保存失败回归' }, 409)
      allowed[camera] = JSON.parse(String(init?.body)).is_allowed
      return json(person(camera))
    }
    if (slowCamera === camera) return new Promise<Response>((resolve) => {
      resolveSlow = () => resolve(json({ ...page(camera), items: [{ ...person(camera), person_name: '过期旧摄像头结果' }] }))
    })
    return json(page(camera))
  }
  if (url.pathname.startsWith('/api/face-recognition/persons')) return json(method === 'PATCH' ? person('camera_1') : page('camera_1'))
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
const pause = () => new Promise((resolve) => setTimeout(resolve, 50))
const context = (role: boolean | UserRole, departments: DepartmentId[] = ['general_electric']): AuthContextValue => ({
  user: { employee_id: 'test', name: '测试用户', role: typeof role === 'boolean' ? (role ? 'admin' : 'viewer') : role,
    departments, feature_access: { general_electric: ['security_fence', 'detect_phone', 'recognize_face'] } },
  loading: false, isAdmin: role === true || role === 'admin',
  login: async () => {}, changePassword: async () => {}, logout: async () => {}, refreshMe: async () => {}, handleUnauthorized: () => {} })
const render = (role: boolean | UserRole = true, key = 'workspace', departments?: DepartmentId[]) => root.render(<StrictMode><AuthContext.Provider value={context(role, departments)}>
  <DetectionDepartmentContext.Provider value="general_electric"><FenceConfigView key={key} department="general_electric" /></DetectionDepartmentContext.Provider>
</AuthContext.Provider></StrictMode>)
const toggle = () => container.querySelector('[role="switch"][aria-label$="允许通行"]') as HTMLButtonElement | null
const tab = () => Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((element) => element.textContent?.includes('围栏白名单'))!
async function selectCamera(camera: number) {
  const trigger = container.querySelector('#fence-whitelist-camera') as HTMLButtonElement
  trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  await until(() => document.querySelector('[role="option"]'), '摄像头下拉框')
  const option = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]')).find((element) => element.textContent === `围栏相机${camera}`)!
  option.click()
  await until(() => !document.querySelector('[role="option"]'), '摄像头选项关闭')
}

async function run() {
  render()
  await until(() => container.textContent?.includes('当前摄像头配置已加载'), '摄像头配置')
  tab().focus(); tab().click()
  await until(() => toggle() && container.textContent?.includes('camera_1人员'), '摄像头1白名单')
  assert(container.querySelector('#fence-whitelist-camera'), '白名单缺少摄像头选择器')
  assert(container.textContent?.includes('各摄像头独立生效'), '白名单仍提示按事业部共用')
  toggle()!.click()
  await until(() => container.textContent?.includes('通行权限已保存'), '保存后回读')
  assert(toggle()!.getAttribute('aria-checked') === 'true', '保存后未显示实际允许状态')
  assert(requests.filter(({ url, method }) => url.pathname.endsWith('/camera_1/persons') && method === 'GET').length >= 2, '保存后未回读当前摄像头')
  successes.push('围栏配置页按摄像头选择，逐人即时保存并回读')

  await selectCamera(2)
  await until(() => container.textContent?.includes('camera_2人员'), '摄像头2白名单')
  assert(toggle()!.getAttribute('aria-checked') === 'false', '同事业部摄像头误用了另一台白名单')
  failSave = true
  toggle()!.click()
  await until(() => container.textContent?.includes('保存失败回归'), '保存失败提示')
  assert(toggle()!.getAttribute('aria-checked') === 'false', '保存失败后错误显示为允许')
  failSave = false
  successes.push('同事业部摄像头白名单独立，保存失败保持真实状态')

  slowCamera = 'camera_1'
  await selectCamera(1)
  await until(() => resolveSlow !== null, '挂起旧摄像头请求')
  assert(!container.textContent?.includes('camera_2人员'), '切换后仍保留旧摄像头名单')
  await selectCamera(2)
  await until(() => container.textContent?.includes('camera_2人员'), '切回摄像头2')
  assert(requests.some(({ url, signal }) => url.pathname.endsWith('/camera_1/persons') && signal?.aborted), '旧摄像头名单请求未取消')
  resolveSlow!()
  await pause()
  assert(!container.textContent?.includes('过期旧摄像头结果'), '晚到的旧摄像头响应覆盖了当前名单')
  slowCamera = ''
  successes.push('切换摄像头清空旧名单并取消请求，晚到响应不覆盖当前结果')

  render(false)
  await until(() => toggle()?.disabled, '普通账号只读')
  successes.push('普通账号可以查看名单，允许状态开关只读')

  render('department_admin')
  await until(() => toggle() && !toggle()!.disabled, '部门管理员可编辑本部门白名单')
  toggle()!.click()
  await until(() => container.textContent?.includes('通行权限已保存'), '部门管理员保存回读')
  successes.push('部门管理员沿用现有开关，保存本部门摄像头白名单')

  render('department_admin', 'workspace', ['electronics_electrician'])
  await until(() => toggle()?.disabled, '跨部门白名单只读')
  const patches = requests.filter(({ method }) => method === 'PATCH').length
  toggle()!.click(); await pause()
  assert(requests.filter(({ method }) => method === 'PATCH').length === patches, '跨部门账号发送了修改请求')
  successes.push('页面所选部门不能扩大部门管理员的授权')

  const scopedUser = context('department_admin').user!
  assert(getAccessibleDepartments(scopedUser).join() === 'general_electric', '部门管理员看到了其他部门入口')
  assert(!hasPageAccess(scopedUser, 'user-management') && !hasPageAccess(scopedUser, 'feature-management'), '部门管理员获得了全局管理入口')
  assert(canConfigureDepartment(scopedUser, 'general_electric', 'security_fence'), '本部门已开放功能不可编辑')
  assert(!canConfigureDepartment(scopedUser, 'general_electric', 'detect_door'), '未开放功能可编辑')
  assert(!canConfigureDepartment({ ...scopedUser, departments: ['all'] }, 'general_electric'), 'all 绕过了部门授权')
  assert(!canConfigureDepartment(context(false).user, 'general_electric'), '普通用户获得了配置权限')
  successes.push('角色、部门、功能权限取交集，账号及功能授权入口仍由系统管理员管理')

  await facePersonPermissionsApi.list('general_electric', { page: 1, page_size: 20 })
  await facePersonPermissionsApi.update('general_electric', 123, true)
  const faceRequests = requests.filter(({ url }) => url.pathname.startsWith('/api/face-recognition/'))
  assert(faceRequests.length === 2 && faceRequests.every(({ url }) => url.searchParams.get('department') === 'general_electric'), '人脸身份识别授权范围发生变化')
  successes.push('人脸身份识别仍使用事业部授权接口')

  emptyCameras = true
  const count = requests.filter(({ url }) => url.pathname.includes('/persons')).length
  render(true, 'empty')
  await until(() => container.textContent?.includes('请先添加并选择摄像头'), '无摄像头状态')
  tab().focus(); tab().click()
  await until(() => container.textContent?.includes('请先添加'), '无围栏摄像头提示')
  await pause()
  assert(!toggle(), '没有摄像头时仍展示可修改人员')
  assert(requests.filter(({ url }) => url.pathname.includes('/persons')).length === count, '没有摄像头时请求了全局名单')
  successes.push('没有围栏摄像头时显示空状态，不读取全局白名单')
  root.unmount()
  result.textContent = `通过 ${successes.length} 项\n${successes.join('\n')}`
  result.dataset.result = 'passed'
}
run().catch((error) => {
  result.textContent = `${String(error.stack || error)}\n页面：${container.textContent}\n请求：${requests.map(({ method, url }) => `${method} ${url.pathname}`).join(', ')}`
  result.dataset.result = 'failed'
})
