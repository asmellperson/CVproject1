import { useEffect, useRef, useState } from 'react'
import type { DepartmentId } from '../auth/permissions'
import { getOverview, OVERVIEW_POLL_INTERVAL_MS, OVERVIEW_REQUEST_TIMEOUT_MS, type OverviewStatus } from '../lib/api'
import { useSerialPoll } from './use-serial-poll'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '../lib/camera-events'
import { PLATFORM_RUNTIME_CHANGED_EVENT } from '../lib/runtime-events'

export function useOverview(department: DepartmentId | null) {
  const [result, setResult] = useState<{ department: DepartmentId; data: OverviewStatus | null; error: string } | null>(null)
  const [revision, setRevision] = useState(0)
  const context = `${department}:${revision}`
  const current = useRef({ key: context })
  if (current.current.key !== context) current.current = { key: context }
  const requestContext = current.current
  const mounted = useRef(false)
  const refresh = () => setRevision((value) => value + 1)

  useEffect(() => {
    mounted.current = true
    window.addEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
    window.addEventListener(PLATFORM_RUNTIME_CHANGED_EVENT, refresh)
    return () => {
      mounted.current = false
      window.removeEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
      window.removeEventListener(PLATFORM_RUNTIME_CHANGED_EVENT, refresh)
    }
  }, [])

  useSerialPoll(async (signal) => {
    if (!department) return
    try {
      const data = await getOverview(department, { signal })
      if (!mounted.current || signal.aborted || current.current !== requestContext) return
      if (data.department !== department) throw new Error('总览返回的事业部不匹配')
      setResult({ department, data, error: data.inventory_complete ? '' : `摄像头清单加载不完整：${Object.values(data.inventory_errors).join('；')}` })
    } catch (error) {
      if (mounted.current && current.current === requestContext) setResult({ department, data: null, error: `摄像头清单加载失败：${String(error)}` })
    }
  }, {
    enabled: department !== null,
    intervalMs: OVERVIEW_POLL_INTERVAL_MS,
    timeoutMs: OVERVIEW_REQUEST_TIMEOUT_MS,
    restartKey: context,
  })

  const scoped = result?.department === department ? result : null
  return { data: scoped?.data ?? null, error: scoped?.error ?? '', loading: department !== null && !scoped, refresh }
}

export type OverviewState = ReturnType<typeof useOverview>
