import { useCallback, useEffect, useMemo, useState } from 'react'
import { getAiVisionDepartments, type AiVisionDepartment } from '@/lib/aivision'

export function useDepartmentCatalog(enabled = true) {
  const [departments, setDepartments] = useState<AiVisionDepartment[]>([])
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const reload = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    setLoading(true)
    setError('')
    void getAiVisionDepartments(controller.signal).then((items) => {
      if (!controller.signal.aborted) setDepartments(items)
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setDepartments([])
        setError(`事业部列表加载失败：${cause instanceof Error ? cause.message : String(cause)}`)
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [enabled, revision])

  const options = useMemo(
    () => departments.map(({ name, display_name }) => ({ value: name, label: display_name })),
    [departments],
  )
  const labels = useMemo<Record<string, string>>(
    () => ({ all: '全部事业部', ...Object.fromEntries(options.map(({ value, label }) => [value, label])) }),
    [options],
  )
  return { options, labels, loading, error, reload }
}
