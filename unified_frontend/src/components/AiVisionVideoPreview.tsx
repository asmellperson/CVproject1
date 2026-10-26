import { useEffect, useRef, useState } from 'react'
import { createMsePreviewSession } from './AiVisionVideoPreview.mse'
import type { VideoPreviewState } from './AiVisionVideoPreview.mse'

type Props = {
  url: string
  cameraKey: string
  department: string
  feature: string
  onFallback?: () => void
  onAccessDenied?: () => void
  onStateChange?: (state: VideoPreviewState) => void
}

const MESSAGES: Record<VideoPreviewState, string> = {
  connecting: '正在连接原始视频…',
  playing: '原始视频，未叠加检测框',
  reconnecting: '视频连接中断，正在重连…',
  paused: '页面不可见，已暂停视频',
  fallback: '视频未连接，正在切换 JPEG 预览',
  'access-denied': '当前账号无权查看此摄像头，画面已清空',
}

export function AiVisionVideoPreview({ url, cameraKey, department, feature, onFallback, onAccessDenied, onStateChange }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const callbacks = useRef({ onFallback, onAccessDenied, onStateChange })
  const [status, setStatus] = useState<{ key: string; state: VideoPreviewState } | null>(null)
  const key = `${department}:${feature}:${cameraKey}:${url}`
  const state = status?.key === key ? status.state : 'connecting'
  useEffect(() => {
    callbacks.current = { onFallback, onAccessDenied, onStateChange }
  }, [onFallback, onAccessDenied, onStateChange])
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    let active = true
    const session = createMsePreviewSession({
      video, url, visible: !document.hidden,
      onState(next) {
        if (!active) return
        setStatus({ key, state: next })
        callbacks.current.onStateChange?.(next)
      },
      onFallback() { if (active) callbacks.current.onFallback?.() },
      onAccessDenied() { if (active) callbacks.current.onAccessDenied?.() },
    })
    const visibility = () => {
      session.setVisible(!document.hidden)
    }
    document.addEventListener('visibilitychange', visibility)
    return () => {
      active = false
      document.removeEventListener('visibilitychange', visibility)
      session.dispose()
    }
  }, [key, url])
  return <div className="relative h-full w-full overflow-hidden bg-slate-950">
    <video key={key} ref={videoRef} autoPlay muted playsInline className="h-full w-full object-contain" />
    <div role="status" className={state === 'playing'
      ? 'pointer-events-none absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-xs text-slate-200'
      : 'pointer-events-none absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-300'}>
      {MESSAGES[state]}
    </div>
  </div>
}
