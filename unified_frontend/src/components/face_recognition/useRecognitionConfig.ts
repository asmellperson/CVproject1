import type { DepartmentId } from '@/auth/permissions'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '@/auth/useAuth'
import {
  getAiVisionCameras, getAiVisionFeatureConfig, saveAiVisionFeatureConfig,
  type AiVisionCamera, type AiVisionFeatureConfig,
} from '@/lib/aivision'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import type { NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
import { FACE_FEATURE, getFacePersons, updateFacePerson, type FacePersonPage } from './api'

const EMPTY_FORM = { roi: '', detectionThreshold: '', threshold: '', interval: '', cooldown: '', recordEnabled: false, alarmInterval: '' }

export function useFacePersons() {
  const { isAdmin } = useAuth()
  const [query, setQuery] = useState<Parameters<typeof getFacePersons>[0]>({ page: 1, page_size: 20 })
  const [result, setResult] = useState<FacePersonPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const requestRef = useRef<AbortController | null>(null)
  const mutationRef = useRef<AbortController | null>(null)

  const loadPersons = useCallback(async () => {
    requestRef.current?.abort()
    const controller = new AbortController()
    requestRef.current = controller
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const page = await getFacePersons(query, controller.signal)
      if (controller.signal.aborted) return false
      const lastPage = Math.max(1, Math.ceil(page.total / page.page_size))
      if (query.page > lastPage) {
        setQuery((current) => ({ ...current, page: lastPage }))
        return false
      }
      setResult(page)
      return true
    } catch (cause) {
      if (!controller.signal.aborted) {
        setResult(null)
        setError(`人员列表读取失败：${String(cause)}`)
      }
      return false
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [query])

  useEffect(() => {
    void loadPersons()
    return () => { requestRef.current?.abort() }
  }, [loadPersons])

  useEffect(() => () => { mutationRef.current?.abort() }, [])

  const setPersonAllowed = async (personId: number, isAllowed: boolean) => {
    if (!isAdmin || mutationRef.current || loading) return
    const controller = new AbortController()
    mutationRef.current = controller
    setSavingId(personId)
    setError('')
    setMessage('')
    try {
      await updateFacePerson(personId, isAllowed, controller.signal)
      if (controller.signal.aborted) return
      if (await loadPersons()) setMessage('通行权限已保存，人员状态已重新读取。')
    } catch (cause) {
      if (!controller.signal.aborted) setError(`通行权限保存失败：${String(cause)}`)
    } finally {
      if (!controller.signal.aborted) {
        mutationRef.current = null
        setSavingId(null)
      }
    }
  }

  return { isAdmin, query, setQuery, result, loading, savingId, error, message, loadPersons, setPersonAllowed }
}

export function useRecognitionConfig(department: DepartmentId) {
  const { isAdmin } = useAuth()
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraKey, setCameraKey] = useState('')
  const [configRevision, setConfigRevision] = useState(0)
  const [form, setForm] = useState(EMPTY_FORM)
  const [config, setConfig] = useState<AiVisionFeatureConfig | null>(null)
  const [hornError, setHornError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [cameraLoading, setCameraLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('正在读取摄像头…')
  const [loadedKey, setLoadedKey] = useState('')
  const selectedRef = useRef('')
  const configLoadRef = useRef<{ key: string; revision: number } | null>(null)
  const requestRef = useRef(0)
  const cameraRequestRef = useRef(0)
  const mountedRef = useRef(true)

  const selectCamera = useCallback((key: string) => {
    if (selectedRef.current === key) return
    selectedRef.current = key
    requestRef.current += 1
    setLoadedKey('')
    setCameraKey(key)
  }, [])

  const loadConfig = useCallback(async (key: string) => {
    const request = ++requestRef.current
    configLoadRef.current = { key, revision: cameraRequestRef.current }
    setLoadedKey('')
    setConfig(null)
    setHornError(null)
    setForm(EMPTY_FORM)
    setLoading(Boolean(key))
    if (!key) {
      setMessage('请先添加摄像头。')
      return
    }
    try {
      const payload = await getAiVisionFeatureConfig(FACE_FEATURE, key)
      if (!mountedRef.current || request !== requestRef.current || key !== selectedRef.current) return
      const value = payload.config.value
      setConfig(payload.config)
      setForm({
        roi: JSON.stringify(value.roi_pos), threshold: String(value.similarity_threshold),
        detectionThreshold: String(value.detection_threshold),
        interval: String(value.cap_interval), cooldown: String(value.record_cooldown_seconds),
        recordEnabled: Boolean(value.record_enabled), alarmInterval: String(value.alarm_interval),
      })
      setLoadedKey(key)
      setMessage('当前摄像头配置已加载。')
    } catch (error) {
      if (mountedRef.current && request === requestRef.current) setMessage(`读取失败：${String(error)}`)
    } finally {
      if (mountedRef.current && request === requestRef.current) setLoading(false)
    }
  }, [])

  const refreshCameras = useCallback(async () => {
    const request = ++cameraRequestRef.current
    requestRef.current += 1
    setLoadedKey('')
    setCameraLoading(true)
    try {
      const items = await getAiVisionCameras(department)
      if (!mountedRef.current || request !== cameraRequestRef.current) return
      setCameras(items)
      if (!items.some((camera) => camera.shm_name === selectedRef.current)) selectCamera(items[0]?.shm_name || '')
      setConfigRevision((value) => value + 1)
      if (!selectedRef.current) setMessage('当前事业部暂未配置摄像头')
    } finally {
      if (mountedRef.current && request === cameraRequestRef.current) setCameraLoading(false)
    }
  }, [department, selectCamera])

  useEffect(() => {
    mountedRef.current = true
    let active = true
    const refresh = () => {
      void refreshCameras().catch((error) => {
        if (active) setMessage(`摄像头读取失败：${String(error)}`)
      })
    }
    refresh()
    window.addEventListener('aivision:cameras-changed', refresh)
    return () => {
      active = false
      mountedRef.current = false
      requestRef.current += 1
      cameraRequestRef.current += 1
      window.removeEventListener('aivision:cameras-changed', refresh)
    }
  }, [refreshCameras])

  useEffect(() => {
    // onConfigCopied 已主动读取本轮最终配置时，列表刷新不再重复请求或覆盖目标。
    const loaded = configLoadRef.current
    if (!cameraLoading && (loaded?.key !== cameraKey || loaded.revision !== cameraRequestRef.current)) void loadConfig(cameraKey)
  }, [cameraKey, cameraLoading, configRevision, loadConfig])

  const setAlarm = (alarm: NormalizedFeatureAlarmConfig) => {
    setConfig((current) => current && ({ ...current, alarm }))
  }

  const save = async () => {
    if (!isAdmin || !config?.alarm || !cameraKey || loadedKey !== cameraKey || loading || cameraLoading || saving) return
    const key = cameraKey
    try {
      const detectionThreshold = Number(form.detectionThreshold)
      const threshold = Number(form.threshold), interval = Number(form.interval), cooldown = Number(form.cooldown)
      const alarmInterval = Number(form.alarmInterval)
      if (![detectionThreshold, threshold, interval, cooldown].every(Number.isFinite) || !form.detectionThreshold.trim() || detectionThreshold < 0 || detectionThreshold > 1 || !form.threshold.trim() || threshold < 0 || threshold > 1 || interval < 0.1 || interval > 1 || cooldown < 1) {
        throw new Error('人脸检测置信度、相似度应在 0～1，采集间隔应在 0.1～1 秒，记录冷却至少 1 秒。')
      }
      if (!form.alarmInterval.trim() || !Number.isFinite(alarmInterval) || alarmInterval <= 0) {
        throw new Error('报警间隔必须大于 0 秒。')
      }
      if (hornError) throw new Error(hornError)
      const roi = parseNormalizedRoi(form.roi)
      setSaving(true)
      await saveAiVisionFeatureConfig(FACE_FEATURE, key, {
        ...config, value: { ...config.value, roi_pos: roi, detection_threshold: detectionThreshold, similarity_threshold: threshold, cap_interval: interval, record_cooldown_seconds: cooldown, record_enabled: form.recordEnabled, alarm_interval: alarmInterval },
      })
      if (mountedRef.current && selectedRef.current === key) {
        setMessage('人脸身份识别配置已保存。')
      }
    } catch (error) {
      if (mountedRef.current) setMessage(`保存失败：${String(error)}`)
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }
  return {
    cameras, cameraKey, form, setForm, config, setAlarm, hornError, setHornError, message, loading, cameraLoading, saving,
    disabled: !isAdmin || loading || cameraLoading || saving,
    canSave: isAdmin && Boolean(config?.alarm) && Boolean(cameraKey) && loadedKey === cameraKey && !loading && !cameraLoading && !saving,
    selectCamera, loadConfig, refreshCameras, save,
  }
}
