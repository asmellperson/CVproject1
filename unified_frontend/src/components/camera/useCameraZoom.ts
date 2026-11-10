import { useCallback, useEffect, useRef, useState } from 'react'
import { CameraZoomError, controlCameraZoom, getCameraZoom, type CameraZoomCapabilities, type ZoomAction } from './zoomApi'

export function useCameraZoom(cameraKey: string, feature: string) {
  const [capabilities, setCapabilities] = useState<CameraZoomCapabilities | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState<ZoomAction | null>(null)
  const [denied, setDenied] = useState(false)
  const [revision, setRevision] = useState(0)
  const alive = useRef(false)
  const operation = useRef(0)
  const busy = useRef(false)
  const stopping = useRef(false)
  const needsStop = useRef(false)

  useEffect(() => {
    alive.current = true
    const stopOnLeave = () => {
      if (!needsStop.current) return
      void controlCameraZoom(cameraKey, feature, 'stop', true).catch((cause) => {
        console.warn('离开镜头控制页面时停止未获确认：', cause instanceof Error ? cause.message : '请求失败')
      })
    }
    const onVisibility = () => { if (document.hidden) stopOnLeave() }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', stopOnLeave)
    return () => {
      alive.current = false
      operation.current += 1
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', stopOnLeave)
      stopOnLeave()
    }
  }, [cameraKey, feature])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setCapabilities(null); setError('')
    void getCameraZoom(cameraKey, feature, controller.signal).then((value) => {
      if (!controller.signal.aborted) setCapabilities(value)
    }).catch((cause) => {
      if (controller.signal.aborted) return
      setError(cause instanceof Error ? cause.message : '变焦能力读取失败')
      if (cause instanceof CameraZoomError && [401, 403].includes(cause.status)) setDenied(true)
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [cameraKey, feature, revision])

  const control = useCallback(async (action: ZoomAction) => {
    if (denied || stopping.current || (busy.current && action !== 'stop')) return
    if (action !== 'stop' && (capabilities?.status !== 'supported' || loading)) return
    const current = ++operation.current
    busy.current = true
    stopping.current = action === 'stop'
    if (action !== 'stop') needsStop.current = true
    setPending(action); setError(''); setMessage('')
    try {
      await controlCameraZoom(cameraKey, feature, action)
      if (alive.current && current === operation.current) {
        needsStop.current = false
        setMessage(action === 'stop' ? '镜头已停止' : '镜头已调整并停止')
      }
    } catch (cause) {
      if (alive.current && current === operation.current) {
        setError(cause instanceof Error ? cause.message : '镜头操作失败')
        if (cause instanceof CameraZoomError && [401, 403].includes(cause.status)) setDenied(true)
      }
    } finally {
      if (alive.current && current === operation.current) {
        busy.current = false; stopping.current = false; setPending(null)
      }
    }
  }, [cameraKey, feature, capabilities, loading, denied])

  return { capabilities, loading, error, message, pending, denied, control,
    reload: () => { if (!busy.current && !denied) setRevision((value) => value + 1) } }
}
