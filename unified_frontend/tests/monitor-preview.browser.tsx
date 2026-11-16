// 启动 Vite 后访问 /tests/monitor-preview.browser.html，可由无头 Chromium 执行。
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { CameraLivePreview } from '../src/components/monitor/CameraLivePreview'
import { CurrentDetectionCard } from '../src/components/monitor/CurrentDetectionCard'
import { useDetectionStatus } from '../src/components/monitor/useDetectionStatus'
import { useSmokeStatus } from '../src/components/smoke_detection/useSmokeStatus'
import { readSmokeParameters, saveSmokeParameters, readSmokeShields, saveSmokeShields, smokePictureUrl, readSmokeStatus } from '../src/components/smoke_detection/api'
import { previewRegions, regionDirection } from '../src/components/monitor/previewRegions'
import { LogisticsChannelMonitorView } from '../src/components/logistics_single_person/LogisticsChannelMonitorView'
import { invalidateLogisticsChannelQueries, updateLogisticsCameraRoi } from '../src/components/logistics_single_person/api'
import type { LogisticsChannelDetail } from '../src/components/logistics_single_person/types'
import type { AiVisionCamera } from '../src/lib/aivision'
import '../src/index.css'

const previewElement = document.getElementById('preview')!
const statusElement = document.getElementById('status')!
const resultElement = document.getElementById('result')!
const root = createRoot(previewElement)
const statusRoot = createRoot(statusElement)
const requests: URL[] = []
const smokeRequests: { url: URL; init?: RequestInit }[] = []
const successes: string[] = []
let statusRequests = 0
let connection = { connected: false, message: '' }
const onConnectionChange = (connected: boolean, message: string) => { connection = { connected, message } }
const pendingCapabilities = new Map<string, () => void>()
let holdVideoFrame = false
let failFirstCameraFrame = false
let finishVideoFrame: (() => void) | null = null
let videoFrameSignal: AbortSignal | null | undefined
let unauthorizedEvents = 0
let smokeMode: 'unknown' | 'active' | 'inactive' | 'hold' = 'unknown'
let finishSmokeStatus: (() => void) | null = null
let smokeStatusSignal: AbortSignal | null | undefined
const logisticsFeature = 'detect_logistics_single_person'
const logisticsRois = new Map<number, number[][]>()
let logisticsRoiReads = 0
let failLogisticsRoi = false
let holdLogisticsRoi = false
let finishLogisticsRoi: (() => void) | null = null
let logisticsRoiSignal: AbortSignal | null | undefined
const onUnauthorized = () => { unauthorizedEvents += 1 }
window.addEventListener('aicv:unauthorized', onUnauthorized)
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const roi = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
const hold = (signal?: AbortSignal | null) => new Promise<Response>((_, reject) => signal?.addEventListener('abort', () => reject(new DOMException('已取消', 'AbortError')), { once: true }))
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin)
  requests.push(url)
  // 与后端注册路径一致；多余的旧前缀必须返回404，不能落入通用状态桩而掩盖错误。
  if (url.pathname.startsWith('/api/aivision/smoke/')) return json({ detail: 'Not Found' }, 404)
  const smoke = /^\/api\/smoke\/([^/]+)\/(parameters|shields|picture|status)$/.exec(url.pathname)
  if (smoke) {
    smokeRequests.push({ url, init })
    assert(url.searchParams.get('department') === 'general_electric', '烟雾状态请求缺少事业部范围')
    const method = init?.method ?? 'GET'
    const resource = smoke[2]
    if (!['GET', 'PUT'].includes(method) || (['picture', 'status'].includes(resource) && method !== 'GET')) return json({ detail: 'Method Not Allowed' }, 405)
    if (resource === 'parameters') {
      const values = method === 'PUT' ? JSON.parse(String(init?.body)).values : { sensitivity: 52 }
      return json({ supported: true, message: '', channel_id: 1, global_enabled: true,
        parameters: [{ key: 'sensitivity', label: '烟雾灵敏度', kind: 'integer', value: values.sensitivity, minimum: 1, maximum: 100 }] })
    }
    if (resource === 'shields') {
      const value = method === 'PUT' ? JSON.parse(String(init?.body)) : { enabled: false, regions: [] }
      return json({ supported: true, writable: true, message: '', channel_id: 1,
        coordinate_width: 1000, coordinate_height: 1000, max_regions: 4, min_points: 4, max_points: 4, ...value })
    }
    if (resource === 'picture') return new Response('device-picture', { headers: { 'Content-Type': 'image/jpeg' } })
    const camera_key = decodeURIComponent(smoke[1])
    const response = (alarm_state: 'active' | 'inactive' | 'unknown') => json({
      camera_key, feature: 'smoke_detection', online: true, count: null,
      connection_state: 'connected', alarm_state, alarm: alarm_state === 'unknown' ? null : alarm_state === 'active',
      reason: alarm_state, updated_at: new Date().toISOString(), valid_for_seconds: 0.45,
      event_channel_id: 1, last_event_at: alarm_state === 'unknown' ? null : new Date().toISOString(),
    })
    if (smokeMode === 'hold') return new Promise<Response>((resolve, reject) => {
      smokeStatusSignal = init?.signal
      finishSmokeStatus = () => resolve(response('active'))
      init?.signal?.addEventListener('abort', () => reject(new DOMException('已取消', 'AbortError')), { once: true })
    })
    return response(smokeMode)
  }
  if (url.pathname.startsWith('/api/smoke/')) return json({ detail: 'Not Found' }, 404)
  if (url.pathname === '/api/departments') return json([{ name: 'general_electric', display_name: '通用电气事业部' }])
  const logisticsRoi = /^\/api\/logistics-channels\/detect_logistics_single_person\/(\d+)\/cameras\/(\d+)\/roi$/.exec(url.pathname)
  if (logisticsRoi) {
    const channelId = Number(logisticsRoi[1])
    const response = () => json({ roi_pos: logisticsRois.get(channelId) ?? roi,
      camera: { id: Number(logisticsRoi[2]), name: '物流摄像头', shm_name: 'camera_1', enable: true } })
    if (init?.method === 'PUT') {
      logisticsRois.set(channelId, JSON.parse(String(init.body)).roi_pos)
      return response()
    }
    logisticsRoiReads += 1
    if (failLogisticsRoi) return json({}, 503)
    if (holdLogisticsRoi && channelId === 11) return new Promise<Response>((resolve) => {
      logisticsRoiSignal = init?.signal
      finishLogisticsRoi = () => resolve(response())
    })
    return response()
  }
  if (url.pathname.endsWith('/preview')) {
    const camera = url.pathname.split('/')[3]
    if (camera === 'camera_3') return json({}, 403)
    if (['camera_4', 'camera_6', 'camera_7'].includes(camera)) return new Promise<Response>((resolve) => {
      pendingCapabilities.set(camera, () => resolve(json({ enabled: true, mode: 'mse',
        url: `/ws/cameras/${camera}/preview?feature=detect_phone`, raw: true })))
    })
    return json({ enabled: false, mode: 'jpeg', url: null, raw: true })
  }
  if (url.pathname.includes('/configs/')) return url.pathname.includes(logisticsFeature)
    ? json({ detail: '物流摄像头配置只通过通道 ROI 接口访问' }, 404)
    : json({ config: { value: { roi_pos: url.pathname.includes('camera_5') ? [] : roi } } })
  if (url.pathname.endsWith('/frame.jpg')) {
    if (url.searchParams.get('raw') !== 'true' || !['detect_phone', logisticsFeature].includes(url.searchParams.get('feature') || '')) throw new Error('预览未保留功能授权或请求了标注图片')
    if (/camera_[367]\//.test(url.pathname)) return json({}, url.pathname.includes('camera_7') ? 401 : 403)
    if (url.pathname.includes('/camera_1/') && failFirstCameraFrame) return json({}, 503)
    const width = url.pathname.includes('camera_2') ? 320 : 160
    const height = url.pathname.includes('camera_2') ? 180 : 120
    const response = () => new Response(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#284863"/></svg>`, { headers: { 'Content-Type': 'image/svg+xml' } })
    if (url.pathname.includes('camera_4') && holdVideoFrame) return new Promise<Response>((resolve) => {
      videoFrameSignal = init?.signal
      finishVideoFrame = () => resolve(response())
    })
    return response()
  }
  if (url.pathname.endsWith('/status')) {
    if (statusRequests++) return hold(init?.signal)
    return json({ camera_key: 'camera_1', feature: 'detect_phone', online: true, count: 1, alarm: true,
      reason: 'phone_confirmed', updated_at: new Date().toISOString(), valid_for_seconds: 0.5,
      duration_seconds: 2, threshold_seconds: 1.2,
      details: [{ label: '手机轨迹 1', confidence: 0.92, duration_seconds: 2, hits: 4, state: 'phone_confirmed' }] })
  }
  throw new Error(`意外请求：${url.pathname}`)
}

function assert(value: unknown, message: string) { if (!value) throw new Error(message) }
async function until(predicate: () => unknown, label: string) {
  const started = Date.now()
  while (!predicate()) {
    if (Date.now() - started > 5000) throw new Error(`等待超时：${label}`)
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}
const frameCount = (camera: string) => requests.filter((url) => url.pathname === `/api/cameras/${camera}/frame.jpg`).length
const pause = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms))
const render = (cameraKey: string, enabled = true) => root.render(<StrictMode><CameraLivePreview cameraKey={cameraKey} feature="detect_phone" department="general_electric" enabled={enabled} onConnectionChange={onConnectionChange} /></StrictMode>)
export function Status() {
  const result = useDetectionStatus('camera_1', 'detect_phone')
  return <CurrentDetectionCard feature="detect_phone" status={result?.status} error={result?.error} />
}

function SmokeStatusHarness({ cameraKey }: { cameraKey: string }) {
  const result = useSmokeStatus(cameraKey, 'general_electric')
  return <div>{JSON.stringify(result?.value ?? null)}</div>
}

const logisticsCamera: AiVisionCamera = { id: '1', camera_id: 1, name: '物流摄像头', shm_name: 'camera_1',
  department: 'general_electric', enabled: true, fps: 5, sort_order: 0,
  feature_sort_orders: { [logisticsFeature]: 0 }, functions: { [logisticsFeature]: true } }
function renderLogistics(channelId: number) {
  const channel: LogisticsChannelDetail = { id: channelId, name: `通道${channelId}`, department: 'general_electric',
    feature_name: logisticsFeature, enabled: true, sort_order: 0, created_at: null, updated_at: null, status: null,
    config: { schedule: { weekdays: [1, 2, 3, 4, 5, 6, 7], start: '00:00', end: '23:59', timezone: 'Asia/Shanghai' },
      confidence_threshold: 0.5, model_iou_threshold: 0.5, min_box_area: 0, min_aspect_ratio: 0,
      max_aspect_ratio: 10, cap_interval: 0.2, empty_grace_seconds: 3, multi_grace_seconds: 3, alarm_interval: 30,
      alarm: { sql_enable: false, horn: { enabled: false, interval: null, horn_id: null, horn_event_id: null },
        wechat: { enabled: false, interval: null, user: '' } } },
    members: [{ id: channelId * 10, channel_id: channelId, camera_id: 1, enabled: true,
      sort_order: 0, created_at: null, updated_at: null }] }
  root.render(<StrictMode><LogisticsChannelMonitorView feature={logisticsFeature} title="物流通道单人检测"
    channels={[channel]} selectedChannelId={channelId} selectedChannel={channel} selectedChannelDetail={channel}
    status={null} cameras={[logisticsCamera]} todayAlarmCount={0} latestAlarmAt={null} events={[]}
    loading={false} error={null} onSelectChannel={() => {}} onRefresh={() => {}} /></StrictMode>)
}

async function run() {
  const cameraKey = 'camera_1?烟雾'
  const encodedCamera = encodeURIComponent(cameraKey)
  const controller = new AbortController()
  const expectSmokeRequest = (resource: string, method: string) => {
    const request = smokeRequests[smokeRequests.length - 1]
    assert(request.url.pathname === `/api/smoke/${encodedCamera}/${resource}`, `${resource}没有使用后端原生路由或摄像头标识未编码`)
    assert(request.url.searchParams.get('department') === 'general_electric' && request.url.searchParams.size === 1, `${resource}事业部查询参数不正确`)
    assert(request.init?.method === method && request.init.credentials === 'include', `${resource}请求方法或登录凭据传递不正确`)
    return request
  }
  const parameters = await readSmokeParameters(cameraKey, 'general_electric', controller.signal)
  assert(parameters.parameters[0].value === 52, '设备实际参数未返回调用方')
  assert(expectSmokeRequest('parameters', 'GET').init?.signal === controller.signal, '参数读取未传递取消信号')
  successes.push('烟雾参数读取使用真实后端路由，保留事业部、登录凭据和取消信号')
  const savedParameters = await saveSmokeParameters(cameraKey, 'general_electric', { sensitivity: 75 })
  const parametersWrite = expectSmokeRequest('parameters', 'PUT')
  assert(JSON.parse(String(parametersWrite.init?.body)).values.sensitivity === 75 && savedParameters.parameters[0].value === 75, '参数保存请求体或回读结果不正确')
  assert(new Headers(parametersWrite.init?.headers).get('Content-Type') === 'application/json', '设备参数写入没有声明JSON格式')
  successes.push('烟雾参数写入使用PUT与values请求体，并保留设备回读结果')
  const shields = await readSmokeShields(cameraKey, 'general_electric', controller.signal)
  assert(shields.supported && shields.writable && shields.coordinate_height === 1000, '屏蔽区能力响应未返回调用方')
  assert(expectSmokeRequest('shields', 'GET').init?.signal === controller.signal, '屏蔽区读取未传递取消信号')
  successes.push('烟雾屏蔽区读取使用真实后端路由并返回设备能力')
  const region = { id: 1, enabled: true, name: '屏蔽区一', points: [{ x: 0.1, y: 0.1 }, { x: 0.8, y: 0.1 }, { x: 0.8, y: 0.8 }, { x: 0.1, y: 0.8 }] }
  const savedShields = await saveSmokeShields(cameraKey, 'general_electric', { enabled: true, regions: [region] })
  const shieldsWrite = expectSmokeRequest('shields', 'PUT')
  assert(JSON.stringify(JSON.parse(String(shieldsWrite.init?.body))) === JSON.stringify({ enabled: true, regions: [region] }) && savedShields.regions[0].name === region.name, '屏蔽区保存请求体或回读结果不正确')
  successes.push('烟雾屏蔽区写入使用PUT并完整传递使能、区域和归一化坐标')
  const picture = new URL(smokePictureUrl(cameraKey, 'general_electric'), location.origin)
  assert(picture.pathname === `/api/smoke/${encodedCamera}/picture` && picture.searchParams.get('department') === 'general_electric', '设备抓图地址未使用原生路由与事业部范围')
  assert((await fetch(`/api/aivision/smoke/${encodedCamera}/picture?department=general_electric`)).status === 404, '多余前缀被测试桩当作合法接口')
  assert((await fetch(`/api/smoke/${encodedCamera}/unregistered/status?department=general_electric`)).status === 404, '不存在的烟雾路由落入了通用状态桩')
  successes.push('设备抓图地址与后端原生路径一致，错误的额外前缀返回404')
  const initialStatus = await readSmokeStatus(cameraKey, 'general_electric', controller.signal)
  assert(initialStatus.camera_key === cameraKey && initialStatus.alarm_state === 'unknown' && initialStatus.alarm === null, '状态读取未保留原始摄像头标识或未知语义')
  assert(expectSmokeRequest('status', 'GET').init?.signal === controller.signal, '烟雾状态请求未传递取消信号')
  successes.push('烟雾状态使用真实后端路由，摄像头标识正确编码且未知状态不变成正常')
  render('camera_1')
  await until(() => previewElement.querySelector('svg[aria-label="检测区域"]'), '原始图片与 ROI')
  let svg = previewElement.querySelector('svg[aria-label="检测区域"]') as SVGSVGElement
  assert(svg.getAttribute('viewBox') === '0 0 160 120', 'ROI 未使用源画面的宽高比')
  let transform = svg.getScreenCTM()!
  let bounds = previewElement.getBoundingClientRect()
  assert(Math.abs(transform.e - bounds.left - 80) < 1 && Math.abs(transform.f - bounds.top) < 1, '横屏黑边内 ROI 错位')
  successes.push('原始 JPEG 保留功能授权，ROI 与横屏黑边对齐，StrictMode 正常显示')
  assert(connection.connected && !connection.message, '正常 JPEG 预览不应输出常驻说明')
  successes.push('正常 JPEG 预览清空说明文案')
  const previousFirstCameraFrame = previewElement.querySelector('img')!.src
  failFirstCameraFrame = true
  await until(() => previewElement.textContent?.includes('原始画面读取失败'), 'JPEG 短暂失败提示')
  assert(previewElement.querySelector('img')?.src === previousFirstCameraFrame && !connection.connected, '短暂失败时清空了已有画面或错误显示为正常连接')
  failFirstCameraFrame = false
  await until(() => connection.connected && !previewElement.textContent?.includes('原始画面读取失败'), 'JPEG 重试恢复')
  svg = previewElement.querySelector('svg[aria-label="检测区域"]') as SVGSVGElement
  successes.push('短暂取图失败保留当前画面并提示异常，重试恢复后清除提示')
  previewElement.style.width = '300px'; previewElement.style.height = '500px'
  await new Promise((resolve) => requestAnimationFrame(resolve))
  transform = svg.getScreenCTM()!; bounds = previewElement.getBoundingClientRect()
  assert(Math.abs(transform.e - bounds.left) < 1 && Math.abs(transform.f - bounds.top - 137.5) < 1, '竖屏黑边内 ROI 错位')
  successes.push('容器缩放后 ROI 保持对齐')
  render('camera_2')
  await until(() => previewElement.querySelector('svg')?.getAttribute('viewBox') === '0 0 320 180', '切换摄像头')
  svg = previewElement.querySelector('svg') as SVGSVGElement
  assert(svg.getAttribute('viewBox') !== '0 0 160 120', '切换摄像头后显示了旧画面尺寸')
  successes.push('切换摄像头清理旧图与 ROI 尺寸')
  const previousFrame = previewElement.querySelector('img')?.src
  render('camera_5')
  await until(() => {
    const image = previewElement.querySelector('img')
    return image && image.src !== previousFrame && image.naturalWidth > 0
  }, '全画面原始图片')
  assert(!previewElement.querySelector('svg[aria-label="检测区域"]'), '未绘制 ROI 时不应叠加全画面边框或标签')
  successes.push('未绘制 ROI 时显示原始画面，不叠加全画面边框或标签')
  render('camera_3')
  await until(() => previewElement.textContent?.includes('无权访问'), '拒绝预览权限')
  assert(!previewElement.querySelector('img,video,svg'), '权限拒绝后仍显示旧画面')
  const deniedFrames = frameCount('camera_3')
  await pause()
  assert(frameCount('camera_3') === deniedFrames, '权限拒绝后仍继续取图')
  successes.push('权限拒绝后清空画面，不回退取图')
  const NativeSocket = window.WebSocket
  class TestSocket extends EventTarget {
    readyState = 1
    send() {}
    close() { this.readyState = 3 }
  }
  window.WebSocket = TestSocket as unknown as typeof WebSocket
  render('camera_4')
  await until(() => previewElement.querySelector('img')?.naturalWidth && connection.connected, '视频能力未返回前先显示首图')
  assert(!previewElement.querySelector('video'), '能力查询未返回就启动了视频')
  const firstVideoFrame = previewElement.querySelector('img')!.src
  pendingCapabilities.get('camera_4')!()
  await until(() => previewElement.querySelector('video'), 'MSE 原始视频')
  const video = previewElement.querySelector('video')!
  assert(previewElement.querySelector('img'), '等待视频首帧期间丢失了图片画面')
  assert(video.closest('[aria-hidden]')?.getAttribute('aria-hidden') === 'true', '已有首图时仍暴露视频加载提示')
  Object.defineProperty(video, 'videoWidth', { value: 320, configurable: true })
  Object.defineProperty(video, 'videoHeight', { value: 180, configurable: true })
  video.dispatchEvent(new Event('loadedmetadata'))
  await pause(30)
  assert(previewElement.querySelector('svg[aria-label="检测区域"]')?.getAttribute('viewBox') === '0 0 160 120', '首图仍显示时错误使用了视频 ROI 尺寸')
  successes.push('能力查询和视频加载期间先展示持续更新的首图，不空等视频')
  holdVideoFrame = true
  await until(() => finishVideoFrame !== null, '视频接管前的在途 JPEG')
  const framesBeforePlaying = frameCount('camera_4')
  video.dispatchEvent(new Event('playing'))
  await until(() => connection.connected && !previewElement.querySelector('img,[role="status"]'), '正常 MSE 接管图片')
  assert(!connection.message, '正常 MSE 预览不应输出常驻说明')
  assert(previewElement.querySelector('svg[aria-label="检测区域"]')?.getAttribute('viewBox') === '0 0 320 180', '视频接管后 ROI 尺寸没有切换')
  await until(() => videoFrameSignal?.aborted, '停止在途 JPEG')
  holdVideoFrame = false
  finishVideoFrame!()
  await pause(600)
  assert(frameCount('camera_4') === framesBeforePlaying && !previewElement.querySelector('img'), '视频播放期间继续取图或晚到 JPEG 覆盖了视频')
  assert(previewElement.querySelector('video') === video, '视频接管时重新创建了播放器')
  successes.push('真实播放后停止 JPEG，取消在途请求，晚到首图不覆盖视频，ROI 按显示源切换')
  video.dispatchEvent(new Event('error'))
  await until(() => previewElement.querySelector('img')?.naturalWidth && connection.connected, 'MSE 重连期间恢复原始图片')
  assert(previewElement.querySelector('img')!.src !== firstVideoFrame, '重连时展示了很早之前的首图')
  successes.push('MSE 重连期间获取新画面，不复用旧首图')
  for (const camera of ['camera_6', 'camera_7']) {
    render(camera)
    await until(() => pendingCapabilities.has(camera), `${camera} 新会话已开始能力查询`)
    await until(() => previewElement.textContent?.includes('无权访问'), `${camera} 首图鉴权拒绝`)
    const count = frameCount(camera)
    pendingCapabilities.get(camera)!()
    await pause()
    assert(!previewElement.querySelector('img,video,svg') && frameCount(camera) === count, '晚到的能力响应恢复了被拒绝的画面')
  }
  assert(unauthorizedEvents > 0, '401 未通知登录状态失效')
  successes.push('首图 401/403 先返回时停止预览，晚到的能力查询不能恢复画面')
  const disabledFrames = frameCount('camera_4')
  render('camera_4', false)
  await until(() => previewElement.textContent?.includes('摄像头已停用'), '停用摄像头')
  await pause()
  assert(!previewElement.querySelector('img,video') && frameCount('camera_4') === disabledFrames, '停用后仍显示或读取画面')
  render('camera_4')
  await until(() => previewElement.querySelector('img')?.naturalWidth && connection.connected, '重新启用时获取新首图')
  const beforeHidden = previewElement.querySelector('img')!.src
  Object.defineProperty(document, 'hidden', { value: true, configurable: true })
  Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
  await until(() => !previewElement.querySelector('img,video'), '隐藏页面清理画面')
  const hiddenFrames = frameCount('camera_4')
  await pause()
  assert(frameCount('camera_4') === hiddenFrames, '隐藏页面仍继续取图')
  Reflect.deleteProperty(document, 'hidden'); Reflect.deleteProperty(document, 'visibilityState')
  document.dispatchEvent(new Event('visibilitychange'))
  await until(() => previewElement.querySelector('img')?.naturalWidth && connection.connected, '恢复页面时获取新首图')
  assert(previewElement.querySelector('img')!.src !== beforeHidden, '恢复页面显示了旧首图')
  successes.push('停用或隐藏页面停止取图并清空画面，重新启用或恢复时读取新图')
  render('camera_3')
  await until(() => previewElement.textContent?.includes('无权访问'), '关闭 MSE 测试会话')
  window.WebSocket = NativeSocket
  statusRoot.render(<Status />)
  await until(() => statusElement.textContent?.includes('92.0%'), '检测状态卡片')
  assert(statusElement.textContent?.includes('手机轨迹 1') && statusElement.textContent.includes('连续命中 4 次'), '卡片缺少采样明细')
  await until(() => statusElement.textContent?.includes('检测结果已过期'), '检测结果到期')
  assert(!statusElement.textContent?.includes('手机轨迹 1'), '网络挂起时仍显示过期检测明细')
  successes.push('卡片显示真实结果明细，网络挂起时独立过期')
  const regions = previewRegions('tailgating', { roi_pos: roi, line_points: [[0.5, 0], [0.5, 1]], direction: 0 })
  assert(regions[1].directions?.length === 2, '双向过闸判定线缺少方向')
  const left = regionDirection([[0.5, 0], [0.5, 1]], 640, 360, 1)!
  assert(left.x2 < left.x1, '判定线方向与后端叉积方向不一致')
  assert(previewRegions('detect_phone', { roi_pos: [[2, 0], [0, 1], [1, 1]] }).length === 0, '无效 ROI 不应显示')
  for (const feature of ['detect_phone', 'guard_behavior']) {
    const field = feature === 'guard_behavior' ? 'vehicle_roi_pos' : 'roi_pos'
    for (const value of [null, {}, { [field]: [] }, { [field]: null }]) {
      assert(previewRegions(feature, value).length === 0, `${feature} 未配置 ROI 时不应生成区域`)
    }
    const configured = previewRegions(feature, { [field]: roi })
    assert(configured.length === 1 && configured[0].points === roi, `${feature} 已绘制 ROI 应正常显示`)
  }
  for (const feature of ['blocks', 'tailgating']) {
    const lineOnly = previewRegions(feature, { roi_pos: [], line_points: [[0.5, 0], [0.5, 1]], direction: 0, alarm_side: -1 })
    assert(lineOnly.length === 1 && lineOnly[0].line, `${feature} 未绘制 ROI 时仍应显示判定线`)
    assert(lineOnly[0].directions?.length === (feature === 'tailgating' ? 2 : 1), `${feature} 判定线方向缺失`)
  }
  successes.push('过闸双向与警戒线方向正确，无效区域不显示')
  renderLogistics(11)
  await until(() => previewElement.querySelector('img')?.naturalWidth && previewElement.querySelector('svg[aria-label="检测区域"] polygon'), '物流通道原始画面及专用 ROI')
  assert(!requests.some((url) => url.pathname.startsWith(`/api/features/${logisticsFeature}/configs/`)), '物流预览仍请求普通功能配置接口')
  assert(!previewElement.textContent?.includes('检测区域读取失败'), '物流通道 ROI 读取失败')
  successes.push('真实物流监控视图从通道成员 ROI 接口读取区域，不请求普通功能配置')
  const reads = logisticsRoiReads
  await updateLogisticsCameraRoi(logisticsFeature, 11, 1, { roi_pos: [] })
  await until(() => logisticsRoiReads > reads && !previewElement.querySelector('svg[aria-label="检测区域"]'), '保存空 ROI 后立即刷新')
  assert(previewElement.querySelector('img'), '清空 ROI 后丢失了物流画面')
  await updateLogisticsCameraRoi(logisticsFeature, 11, 1, { roi_pos: roi as [number, number][] })
  await until(() => previewElement.querySelector('svg[aria-label="检测区域"] polygon'), '保存 ROI 后重新显示区域')
  successes.push('物流 ROI 保存后即时刷新，空 ROI 不叠加区域且持续显示画面')
  failLogisticsRoi = true
  invalidateLogisticsChannelQueries(logisticsFeature, 11)
  await until(() => previewElement.textContent?.includes('检测区域读取失败'), '专用 ROI 接口失败提示')
  assert(!previewElement.querySelector('svg[aria-label="检测区域"]') && previewElement.querySelector('img'), 'ROI 读取失败后仍显示旧区域或丢失画面')
  failLogisticsRoi = false
  invalidateLogisticsChannelQueries(logisticsFeature, 11)
  await until(() => previewElement.querySelector('svg[aria-label="检测区域"] polygon') && !previewElement.textContent?.includes('检测区域读取失败'), '专用 ROI 接口恢复')
  successes.push('专用 ROI 接口真实失败时保留错误提示，恢复后清除错误并重画区域')
  holdLogisticsRoi = true
  invalidateLogisticsChannelQueries(logisticsFeature, 11)
  await until(() => finishLogisticsRoi !== null, '旧通道 ROI 挂起请求')
  logisticsRois.set(12, [[0.2, 0.2], [0.8, 0.2], [0.5, 0.8]])
  renderLogistics(12)
  await until(() => previewElement.querySelector('svg[aria-label="检测区域"] polygon')?.getAttribute('points') === '32,24 128,24 80,96', '切换通道使用新 ROI')
  assert(logisticsRoiSignal?.aborted, '切换通道未取消旧 ROI 请求')
  finishLogisticsRoi!()
  await pause()
  assert(previewElement.querySelector('svg[aria-label="检测区域"] polygon')?.getAttribute('points') === '32,24 128,24 80,96', '晚到的旧通道 ROI 覆盖了当前通道')
  assert(!requests.some((url) => url.pathname.startsWith(`/api/features/${logisticsFeature}/configs/`)), '物流刷新或切换时回退到普通配置接口')
  successes.push('切换通道取消旧 ROI 请求，同一摄像头晚到的旧通道响应不会覆盖新区域')
  statusRoot.render(<SmokeStatusHarness cameraKey="smoke_1" />)
  await until(() => statusElement.textContent?.includes('"alarm_state":"unknown"'), '烟雾连接成功后的未知状态')
  assert(statusElement.textContent?.includes('"alarm":null'), '尚未收到设备事件时被当成未报警')
  successes.push('烟雾连接成功但未收到设备事件时仍为未知状态，状态请求携带当前事业部')
  smokeMode = 'active'
  await until(() => statusElement.textContent?.includes('"alarm_state":"active"'), '设备烟雾活动报警')
  smokeMode = 'hold'
  await until(() => statusElement.textContent?.includes('"alarm_state":"unknown"'), '烟雾状态独立到期')
  assert(statusElement.textContent?.includes('"alarm":null'), '过期的设备报警仍当作当前结果')
  await until(() => finishSmokeStatus !== null, '烟雾状态挂起请求')
  successes.push('设备烟雾状态按服务端有效期过期，挂起请求不能让旧报警一直保持活动')
  smokeMode = 'inactive'
  statusRoot.render(<SmokeStatusHarness cameraKey="smoke_2" />)
  await until(() => statusElement.textContent?.includes('"camera_key":"smoke_2"') && statusElement.textContent.includes('"alarm_state":"inactive"'), '切换后设备上报解除')
  assert(smokeStatusSignal?.aborted, '切换摄像头后未取消旧设备状态请求')
  finishSmokeStatus!()
  await pause(100)
  assert(statusElement.textContent?.includes('"camera_key":"smoke_2"') && !statusElement.textContent.includes('"alarm_state":"active"'), '旧设备晚到的报警覆盖了当前摄像头')
  successes.push('摄像头切换取消旧状态读取，晚到的设备报警不能覆盖新摄像头解除状态')
  root.unmount(); statusRoot.unmount()
  window.removeEventListener('aicv:unauthorized', onUnauthorized)
  resultElement.textContent = `通过 ${successes.length} 项\n${successes.join('\n')}`
  resultElement.dataset.result = 'passed'
}
run().catch((error) => {
  resultElement.textContent = `${String(error.stack || error)}\n已通过：${successes.join('；')}`
  resultElement.dataset.result = 'failed'
})
