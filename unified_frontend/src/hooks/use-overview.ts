import { useEffect, useRef, useState } from 'react'
import type { AuthUser } from '../auth/auth-context'
import { getOverview, OVERVIEW_POLL_INTERVAL_MS, OVERVIEW_REQUEST_TIMEOUT_MS, type OverviewStatus } from '../lib/api'
import { useSerialPoll } from './use-serial-poll'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '../lib/camera-events'
import { PLATFORM_RUNTIME_CHANGED_EVENT } from '../lib/runtime-events'

export function useOverview(user: AuthUser | null) {
  const scope = user ? JSON.stringify([user.employee_id, user.role, [...user.departments].sort()]) : null
  const [result, setResult] = useState<{ scope: string; data: OverviewStatus | null; error: string } | null>(null)
  const [revision, setRevision] = useState(0)
  const context = `${scope}:${revision}`
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
    if (!scope) return
    try {
      const data = await getOverview({ signal })
      if (!mounted.current || signal.aborted || current.current !== requestContext) return
      setResult({ scope, data, error: data.inventory_complete ? '' : `摄像头清单加载不完整：${Object.values(data.inventory_errors).join('；')}` })
    } catch (error) {
      if (mounted.current && current.current === requestContext) setResult({ scope, data: null, error: `摄像头清单加载失败：${String(error)}` })
    }
  }, {
    enabled: scope !== null,
    intervalMs: OVERVIEW_POLL_INTERVAL_MS,
    timeoutMs: OVERVIEW_REQUEST_TIMEOUT_MS,
    restartKey: context,
  })

  const scoped = result?.scope === scope ? result : null
  return { data: scoped?.data ?? null, error: scoped?.error ?? '', loading: scope !== null && !scoped, refresh }
}

export type OverviewState = ReturnType<typeof useOverview>
