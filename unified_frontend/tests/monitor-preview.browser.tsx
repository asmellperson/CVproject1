// 启动 Vite 后访问 /tests/monitor-preview.browser.html，可由无头 Chromium 执行。
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { CameraLivePreview } from '../src/components/monitor/CameraLivePreview'
import { CurrentDetectionCard } from '../src/components/monitor/CurrentDetectionCard'
import { useDetectionStatus } from '../src/components/monitor/useDetectionStatus'
import { previewRegions, regionDirection } from '../src/components/monitor/previewRegions'
import '../src/index.css'

const previewElement = document.getElementById('preview')!
const statusElement = document.getElementById('status')!
const resultElement = document.getElementById('result')!
const root = createRoot(previewElement)
const statusRoot = createRoot(statusElement)
const requests: URL[] = []
const successes: string[] = []
let statusRequests = 0
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const roi = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
const hold = (signal?: AbortSignal | null) => new Promise<Response>((_, reject) => signal?.addEventListener('abort', () => reject(new DOMException('已取消', 'AbortError')), { once: true }))
window.fetch = async (input, init) => {
  const url = new URL(String(input), location.origin)
  requests.push(url)
  if (url.pathname.endsWith('/preview')) return url.pathname.includes('camera_3') ? json({}, 403)
    : url.pathname.includes('camera_4') ? json({ enabled: true, mode: 'mse', url: '/ws/cameras/camera_4/preview?feature=detect_phone', raw: true })
    : json({ enabled: false, mode: 'jpeg', url: null, raw: true })
  if (url.pathname.includes('/configs/')) return json({ config: { value: { roi_pos: roi } } })
  if (url.pathname.endsWith('/frame.jpg')) {
    if (url.searchParams.get('raw') !== 'true' || url.searchParams.get('feature') !== 'detect_phone') throw new Error('预览未保留功能授权或请求了标注图片')
    const width = url.pathname.includes('camera_2') ? 320 : 160
    const height = url.pathname.includes('camera_2') ? 180 : 120
    return new Response(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#284863"/></svg>`, { headers: { 'Content-Type': 'image/svg+xml' } })
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
const render = (cameraKey: string) => root.render(<StrictMode><CameraLivePreview cameraKey={cameraKey} feature="detect_phone" department="general_electric" /></StrictMode>)
export function Status() {
  const result = useDetectionStatus('camera_1', 'detect_phone')
  return <CurrentDetectionCard feature="detect_phone" status={result?.status} error={result?.error} />
}

async function run() {
  render('camera_1')
  await until(() => previewElement.querySelector('svg[aria-label="检测区域"]'), '原始图片与 ROI')
  let svg = previewElement.querySelector('svg[aria-label="检测区域"]') as SVGSVGElement
  assert(svg.getAttribute('viewBox') === '0 0 160 120', 'ROI 未使用源画面的宽高比')
  let transform = svg.getScreenCTM()!
  let bounds = previewElement.getBoundingClientRect()
  assert(Math.abs(transform.e - bounds.left - 80) < 1 && Math.abs(transform.f - bounds.top) < 1, '横屏黑边内 ROI 错位')
  successes.push('原始 JPEG 保留功能授权，ROI 与横屏黑边对齐，StrictMode 正常显示')
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
  render('camera_3')
  await until(() => previewElement.textContent?.includes('无权访问'), '拒绝预览权限')
  assert(!previewElement.querySelector('img,video,svg'), '权限拒绝后仍显示旧画面')
  assert(!requests.some((url) => url.pathname.includes('camera_3') && url.pathname.endsWith('/frame.jpg')), '权限拒绝后仍回退取图')
  successes.push('权限拒绝后清空画面，不回退取图')
  const NativeSocket = window.WebSocket
  class TestSocket extends EventTarget {
    readyState = 1
    send() {}
    close() { this.readyState = 3 }
  }
  window.WebSocket = TestSocket as unknown as typeof WebSocket
  render('camera_4')
  await until(() => previewElement.querySelector('video'), 'MSE 原始视频')
  await new Promise((resolve) => setTimeout(resolve, 200))
  assert(!requests.some((url) => url.pathname.includes('camera_4') && url.pathname.endsWith('/frame.jpg')), 'MSE 播放期间仍并行拉 JPEG')
  successes.push('MSE 视频与 JPEG 取图互斥')
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
  assert(previewRegions('detect_phone', { roi_pos: [] })[0].label.includes('全画面'), '空 ROI 应标示全画面')
  successes.push('过闸双向与警戒线方向正确，无效区域不显示')
  root.unmount(); statusRoot.unmount()
  resultElement.textContent = `通过 ${successes.length} 项\n${successes.join('\n')}`
  resultElement.dataset.result = 'passed'
}
run().catch((error) => { resultElement.textContent = String(error.stack || error); resultElement.dataset.result = 'failed' })
