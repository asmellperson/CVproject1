export type VideoPreviewState = 'connecting' | 'playing' | 'reconnecting' | 'paused' | 'fallback' | 'access-denied'

export type VideoPreviewPerformanceReport = {
  mode: 'mse'
  cameraKey: string
  feature: string
  department: string
  sampledAt: string
  windowMs: number
  videoFps: number | null
  droppedVideoFrames: number | null
  receivedKiB: number
  bufferedSeconds: number
  videoWidth: number
  videoHeight: number
  state: VideoPreviewState
}

export type VideoPreviewPerformanceGroupReport = {
  scope: 'guard_behavior'
  siteId: number | null
  department: string
  sampledAt: string
  cameras: Record<string, VideoPreviewPerformanceReport | null>
}

declare global {
  interface Window {
    aivisionVideoPreviewDiagnostics?: VideoPreviewPerformanceReport | VideoPreviewPerformanceGroupReport
  }
}

export function createVideoPreviewPerformanceGroup(options: {
  siteId: number | null
  department: string
  onReport: (report: VideoPreviewPerformanceGroupReport) => void
}) {
  const cameras = new Map<string, VideoPreviewPerformanceReport | null>()
  const activeCameras = new Set<string>()
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
    setCameras(keys: string[], activeKeys: string[] = keys) {
      if (disposed) return
      const members = new Set([...new Set(keys)].slice(0, 3))
      activeCameras.clear()
      for (const key of activeKeys) if (members.has(key)) activeCameras.add(key)
      let changed = false
      for (const key of cameras.keys()) {
        if (!members.has(key)) { cameras.delete(key); changed = true }
      }
      for (const key of members) {
        if (!cameras.has(key)) { cameras.set(key, null); changed = true }
        // 仍在站点但已离线或停用的成员保留键，旧播放帧率必须同时清空。
        else if (!activeCameras.has(key) && cameras.get(key) !== null) { cameras.set(key, null); changed = true }
      }
      if (changed) publish()
    },
    update(report: VideoPreviewPerformanceReport) {
      // 保安室成员、事业部及功能必须同时匹配，迟到的其他上下文不能污染当前统计。
      if (disposed || report.department !== options.department || report.feature !== 'guard_behavior'
        || !cameras.has(report.cameraKey) || !activeCameras.has(report.cameraKey)) return
      cameras.set(report.cameraKey, report)
      publish()
    },
    reset() {
      if (disposed) return
      for (const key of cameras.keys()) cameras.set(key, null)
      publish()
    },
    dispose() { disposed = true; cameras.clear(); activeCameras.clear() },
  }
}

export function createVideoPreviewPerformanceRecorder(options: {
  video: HTMLVideoElement
  cameraKey: string
  feature: string
  department: string
  now: () => number
  onReport: (report: VideoPreviewPerformanceReport) => void
}) {
  const quality = () => options.video.getVideoPlaybackQuality?.()
  let baseline = quality()
  let startedAt = options.now()
  let receivedBytes = 0
  const rounded = (value: number) => Math.round(value * 100) / 100
  return {
    received(bytes: number) { receivedBytes += bytes },
    sample(state: VideoPreviewState, force = false) {
      const at = options.now()
      const windowMs = at - startedAt
      if (windowMs <= 0 || (!force && windowMs < 5000)) return
      const current = quality()
      // 切换媒体源会重置浏览器计数，不能把跨播放会话的差分当作帧率。
      const comparable = current && baseline && current.totalVideoFrames >= baseline.totalVideoFrames
        && current.droppedVideoFrames >= baseline.droppedVideoFrames
      const buffered = options.video.buffered
      const end = buffered.length ? buffered.end(buffered.length - 1) : 0
      options.onReport({
        mode: 'mse', cameraKey: options.cameraKey, feature: options.feature, department: options.department,
        sampledAt: new Date().toISOString(), windowMs: rounded(windowMs),
        // totalVideoFrames 包含丢弃帧，扣除后才是浏览器呈现的视频帧率。
        videoFps: comparable ? rounded(Math.max(0, current.totalVideoFrames - baseline.totalVideoFrames
          - current.droppedVideoFrames + baseline.droppedVideoFrames) * 1000 / windowMs) : null,
        droppedVideoFrames: comparable ? current.droppedVideoFrames - baseline.droppedVideoFrames : null,
        receivedKiB: rounded(receivedBytes / 1024),
        bufferedSeconds: rounded(Math.max(0, end - options.video.currentTime)),
        videoWidth: options.video.videoWidth, videoHeight: options.video.videoHeight, state,
      })
      baseline = current
      receivedBytes = 0
      startedAt = at
    },
  }
}
