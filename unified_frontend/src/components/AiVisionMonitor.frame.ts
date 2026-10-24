import { aiVisionFrameUrl } from '../lib/aivision'

export const PREVIEW_MAX_WIDTH = 960
export const PREVIEW_QUALITY = 72
export const FRAME_REQUEST_TIMEOUT_MS = 5000
const DEFAULT_PREVIEW_FPS = 5
const MAX_PREVIEW_FPS = 10

export function previewRefreshMs(cameraFps?: number): number {
  const fps = cameraFps && Number.isFinite(cameraFps) && cameraFps > 0 ? cameraFps : DEFAULT_PREVIEW_FPS
  return Math.ceil(1000 / Math.min(MAX_PREVIEW_FPS, fps))
}

type ScheduleTimeout = (callback: () => void, delay: number) => ReturnType<typeof setTimeout>

function decodePreviewImage(src: string, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    const cleanup = () => signal.removeEventListener('abort', abort)
    const abort = () => {
      cleanup()
      image.src = ''
      reject(signal.reason ?? new DOMException('画面请求已取消', 'AbortError'))
    }
    if (signal.aborted) {
      abort()
      return
    }
    signal.addEventListener('abort', abort, { once: true })
    image.src = src
    image.decode().then(() => { cleanup(); resolve() }, (error) => { cleanup(); reject(error) })
  })
}

export function createPreviewFrameBuffer(options: {
  createUrl?: (blob: Blob) => string
  revokeUrl?: (url: string) => void
  decode?: (src: string, signal: AbortSignal) => Promise<void>
} = {}) {
  const createUrl = options.createUrl ?? ((blob: Blob) => URL.createObjectURL(blob))
  const revokeUrl = options.revokeUrl ?? ((src: string) => URL.revokeObjectURL(src))
  const decode = options.decode ?? decodePreviewImage
  const urls = new Map<string, number>()
  let sequence = 0
  let latestReady = ''
  let disposed = false
  const release = (src: string) => {
    if (urls.delete(src)) revokeUrl(src)
  }
  const clear = () => {
    latestReady = ''
    for (const src of urls.keys()) release(src)
  }
  return {
    async prepare(blob: Blob, signal: AbortSignal): Promise<string> {
      if (disposed || signal.aborted) throw new DOMException('画面请求已取消', 'AbortError')
      const src = createUrl(blob)
      urls.set(src, ++sequence)
      try {
        await decode(src, signal)
        if (disposed || signal.aborted || !urls.has(src)) throw new DOMException('画面请求已取消', 'AbortError')
        latestReady = src
        return src
      } catch (error) {
        release(src)
        throw error
      }
    },
    displayed(src: string) {
      const order = urls.get(src)
      if (order === undefined || src !== latestReady) return
      // 页面确认新图已显示后再释放旧图，尚在解码的下一帧继续保留。
      for (const [url, index] of urls) if (index < order) release(url)
    },
    clear,
    dispose() { disposed = true; clear() },
  }
}

export function buildAiVisionPreviewFrameUrl(cameraKey: string, feature: string, nonce: number) {
  return aiVisionFrameUrl(cameraKey, feature, nonce, {
    maxWidth: PREVIEW_MAX_WIDTH,
    quality: PREVIEW_QUALITY,
  })
}

export function scheduleFrameRequestAbort(
  controller: AbortController,
  timeoutMs = FRAME_REQUEST_TIMEOUT_MS,
  schedule: ScheduleTimeout = setTimeout,
) {
  return schedule(() => controller.abort(), timeoutMs)
}
