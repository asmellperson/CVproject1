import { useEffect, useRef, useState } from 'react'
import type { AuthUser } from '../auth/auth-context'
import { getOverview, OVERVIEW_POLL_INTERVAL_MS, OVERVIEW_REQUEST_TIMEOUT_MS, type OverviewStatus } from '../lib/api'
import { useSerialPoll } from './use-serial-poll'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '../lib/camera-events'
import { PLATFORM_RUNTIME_CHANGED_EVENT } from '../lib/runtime-events'

const OVERVIEW_INITIAL_RETRY_MS = 3_000
// 现场完整清单请求可接近 9 秒，首次加载和超时恢复需要覆盖该耗时。
const OVERVIEW_RECOVERY_TIMEOUT_MS = 12_000

type OverviewResult = {
  scope: string
  context: string
  data: OverviewStatus | null
  error: string
  retryDelayMs: number | null
  timedOut: boolean
}

export function useOverview(user: AuthUser | null) {
  const scope = user ? JSON.stringify([user.employee_id, user.role, [...user.departments].sort(), user.feature_access]) : null
  const [result, setResult] = useState<OverviewResult | null>(null)
  const [revision, setRevision] = useState(0)
  const context = `${scope}:${revision}`
  const current = useRef(context)
  const requestContext = context
  const mounted = useRef(false)
  const scoped = result?.scope === scope ? result : null
  const refresh = () => setRevision((value) => value + 1)

  useEffect(() => {
    current.current = context
  }, [context])

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
    const recordFailure = (data: OverviewStatus | null, error: string, timedOut = false) => {
      // 短暂故障尽快恢复，持续失败则逐步回到正常轮询频率。
      setResult((previous) => {
        const sameScope = previous?.scope === scope ? previous : null
        const complete = sameScope?.data?.inventory_complete ? sameScope.data : null
        return { scope, context: requestContext, data: complete ?? data,
          error: complete ? `${error}（显示上次成功清单）` : error,
          retryDelayMs: sameScope?.context === requestContext && sameScope.retryDelayMs !== null
            ? Math.min(sameScope.retryDelayMs * 2, OVERVIEW_POLL_INTERVAL_MS) : OVERVIEW_INITIAL_RETRY_MS,
          timedOut: timedOut || Boolean(sameScope?.timedOut) }
      })
    }
    try {
      const data = await getOverview({ signal })
      if (!mounted.current || signal.aborted || current.current !== requestContext) return
      if (!data.inventory_complete) {
        recordFailure(data, `摄像头清单加载不完整：${Object.values(data.inventory_errors).join('；')}`)
        return
      }
      setResult({ scope, context: requestContext, data, error: '', retryDelayMs: null, timedOut: false })
    } catch (error) {
      // 初始化重挂载或刷新导致的主动取消不属于加载失败，超时仍需提示。
      const timedOut = signal.aborted && signal.reason?.name === 'TimeoutError'
      if (signal.aborted && !timedOut) return
      if (mounted.current && current.current === requestContext) recordFailure(null, `摄像头清单加载失败：${String(error)}`, timedOut)
    }
  }, {
    enabled: scope !== null,
    intervalMs: scoped?.context === context ? scoped.retryDelayMs ?? OVERVIEW_POLL_INTERVAL_MS : OVERVIEW_POLL_INTERVAL_MS,
    timeoutMs: !scoped?.data?.inventory_complete || scoped.timedOut ? OVERVIEW_RECOVERY_TIMEOUT_MS : OVERVIEW_REQUEST_TIMEOUT_MS,
    restartKey: context,
  })

  return { data: scoped?.data ?? null, error: scoped?.error ?? '', loading: scope !== null && !scoped, refresh }
}

export type OverviewState = ReturnType<typeof useOverview>
