const REPORT_INTERVAL_MS = 5000

type Duration = { total: number; count: number }
type Capture = { sequence: number; updatedAt: number; observedAt: number }
type FrameSample = {
  startedAt: number
  headersReceivedAt: number
  bodyReceivedAt: number
  decodedAt: number
  bytes: number
  headers: Pick<Headers, 'get'>
  src: string
}

export type PreviewPerformanceReport = {
  cameraKey: string
  feature: string
  department: string
  sampledAt: string
  windowMs: number
  targetFps: number
  readyFps: number
  imageLoadFps: number
  capturePublishedFpsEstimate: number | null
  completedRequests: number
  failedRequests: number
  averageImageKiB: number | null
  averageMs: Record<
    'requestToHeaders' | 'downloadBody' | 'imageDecode' | 'requestToReady' | 'readyToImageLoad'
    | 'frameLookupAndOverlay' | 'jpegEncode' | 'frameHandler' | 'outsideFrameHandler'
    | 'authentication' | 'cameraAccess' | 'serverRequest' | 'serverDispatch' | 'outsideServer'
    | 'captureAge', number | null
  >
}

export type PreviewPerformanceGroupReport = {
  scope: 'guard_behavior'
  siteId: number | null
  department: string
  sampledAt: string
  cameras: Record<string, PreviewPerformanceReport | null>
}

declare global {
  interface Window {
    aivisionPreviewDiagnostics?: PreviewPerformanceReport | PreviewPerformanceGroupReport
  }
}

export function createPreviewPerformanceGroup(options: {
  siteId: number | null
  department: string
  onReport: (report: PreviewPerformanceGroupReport) => void
}) {
  const cameras = new Map<string, PreviewPerformanceReport | null>()
  let disposed = false
  const publish = () => {
    if (disposed) return
    options.onReport({
      scope: 'guard_behavior', siteId: options.siteId, department: options.department,
      sampledAt: new Date().toISOString(), cameras: Object.fromEntries(cameras),
    })
  }
  return {
    publish,
    setCameras(keys: string[]) {
      if (disposed) return
      const current = new Set(keys)
      let changed = false
      for (const key of cameras.keys()) {
        if (!current.has(key)) { cameras.delete(key); changed = true }
      }
      for (const key of current) {
        if (!cameras.has(key)) { cameras.set(key, null); changed = true }
      }
      if (changed) publish()
    },
    update(report: PreviewPerformanceReport) {
      // 仅接收当前保安室成员，已移除或其他事业部的迟到结果不能进入报告。
      if (disposed || report.department !== options.department || !cameras.has(report.cameraKey)) return
      cameras.set(report.cameraKey, report)
      publish()
    },
    dispose() { disposed = true; cameras.clear() },
  }
}

function duration(): Duration { return { total: 0, count: 0 } }

function add(value: Duration, milliseconds: number) {
  if (Number.isFinite(milliseconds) && milliseconds >= 0) {
    value.total += milliseconds
    value.count++
  }
}

function rounded(value: number) { return Math.round(value * 100) / 100 }

function readNumber(value: string | null): number | null {
  if (value === null || value.trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

function captureRate(first: Capture | null, last: Capture | null): number | null {
  if (!first || !last || last.observedAt <= first.observedAt) return null
  const progress = last.sequence - first.sequence
  if (progress === 0) return 0
  // 使用两次服务端读帧时间之差，避免网络排队和浏览器调度污染采集速率估计。
  const elapsed = last.updatedAt - first.updatedAt
  return elapsed > 0 ? rounded(progress / elapsed) : null
}

export function createPreviewPerformanceRecorder(options: {
  cameraKey: string
  feature: string
  department: string
  refreshMs: number
  onReport: (report: PreviewPerformanceReport) => void
  now?: () => number
}) {
  const now = options.now ?? (() => performance.now())
  let startedAt = now()
  let completed = 0
  let failed = 0
  let loaded = 0
  let bytes = 0
  let disposed = false
  let pending: { src: string; decodedAt: number } | null = null
  let captureFirst: Capture | null = null
  let captureLast: Capture | null = null
  const stages = {
    requestToHeaders: duration(), downloadBody: duration(), imageDecode: duration(),
    requestToReady: duration(), readyToImageLoad: duration(), frameLookupAndOverlay: duration(),
    jpegEncode: duration(), frameHandler: duration(), outsideFrameHandler: duration(), captureAge: duration(),
    authentication: duration(), cameraAccess: duration(), serverRequest: duration(),
    serverDispatch: duration(), outsideServer: duration(),
  }

  function reportIfDue(at: number) {
    const windowMs = at - startedAt
    if (disposed || windowMs < REPORT_INTERVAL_MS) return
    const report: PreviewPerformanceReport = {
      cameraKey: options.cameraKey, feature: options.feature, department: options.department,
      sampledAt: new Date().toISOString(), windowMs: rounded(windowMs),
      targetFps: rounded(1000 / options.refreshMs), readyFps: rounded(completed * 1000 / windowMs),
      // img 的 load 事件证明图片已加载；此数值不等于屏幕实际绘制或独立视频帧数。
      imageLoadFps: rounded(loaded * 1000 / windowMs),
      capturePublishedFpsEstimate: captureRate(captureFirst, captureLast),
      completedRequests: completed, failedRequests: failed,
      averageImageKiB: completed ? rounded(bytes / completed / 1024) : null,
      averageMs: Object.fromEntries(Object.entries(stages).map(([name, value]) => [
        name, value.count ? rounded(value.total / value.count) : null,
      ])) as PreviewPerformanceReport['averageMs'],
    }
    startedAt = at
    completed = failed = loaded = bytes = 0
    captureFirst = captureLast = null
    for (const value of Object.values(stages)) value.total = value.count = 0
    options.onReport(report)
  }

  return {
    completed(sample: FrameSample) {
      if (disposed) return
      completed++
      bytes += sample.bytes
      add(stages.requestToHeaders, sample.headersReceivedAt - sample.startedAt)
      add(stages.downloadBody, sample.bodyReceivedAt - sample.headersReceivedAt)
      add(stages.imageDecode, sample.decodedAt - sample.bodyReceivedAt)
      add(stages.requestToReady, sample.decodedAt - sample.startedAt)
      pending = { src: sample.src, decodedAt: sample.decodedAt }
      const timing = sample.headers.get('Server-Timing') ?? ''
      const names = {
        frame_lookup: 'frameLookupAndOverlay', jpeg_encode: 'jpegEncode', frame_total: 'frameHandler',
        auth: 'authentication', camera_access: 'cameraAccess', request_total: 'serverRequest',
      } as const
      const serverDurations: Record<string, number> = {}
      for (const [metric, stage] of Object.entries(names)) {
        const match = timing.match(new RegExp(`(?:^|,)\\s*${metric}\\s*;\\s*dur=([0-9]+(?:\\.[0-9]+)?)(?=\\s*(?:;|,|$))`))
        const milliseconds = readNumber(match?.[1] ?? null)
        if (milliseconds !== null) {
          serverDurations[metric] = milliseconds
          add(stages[stage], milliseconds)
          // 差值还包含鉴权、排队、代理和往返传输，不能当成纯网络延迟。
          if (metric === 'frame_total') add(stages.outsideFrameHandler,
            Math.max(0, sample.headersReceivedAt - sample.startedAt - milliseconds))
          if (metric === 'request_total') add(stages.outsideServer,
            Math.max(0, sample.headersReceivedAt - sample.startedAt - milliseconds))
        }
      }
      if (['request_total', 'auth', 'camera_access', 'frame_total'].every((name) => name in serverDurations)) {
        add(stages.serverDispatch, Math.max(0, serverDurations.request_total - serverDurations.auth
          - serverDurations.camera_access - serverDurations.frame_total))
      }
      const age = readNumber(sample.headers.get('X-Capture-Age-Ms'))
      if (age !== null) add(stages.captureAge, age)
      const sequence = readNumber(sample.headers.get('X-Capture-Sequence'))
      const updatedAt = readNumber(sample.headers.get('X-Capture-Updated-At'))
      if (sequence !== null && Number.isSafeInteger(sequence) && sequence > 0 && updatedAt !== null && updatedAt > 0) {
        const capture = { sequence, updatedAt, observedAt: sample.headersReceivedAt }
        // 序号回退或采集时钟回退代表重启/异常，不能跨两段采集计算发布频率。
        if (!captureFirst || (captureLast && (sequence < captureLast.sequence || updatedAt < captureLast.updatedAt))) {
          captureFirst = capture
        }
        captureLast = capture
      }
      reportIfDue(sample.decodedAt)
    },
    displayed(src: string) {
      if (disposed || pending?.src !== src) return
      const at = now()
      loaded++
      add(stages.readyToImageLoad, at - pending.decodedAt)
      pending = null
      reportIfDue(at)
    },
    failed() {
      if (disposed) return
      failed++
      reportIfDue(now())
    },
    dispose() { disposed = true; pending = null },
  }
}
