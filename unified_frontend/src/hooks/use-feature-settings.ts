import { useEffect, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { getFeatureSettings, saveFeatureSettings, type FeatureSettings } from '@/lib/feature-settings'

export function useFeatureSettings() {
  const [saved, setSaved] = useState<FeatureSettings | null>(null)
  const [draft, setDraft] = useState<FeatureSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getFeatureSettings(controller.signal).then((result) => {
      if (controller.signal.aborted) return
      setSaved(result)
      setDraft(result)
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '功能分配加载失败')
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [revision])

  const reload = () => {
    setLoading(true)
    setError('')
    setRevision((value) => value + 1)
  }

  const toggle = (department: DepartmentId, feature: string, enabled: boolean) => {
    setDraft((current) => current && ({
      ...current,
      assignments: current.assignments.map((item) => item.department !== department ? item : {
        ...item,
        features: enabled ? [...item.features, feature] : item.features.filter((name) => name !== feature),
      }),
    }))
  }

  const dirty = Boolean(saved && draft && draft.assignments.some((item, index) => {
    const before = saved.assignments[index].features
    return item.features.length !== before.length || item.features.some((name) => !before.includes(name))
  }))
  const removed = saved && draft ? saved.assignments.flatMap((item, index) =>
    item.features.filter((name) => !draft.assignments[index].features.includes(name))
      .map((feature) => ({ department: item.department, feature })),
  ) : []

  const save = async () => {
    if (!draft || !dirty || saving) return false
    setSaving(true)
    setError('')
    try {
      const result = await saveFeatureSettings(draft.assignments)
      setSaved(result)
      setDraft(result)
      return true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '功能分配保存失败')
      return false
    } finally {
      setSaving(false)
    }
  }

  return { draft, loading, saving, error, dirty, removed, reload, toggle, save }
}
