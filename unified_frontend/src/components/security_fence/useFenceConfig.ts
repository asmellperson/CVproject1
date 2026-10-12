import { useCallback, useEffect, useRef, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { getAiVisionCameras, getAiVisionFeatureConfig, saveAiVisionFeatureConfig, type AiVisionCamera } from '@/lib/aivision'
import { getEnabledFeatureCameras, selectFeatureCamera } from '@/lib/feature-cameras'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { FENCE_FEATURE, NUMBER_FIELDS, type FenceConfig, type NumberField } from './api'

export type FenceDraft = { config: FenceConfig; roi: string; numbers: Record<NumberField, string> }
const draftOf = (config: FenceConfig): FenceDraft => ({ config, roi: JSON.stringify(config.value.roi_pos),
  numbers: Object.fromEntries(NUMBER_FIELDS.map(([key]) => [key, String(config.value[key])])) as Record<NumberField, string> })

export function useFenceConfig(department: DepartmentId, isAdmin: boolean) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraKey, setCameraKey] = useState('')
  const [draft, setDraft] = useState<FenceDraft | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('正在读取摄像头…')
  const revision = useRef(0)
  const selected = useRef('')
  const busy = useRef(false)
  const enabledCameras = getEnabledFeatureCameras(cameras, FENCE_FEATURE, department)

  const loadConfig = useCallback(async (key: string) => {
    const request = ++revision.current
    selected.current = key
    setCameraKey(key)
    setDraft(null)
    setLoading(Boolean(key))
    if (!key) { setMessage('请先添加并选择摄像头。'); return }
    try {
      const result = await getAiVisionFeatureConfig(FENCE_FEATURE, key)
      if (request !== revision.current) return
      setDraft(draftOf(result.config as FenceConfig))
      setMessage('围栏配置已加载。')
    } catch (error) {
      if (request === revision.current) setMessage(`读取失败：${String(error)}`)
    } finally { if (request === revision.current) setLoading(false) }
  }, [])

  const reload = useCallback(async (preferred?: string) => {
    if (busy.current) return
    const request = ++revision.current
    setLoading(true)
    setDraft(null)
    try {
      const items = await getAiVisionCameras(department)
      if (request !== revision.current) return
      setCameras(items)
      await loadConfig(selectFeatureCamera(items, FENCE_FEATURE, department, preferred ?? selected.current))
    } catch (error) {
      if (request === revision.current) { setLoading(false); setMessage(`摄像头读取失败：${String(error)}`) }
    }
  }, [department, loadConfig])

  useEffect(() => {
    void reload()
    const refresh = () => { void reload() }
    window.addEventListener('aivision:cameras-changed', refresh)
    return () => { revision.current += 1; window.removeEventListener('aivision:cameras-changed', refresh) }
  }, [reload])

  const update = (change: (current: FenceDraft) => FenceDraft) => {
    if (isAdmin && !loading && !busy.current) setDraft((current) => current ? change(current) : current)
  }
  const save = async () => {
    if (!draft || !isAdmin || loading || busy.current) return
    const request = revision.current
    const key = cameraKey
    try {
      const value = { ...draft.config.value, roi_pos: parseNormalizedRoi(draft.roi) }
      for (const [field, label, min, max, step] of NUMBER_FIELDS) {
        const number = Number(draft.numbers[field])
        if (!draft.numbers[field].trim() || !Number.isFinite(number) || number < min || (max !== undefined && number > max)
          || (['confirmation_frames', 'min_face_size'].includes(field) && step === 1 && !Number.isInteger(number))) throw new Error(`${label}超出有效范围`)
        value[field] = number
      }
      if (value.unknown_similarity_threshold >= value.similarity_threshold) throw new Error('未匹配判定阈值必须小于身份匹配阈值')
      busy.current = true
      setSaving(true)
      await saveAiVisionFeatureConfig(FENCE_FEATURE, key, { ...draft.config, value })
      if (request !== revision.current) return
      const result = await getAiVisionFeatureConfig(FENCE_FEATURE, key)
      if (request !== revision.current) return
      setDraft(draftOf(result.config as FenceConfig))
      setMessage('围栏配置已保存并重新读取。')
    } catch (error) { if (request === revision.current) setMessage(`保存或回读失败：${String(error)}`) }
    finally { busy.current = false; if (request === revision.current) setSaving(false) }
  }
  return { cameras, enabledCameras, cameraKey, draft, loading, saving, message, update, save, reload,
    selectCamera: (key: string) => { if (!busy.current && enabledCameras.some((camera) => camera.shm_name === key)) void loadConfig(key) } }
}
