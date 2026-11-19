import { useCallback, useEffect, useMemo, useState } from 'react'
import { getAiVisionDepartments, type AiVisionDepartment } from '@/lib/aivision'

export function useDepartmentCatalog(enabled = true) {
  const [settled, setSettled] = useState({ revision: -1, departments: [] as AiVisionDepartment[], error: '' })
  const [revision, setRevision] = useState(0)
  const reload = useCallback(() => setRevision((value) => value + 1), [])
  // 加载态由“当前请求是否已有结论”推导，避免 effect 同步改状态导致级联渲染。
  const loading = enabled && settled.revision !== revision
  const departments = settled.departments
  const error = loading ? '' : settled.error

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    void getAiVisionDepartments(controller.signal).then((items) => {
      if (!controller.signal.aborted) setSettled({ revision, departments: items, error: '' })
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setSettled({
          revision,
          departments: [],
          error: `事业部列表加载失败：${cause instanceof Error ? cause.message : String(cause)}`,
        })
      }
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
