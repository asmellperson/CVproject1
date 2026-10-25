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

declare global {
  interface Window { aivisionVideoPreviewDiagnostics?: VideoPreviewPerformanceReport }
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
