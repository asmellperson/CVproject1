export type CameraPreviewStream = {
  enabled: boolean
  mode: 'mse' | 'jpeg'
  url: string | null
  raw: true
}

const PREVIEW_CAPABILITY_TIMEOUT_MS = 3000

export class PreviewStreamAccessError extends Error {
  readonly status: 401 | 403

  constructor(status: 401 | 403) {
    super(status === 401 ? '登录状态已失效' : '当前账号无权查看此摄像头')
    this.name = 'PreviewStreamAccessError'
    this.status = status
  }
}

function validatePreviewStream(payload: unknown, cameraKey: string, feature: string): CameraPreviewStream {
  if (!payload || typeof payload !== 'object' || !('enabled' in payload) || !('mode' in payload)
    || !('url' in payload) || !('raw' in payload) || payload.raw !== true) {
    throw new Error('视频能力响应无效')
  }
  if (payload.enabled === false && payload.mode === 'jpeg' && payload.url === null) {
    return { enabled: false, mode: 'jpeg', url: null, raw: true }
  }
  if (payload.enabled !== true || payload.mode !== 'mse' || typeof payload.url !== 'string') {
    throw new Error('视频能力响应无效')
  }
  const cameraId = /^(?:camera_)?([1-9][0-9]*)$/.exec(cameraKey)?.[1]
  const origin = window.location.origin
  const url = new URL(payload.url, origin)
  // 能力查询不能把浏览器引向其他摄像头、外部媒体服务或含凭据的地址。
  if (!cameraId || url.origin !== origin || url.username || url.password || url.hash
    || url.pathname !== `/ws/cameras/camera_${cameraId}/preview`
    || [...url.searchParams.keys()].length !== 1 || url.searchParams.get('feature') !== feature) {
    throw new Error('视频连接地址无效')
  }
  return { enabled: true, mode: 'mse', url: `${url.pathname}${url.search}`, raw: true }
}

export async function getCameraPreviewStream(
  cameraKey: string,
  feature: string,
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<CameraPreviewStream> {
  const { signal, timeoutMs = PREVIEW_CAPABILITY_TIMEOUT_MS } = options
  if (signal?.aborted) throw signal.reason ?? new DOMException('视频能力查询已取消', 'AbortError')
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('视频能力查询超时配置无效')
  const controller = new AbortController()
  const cancel = () => controller.abort(signal?.reason ?? new DOMException('视频能力查询已取消', 'AbortError'))
  signal?.addEventListener('abort', cancel, { once: true })
  const timer = setTimeout(() => controller.abort(new DOMException('视频能力查询超时', 'TimeoutError')), timeoutMs)
  let rejectAbort: () => void = () => undefined
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = () => reject(controller.signal.reason)
    controller.signal.addEventListener('abort', rejectAbort, { once: true })
  })
  try {
    const request = (async () => {
      const query = new URLSearchParams({ feature })
      const response = await fetch(`/api/cameras/${encodeURIComponent(cameraKey)}/preview?${query}`, {
        credentials: 'include', cache: 'no-store', signal: controller.signal,
      })
      controller.signal.throwIfAborted()
      if (response.status === 401 || response.status === 403) {
        if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
        throw new PreviewStreamAccessError(response.status)
      }
      if (!response.ok) throw new Error('视频能力查询失败')
      const payload: unknown = await response.json()
      controller.signal.throwIfAborted()
      return validatePreviewStream(payload, cameraKey, feature)
    })()
    // 即使代理或测试替身未及时响应 abort，能力探测也必须在上限内结束。
    return await Promise.race([request, aborted])
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
    controller.signal.removeEventListener('abort', rejectAbort)
  }
}
