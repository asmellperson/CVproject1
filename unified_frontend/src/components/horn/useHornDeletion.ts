import { useEffect, useRef, useState } from 'react'
import { deleteHorn, getHornUsage, HornApiError, type HornDevice, type HornUsage } from '@/lib/horns'

export function useHornDeletion(device: HornDevice, onDeleted: () => void) {
  const [usage, setUsage] = useState<HornUsage | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const action = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  const scope = device.department ?? 'unassigned'

  useEffect(() => {
    mounted.current = true
    let active = true
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 8000)
    setLoading(true); setUsage(null); setError('')
    void getHornUsage(device.id, scope, controller.signal).then((value) => {
      if (active && !controller.signal.aborted) setUsage(value)
    }).catch((reason) => {
      if (active) setError(controller.signal.aborted ? '引用读取超时，请重试。'
        : reason instanceof Error ? reason.message : '引用读取失败。')
    }).finally(() => {
      window.clearTimeout(timer)
      if (active) setLoading(false)
    })
    return () => { active = false; mounted.current = false; controller.abort(); action.current?.abort(); window.clearTimeout(timer) }
  }, [device.id, scope, revision])

  const remove = async () => {
    if (!usage || loading || action.current || (usage.device_enabled && usage.references.length > 0)) return
    const controller = new AbortController()
    action.current = controller
    const timer = window.setTimeout(() => controller.abort(), 20000)
    setBusy(true); setError('')
    try {
      await deleteHorn(device.id, scope, { detach_bindings: usage.references.length > 0, expected_revision: usage.revision }, controller.signal)
      if (!controller.signal.aborted && mounted.current) onDeleted()
    } catch (reason) {
      if (mounted.current) {
        if (reason instanceof HornApiError && reason.usage) setUsage(reason.usage)
        setError(controller.signal.aborted ? '删除等待超时，请刷新设备列表核对结果。'
          : reason instanceof Error ? reason.message : '删除失败。')
      }
    } finally {
      window.clearTimeout(timer)
      if (action.current === controller) action.current = null
      if (mounted.current) setBusy(false)
    }
  }
  return { usage, loading, busy, error, remove, reload: () => setRevision((value) => value + 1) }
}
