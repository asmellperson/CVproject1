import { useCallback, useEffect, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { getSites } from './api'
import type { GuardSite } from './types'

export function useGuardSites(department: DepartmentId) {
  const [sites, setSites] = useState<GuardSite[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const reload = useCallback(async (signal?: AbortSignal, preferredId?: number) => {
    setLoading(true)
    try {
      const next = await getSites(department, signal)
      if (signal?.aborted) return
      setSites(next)
      setSelectedId((current) => {
        const id = preferredId ?? current
        return next.some((site) => site.id === id) ? id : next[0]?.id ?? null
      })
      setError('')
    } catch (cause) {
      if (!signal?.aborted) setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [department])
  useEffect(() => {
    const controller = new AbortController()
    void reload(controller.signal)
    return () => controller.abort()
  }, [reload])
  return { sites, selectedId, setSelectedId, loading, error, reload,
    site: sites.find((site) => site.id === selectedId) ?? null }
}
