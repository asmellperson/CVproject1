import { useEffect, useRef, useState } from 'react'
import { testHornPlayback, type HornPlaybackResult, type HornScope } from '@/lib/horns'

export function useHornPlayback(hornId: number, audioId: number | null, scope: HornScope) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<HornPlaybackResult | null>(null)
  const [error, setError] = useState('')
  const [resultKey, setResultKey] = useState('')
  const selectionKey = `${hornId}:${audioId}`
  const mounted = useRef(true)
  const active = useRef<AbortController | null>(null)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; active.current?.abort() }
  }, [hornId])

  const play = async (duration = 0) => {
    if (!audioId || active.current || !mounted.current) return
    const controller = new AbortController()
    active.current = controller
    setBusy(true); setResult(null); setError(''); setResultKey(selectionKey)
    const timer = window.setTimeout(() => controller.abort(), Math.max(30000, (duration + 30) * 1000))
    try {
      const value = await testHornPlayback(hornId, audioId, scope, controller.signal)
      if (!controller.signal.aborted && mounted.current) setResult(value)
    } catch (reason) {
      if (mounted.current) setError(controller.signal.aborted ? '试播等待超时，请现场确认设备状态后再操作。'
        : reason instanceof Error ? reason.message : '试播请求失败。')
    } finally {
      window.clearTimeout(timer)
      if (active.current === controller) active.current = null
      if (mounted.current) setBusy(false)
    }
  }
  return { busy, result: resultKey === selectionKey ? result : null,
    error: resultKey === selectionKey ? error : '', play }
}
