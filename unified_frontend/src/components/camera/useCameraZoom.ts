import { useCallback, useEffect, useRef, useState } from 'react'
import { CameraZoomError, controlCameraZoom, getCameraZoom, type CameraZoomCapabilities, type ZoomAction } from './zoomApi'

const PULSE_GAP_MS = 40

export function useCameraZoom(cameraKey: string, feature: string, previewConnected = true) {
  const [capabilities, setCapabilities] = useState<CameraZoomCapabilities | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState<ZoomAction | null>(null)
  const [denied, setDenied] = useState(false)
  const [rate, setRateValue] = useState(0)
  const [revision, setRevision] = useState(0)
  const alive = useRef(false)
  const operation = useRef(0)
  const busy = useRef(false)
  const stopping = useRef(false)
  const needsStop = useRef(false)
  const desiredRate = useRef(0)
  const loopGeneration = useRef(0)
  const loopRunning = useRef(false)
  const finishPause = useRef<(() => void) | null>(null)

  const cancelRepeat = useCallback(() => {
    desiredRate.current = 0
    loopGeneration.current += 1
    loopRunning.current = false
    finishPause.current?.()
    if (alive.current) setRateValue(0)
  }, [])

  useEffect(() => {
    alive.current = true
    const stopOnLeave = () => {
      cancelRepeat()
      if (!needsStop.current) return
      void controlCameraZoom(cameraKey, feature, 'stop', { keepalive: true }).catch((cause) => {
        console.warn('离开镜头控制页面时停止未获确认：', cause instanceof Error ? cause.message : '请求失败')
      })
    }
    const onVisibility = () => { if (document.hidden) stopOnLeave() }
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', stopOnLeave)
    window.addEventListener('blur', stopOnLeave)
    return () => {
      alive.current = false
      operation.current += 1
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', stopOnLeave)
      window.removeEventListener('blur', stopOnLeave)
      stopOnLeave()
    }
  }, [cameraKey, feature, cancelRepeat])

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

  const execute = useCallback(async (action: ZoomAction, speedFraction?: number) => {
    if (!alive.current || denied || stopping.current || (busy.current && action !== 'stop')) return false
    if (action !== 'stop' && (!previewConnected || capabilities?.status !== 'supported' || loading)) return false
    if ((action === 'in' && !capabilities?.zoom_in) || (action === 'out' && !capabilities?.zoom_out)) return false
    const current = ++operation.current
    busy.current = true
    stopping.current = action === 'stop'
    if (action !== 'stop') needsStop.current = true
    setPending(action); setError(''); setMessage('')
    try {
      await controlCameraZoom(cameraKey, feature, action, { speedFraction })
      if (alive.current && current === operation.current) {
        needsStop.current = false
        setMessage(action === 'stop' ? '镜头已停止' : desiredRate.current ? '持续调整中，松手停止' : '镜头已调整并停止')
      }
      return alive.current && current === operation.current
    } catch (cause) {
      if (alive.current && current === operation.current) {
        cancelRepeat()
        setError(cause instanceof Error ? cause.message : '镜头操作失败')
        if (cause instanceof CameraZoomError && [401, 403].includes(cause.status)) setDenied(true)
      }
      return false
    } finally {
      if (alive.current && current === operation.current) {
        busy.current = false; stopping.current = false; setPending(null)
      }
    }
  }, [cameraKey, feature, capabilities, loading, denied, previewConnected, cancelRepeat])

  const control = useCallback(async (action: ZoomAction) => {
    if (action === 'stop') cancelRepeat()
    return execute(action)
  }, [execute, cancelRepeat])

  const release = useCallback(() => {
    if (!loopRunning.current && !desiredRate.current && !needsStop.current) return
    cancelRepeat()
    if (needsStop.current || busy.current) void execute('stop')
  }, [cancelRepeat, execute])

  useEffect(() => { if (!previewConnected) release() }, [previewConnected, release])

  const setRate = useCallback((value: number) => {
    if (!Number.isFinite(value) || !previewConnected || denied || loading || capabilities?.status !== 'supported' || stopping.current) return
    const next = Math.max(-100, Math.min(100, value))
    if (!next) { release(); return }
    if ((next > 0 && !capabilities.zoom_in) || (next < 0 && !capabilities.zoom_out)) return
    if (busy.current && !loopRunning.current) return
    desiredRate.current = next
    setRateValue(next)
    if (loopRunning.current) return
    loopRunning.current = true
    const generation = ++loopGeneration.current
    void (async () => {
      try {
        while (alive.current && generation === loopGeneration.current && desiredRate.current) {
          const requested = desiredRate.current
          const completed = await execute(requested > 0 ? 'in' : 'out', Math.abs(requested) / 100)
          if (!completed || generation !== loopGeneration.current) break
          // 始终让出事件循环；服务快速返回时也不能饿死松手、取消和停止事件。
          await new Promise<void>((resolve) => {
            const finish = () => { clearTimeout(timer); finishPause.current = null; resolve() }
            const timer = setTimeout(finish, PULSE_GAP_MS)
            finishPause.current = finish
          })
        }
      } finally {
        if (alive.current && generation === loopGeneration.current) cancelRepeat()
      }
    })()
  }, [previewConnected, denied, loading, capabilities, release, execute, cancelRepeat])

  return { capabilities, loading, error, message, pending, denied, control, rate, setRate, release,
    reload: () => { if (!busy.current && !denied) setRevision((value) => value + 1) } }
}
