import { useEffect, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { listHorns, type HornDevice } from '@/lib/horns'
import { useDetectionDepartment } from '@/components/detection/DetectionDepartmentContext'

export function useHornCatalog(enabled: boolean) {
  const department = useDetectionDepartment()
  const [devices, setDevices] = useState<HornDevice[] | null>(null)
  const [error, setError] = useState('')
  const active = useRef(enabled)
  useEffect(() => {
    active.current = enabled
    return () => { active.current = false }
  }, [enabled])

  useSerialPoll(async (signal) => {
    try {
      if (!department) return
      const items = await listHorns(department, signal)
      if (!signal.aborted && active.current) {
        setDevices(items)
        setError('')
      }
    } catch (reason) {
      if (!active.current) return
      setError(signal.aborted ? '喇叭设备列表读取超时或中断，稍后自动重试。'
        : reason instanceof Error ? reason.message : '喇叭设备列表读取失败，稍后自动重试。')
    }
  }, { enabled: enabled && department !== null, intervalMs: 5000, timeoutMs: 8000, restartKey: department ?? 'none' })

  return { devices: enabled ? devices : null, error: enabled ? error : '' }
}
