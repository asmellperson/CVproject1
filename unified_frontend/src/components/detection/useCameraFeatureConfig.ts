import { useCallback, useEffect, useRef, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { getAiVisionCameras, getAiVisionFeatureConfig, saveAiVisionFeatureConfig, type AiVisionCamera, type AiVisionFeatureConfig } from '@/lib/aivision'
import { getEnabledFeatureCameras, selectFeatureCamera } from '@/lib/feature-cameras'

export function useCameraFeatureConfig<Config extends AiVisionFeatureConfig, Draft>({
  feature, department, isAdmin, createDraft, buildConfig,
}: {
  feature: string
  department: DepartmentId
  isAdmin: boolean
  createDraft: (config: Config) => Draft
  buildConfig: (draft: Draft) => Config
}) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraKey, setCameraKey] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('正在读取摄像头…')
  const revision = useRef(0)
  const selected = useRef('')
  const busy = useRef(false)
  const enabledCameras = getEnabledFeatureCameras(cameras, feature, department)

  const loadConfig = useCallback(async (key: string) => {
    const request = ++revision.current
    selected.current = key
    setCameraKey(key)
    setDraft(null)
    setLoading(Boolean(key))
    if (!key) {
      setMessage('请先添加并选择摄像头。')
      return
    }
    try {
      const result = await getAiVisionFeatureConfig(feature, key)
      if (request !== revision.current) return
      setDraft(createDraft(result.config as Config))
      setMessage('当前摄像头配置已加载。')
    } catch (error) {
      if (request === revision.current) setMessage(`读取失败：${String(error)}`)
    } finally {
      if (request === revision.current) setLoading(false)
    }
  }, [feature, createDraft])

  const reload = useCallback(async (preferred?: string) => {
    // 保存会广播摄像头变化；等待保存回读完成，避免广播覆盖正在提交的草稿。
    if (busy.current) return
    const request = ++revision.current
    setLoading(true)
    setDraft(null)
    try {
      const items = await getAiVisionCameras(department)
      if (request !== revision.current) return
      setCameras(items)
      await loadConfig(selectFeatureCamera(items, feature, department, preferred ?? selected.current))
    } catch (error) {
      if (request === revision.current) {
        setLoading(false)
        setMessage(`摄像头读取失败：${String(error)}`)
      }
    }
  }, [department, feature, loadConfig])

  useEffect(() => {
    void reload()
    const refresh = () => { void reload() }
    window.addEventListener('aivision:cameras-changed', refresh)
    return () => {
      revision.current += 1
      window.removeEventListener('aivision:cameras-changed', refresh)
    }
  }, [reload])

  const update = (change: (current: Draft) => Draft) => {
    if (isAdmin && !loading && !busy.current) setDraft((current) => current ? change(current) : current)
  }

  const save = async () => {
    if (!draft || !isAdmin || loading || busy.current) return
    const request = revision.current
    const key = cameraKey
    try {
      const payload = buildConfig(draft)
      busy.current = true
      setSaving(true)
      await saveAiVisionFeatureConfig(feature, key, payload)
      if (request !== revision.current) return
      const result = await getAiVisionFeatureConfig(feature, key)
      if (request !== revision.current) return
      setDraft(createDraft(result.config as Config))
      setMessage('配置已保存并重新读取。')
    } catch (error) {
      if (request === revision.current) setMessage(`保存或回读失败：${String(error)}`)
    } finally {
      busy.current = false
      if (request === revision.current) setSaving(false)
    }
  }

  const selectCamera = (key: string) => {
    if (!busy.current && enabledCameras.some((camera) => camera.shm_name === key)) void loadConfig(key)
  }
  return { cameras, enabledCameras, cameraKey, draft, loading, saving, message, update, save, reload, selectCamera }
}
