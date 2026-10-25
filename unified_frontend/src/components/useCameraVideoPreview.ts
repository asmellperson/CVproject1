import { useCallback, useEffect, useMemo, useState } from 'react'
import { getCameraPreviewStream, PreviewStreamAccessError } from '../lib/preview-stream'

type PreviewMode = 'checking' | 'jpeg' | 'mse' | 'denied'
type Options = { cameraKey: string; feature: string; department: string; enabled: boolean }
type PreviewState = { mode: PreviewMode; url: string | null; fallbackReason: string }
const FALLBACK_REASON = '视频试播未连接，显示 JPEG 画面'

export function useCameraVideoPreview({ cameraKey, feature, department, enabled }: Options): PreviewState & {
  onFallback: () => void
  onAccessDenied: () => void
} {
  // 对象身份也区分隐藏后恢复的同一摄像头，旧播放会话回调不能修改新会话。
  const context = useMemo(() => ({ cameraKey, feature, department, enabled }), [cameraKey, feature, department, enabled])
  const [snapshot, setSnapshot] = useState<{ context: typeof context; value: PreviewState } | null>(null)
  useEffect(() => {
    if (!context.enabled || !context.cameraKey) return
    let active = true
    const controller = new AbortController()
    getCameraPreviewStream(context.cameraKey, context.feature, { signal: controller.signal }).then(
      (capability) => {
        if (!active || controller.signal.aborted) return
        setSnapshot({ context, value: {
          mode: capability.enabled ? 'mse' : 'jpeg', url: capability.url, fallbackReason: '',
        } })
      },
      (error: unknown) => {
        if (!active || controller.signal.aborted) return
        setSnapshot({ context, value: error instanceof PreviewStreamAccessError
          ? { mode: 'denied', url: null, fallbackReason: '' }
          : { mode: 'jpeg', url: null, fallbackReason: FALLBACK_REASON } })
      },
    )
    return () => { active = false; controller.abort() }
  }, [context])
  const onFallback = useCallback(() => {
    setSnapshot((current) => current?.context === context && current.value.mode === 'mse'
      ? { context, value: { mode: 'jpeg', url: null, fallbackReason: FALLBACK_REASON } }
      : current)
  }, [context])
  const onAccessDenied = useCallback(() => {
    setSnapshot((current) => current?.context === context && current.value.mode !== 'denied'
      ? { context, value: { mode: 'denied', url: null, fallbackReason: '' } }
      : current)
  }, [context])
  const value: PreviewState = snapshot?.context === context ? snapshot.value : {
    mode: enabled && cameraKey ? 'checking' : 'jpeg', url: null, fallbackReason: '',
  }
  return { ...value, onFallback, onAccessDenied }
}
