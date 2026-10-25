import { createVideoPreviewPerformanceRecorder } from './AiVisionVideoPreview.performance'
import type { VideoPreviewPerformanceReport, VideoPreviewState } from './AiVisionVideoPreview.performance'

const VIDEO_CODECS = ['avc1.640029', 'avc1.64002A', 'avc1.640033', 'hvc1.1.6.L153.B0']
export const MSE_MAX_PENDING_BYTES = 8 * 1024 * 1024
const MSE_KEEP_SECONDS = 5
const STARTUP_TIMEOUT_MS = 9000
const RECONNECT_DELAY_MS = 500

export function supportedPreviewCodecs(isTypeSupported: (mime: string) => boolean): string {
  return VIDEO_CODECS.filter((codec) => isTypeSupported(`video/mp4; codecs="${codec}"`)).join(',')
}

export function previewWebSocketUrl(path: string, origin: string): string {
  const target = new URL(path, origin)
  if (target.protocol === 'ws:') target.protocol = 'http:'
  if (target.protocol === 'wss:') target.protocol = 'https:'
  if (target.origin !== new URL(origin).origin || target.username || target.password || target.hash) {
    throw new Error('视频连接地址无效')
  }
  target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:'
  return target.href
}

export function parseMseControlMessage(text: string): { type: 'mse' | 'error'; value: string } {
  if (text.length > 1024) throw new Error('视频协商响应无效')
  const message: unknown = JSON.parse(text)
  if (!message || typeof message !== 'object' || !('type' in message) || !('value' in message)
    || (message.type !== 'mse' && message.type !== 'error') || typeof message.value !== 'string') {
    throw new Error('视频协商响应无效')
  }
  if (message.type === 'mse' && !/^video\/mp4;\s*codecs="(?:avc1|hvc1|hev1)[\w., -]+"$/i.test(message.value)) {
    throw new Error('视频编码格式不支持')
  }
  return { type: message.type, value: message.value }
}

export function createMseAppendQueue(options: {
  buffer: SourceBuffer
  video: HTMLVideoElement
  onFailure: () => void
  maxPendingBytes?: number
}) {
  const { buffer, video } = options
  const pending: ArrayBuffer[] = []
  let queuedBytes = 0
  let inFlightBytes = 0
  let disposed = false
  const fail = () => { if (!disposed) { disposed = true; options.onFailure() } }
  const pump = () => {
    if (disposed || buffer.updating) return
    try {
      const ranges = buffer.buffered
      if (ranges.length) {
        const start = ranges.start(ranges.length - 1)
        const end = ranges.end(ranges.length - 1)
        if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) { fail(); return }
        // 只在落后、进入时间轴空洞或时间戳回退时跳到直播边缘，保留低帧率视频的正常播放节奏。
        if (video.currentTime < start || end - video.currentTime > 1.5 || video.currentTime > end + .5) {
          video.currentTime = Math.max(start, end - .15)
        }
        video.playbackRate = end - video.currentTime > .6 ? 1.03 : 1
        const trimBefore = Math.min(end - MSE_KEEP_SECONDS, video.currentTime - .5)
        if (trimBefore > ranges.start(0) + 1) {
          buffer.remove(0, trimBefore)
          return
        }
      }
      const chunk = pending.shift()
      if (chunk) {
        queuedBytes -= chunk.byteLength
        inFlightBytes = chunk.byteLength
        buffer.appendBuffer(chunk)
      }
    } catch { fail() }
  }
  const update = () => { inFlightBytes = 0; pump() }
  buffer.addEventListener('updateend', update)
  buffer.addEventListener('error', fail)
  return {
    append(data: ArrayBuffer) {
      if (disposed) return
      // fMP4 不能随意丢片段；字节队列溢出时由上层重建协商和初始化片段。
      if (queuedBytes + inFlightBytes + data.byteLength > (options.maxPendingBytes ?? MSE_MAX_PENDING_BYTES)) {
        fail()
        return
      }
      pending.push(data)
      queuedBytes += data.byteLength
      pump()
    },
    dispose() {
      disposed = true
      pending.length = 0
      queuedBytes = inFlightBytes = 0
      buffer.removeEventListener('updateend', update)
      buffer.removeEventListener('error', fail)
    },
  }
}

export function createMsePreviewSession(options: {
  video: HTMLVideoElement
  url: string
  cameraKey: string
  feature: string
  department: string
  visible?: boolean
  onState: (state: VideoPreviewState) => void
  onFallback?: () => void
  onAccessDenied?: () => void
  onReport: (report: VideoPreviewPerformanceReport) => void
  environment?: {
    origin?: string
    createMediaSource?: () => MediaSource
    isTypeSupported?: (mime: string) => boolean
    createWebSocket?: (url: string) => WebSocket
    createObjectURL?: (source: MediaSource) => string
    revokeObjectURL?: (url: string) => void
    now?: () => number
    setTimeoutFn?: typeof setTimeout
    clearTimeoutFn?: typeof clearTimeout
  }
}) {
  const { video } = options
  const env = options.environment ?? {}
  const now = env.now ?? (() => performance.now())
  const schedule = env.setTimeoutFn ?? setTimeout
  const unschedule = env.clearTimeoutFn ?? clearTimeout
  const supported = env.isTypeSupported ?? ((mime) => typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(mime))
  let state: VideoPreviewState = 'connecting'
  let visible = options.visible ?? true
  let disposed = false
  let terminal = false
  let generation = 0
  let deadline = 0
  let lastProgress = 0
  let lastTime = 0
  let reconnectAt: number | null = null
  let reconnects = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let cleanupAttempt: (() => void) | undefined
  let recorder: ReturnType<typeof createVideoPreviewPerformanceRecorder> | undefined
  const transition = (next: VideoPreviewState) => {
    state = next
    if (!disposed) options.onState(next)
  }
  const clearVideo = () => {
    video.pause()
    video.removeAttribute('src')
    video.srcObject = null
    video.playbackRate = 1
    video.load()
  }
  const stopAttempt = () => { generation++; cleanupAttempt?.(); cleanupAttempt = undefined }
  const finish = (denied = false) => {
    if (disposed || terminal) return
    terminal = true
    if (timer !== undefined) unschedule(timer)
    stopAttempt()
    transition(denied ? 'access-denied' : 'fallback')
    recorder?.sample(state, true)
    if (denied) options.onAccessDenied?.()
    else options.onFallback?.()
  }
  const retry = () => {
    if (disposed || terminal || !visible) return
    if (state === 'playing') deadline = now() + STARTUP_TIMEOUT_MS
    stopAttempt()
    if (++reconnects > 2 || now() >= deadline) { finish(); return }
    transition('reconnecting')
    reconnectAt = now() + RECONNECT_DELAY_MS
  }

  const connect = () => {
    if (disposed || terminal || !visible) return
    reconnectAt = null
    const current = ++generation
    let socket: WebSocket | undefined
    let media: MediaSource | undefined
    let queue: ReturnType<typeof createMseAppendQueue> | undefined
    let objectUrl = ''
    let handshaken = false
    let protocolFailed = false
    let released = false
    const removers: (() => void)[] = []
    const active = () => !disposed && !terminal && visible && generation === current
    const listen = (target: EventTarget, name: string, handler: EventListener) => {
      target.addEventListener(name, handler)
      removers.push(() => target.removeEventListener(name, handler))
    }
    cleanupAttempt = () => {
      if (released) return
      released = true
      for (const remove of removers) remove()
      queue?.dispose()
      socket?.close()
      if (media?.readyState === 'open') {
        try {
          for (const buffer of Array.from(media.sourceBuffers)) if (buffer.updating) buffer.abort()
          media.endOfStream()
        } catch { /* 关闭期间浏览器可能已分离媒体源，清理仍需继续。 */ }
      }
      clearVideo()
      if (objectUrl) (env.revokeObjectURL ?? URL.revokeObjectURL)(objectUrl)
    }
    try {
      const codecs = supportedPreviewCodecs(supported)
      if (!codecs) { finish(); return }
      const url = previewWebSocketUrl(options.url, env.origin ?? location.origin)
      media = env.createMediaSource?.() ?? new MediaSource()
      socket = env.createWebSocket?.(url) ?? new WebSocket(url)
      socket.binaryType = 'arraybuffer'
      const negotiate = () => {
        if (!active() || handshaken || media?.readyState !== 'open' || socket?.readyState !== 1) return
        handshaken = true
        try { socket.send(JSON.stringify({ type: 'mse', value: codecs })) }
        catch { retry() }
      }
      const protocolFailure = () => {
        if (!active() || protocolFailed) return
        protocolFailed = true
        deadline = now() + STARTUP_TIMEOUT_MS
        // 服务端可能先发 error 再以 1008 关闭；必须等待关闭码，避免权限失效时转入 JPEG。
        queue?.dispose()
        clearVideo()
        transition('reconnecting')
      }
      listen(media, 'sourceopen', negotiate)
      listen(socket, 'open', negotiate)
      listen(socket, 'error', protocolFailure)
      listen(socket, 'close', ((event: CloseEvent) => {
        if (!active()) return
        if (event.code === 1008) finish(true)
        else if (protocolFailed) finish()
        else retry()
      }) as EventListener)
      listen(socket, 'message', ((event: MessageEvent) => {
        if (!active() || protocolFailed) return
        try {
          if (typeof event.data === 'string') {
            const message = parseMseControlMessage(event.data)
            if (message.type === 'error') { protocolFailure(); return }
            if (!handshaken || queue || !supported(message.value)) { protocolFailure(); return }
            const buffer = media!.addSourceBuffer(message.value)
            buffer.mode = 'segments'
            queue = createMseAppendQueue({ buffer, video, onFailure: retry })
          } else {
            if (!queue || !(event.data instanceof ArrayBuffer)) { protocolFailure(); return }
            recorder?.received(event.data.byteLength)
            queue.append(event.data)
          }
        } catch { protocolFailure() }
      }) as EventListener)
      listen(video, 'playing', () => {
        if (!active() || protocolFailed) return
        lastProgress = now()
        lastTime = video.currentTime
        // 只有浏览器进入播放状态，才算视频链路建立，收到字节不代表成功。
        transition('playing')
      })
      listen(video, 'error', () => { if (active() && !protocolFailed) retry() })
      objectUrl = (env.createObjectURL ?? URL.createObjectURL)(media)
      video.src = objectUrl
      video.play().catch(() => { if (active() && !protocolFailed) finish() })
    } catch { finish() }
  }
  const poll = () => {
    if (disposed || terminal || !visible) return
    const at = now()
    recorder?.sample(state)
    if (state === 'playing') {
      if (Math.abs(video.currentTime - lastTime) > .001) {
        lastTime = video.currentTime
        lastProgress = at
        reconnects = 0
      }
      if (at - lastProgress >= STARTUP_TIMEOUT_MS) {
        deadline = at + STARTUP_TIMEOUT_MS
        retry()
      }
    } else if (at >= deadline) { finish(); return }
    if (reconnectAt !== null && at >= reconnectAt) connect()
    if (!disposed && !terminal && visible) timer = schedule(poll, 500)
  }
  const start = () => {
    deadline = now() + STARTUP_TIMEOUT_MS
    reconnects = 0
    recorder = createVideoPreviewPerformanceRecorder({ ...options, now })
    transition('connecting')
    connect()
    if (!terminal) timer = schedule(poll, 500)
  }
  if (visible) start()
  else transition('paused')
  return {
    setVisible(next: boolean) {
      if (disposed || terminal || next === visible) return
      visible = next
      if (timer !== undefined) unschedule(timer)
      stopAttempt()
      recorder = undefined
      if (next) start()
      else transition('paused')
    },
    dispose() {
      if (disposed) return
      disposed = true
      if (timer !== undefined) unschedule(timer)
      stopAttempt()
      recorder = undefined
    },
  }
}
