import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '@/auth/useAuth'
import {
  getAiVisionCameras, getAiVisionFeatureConfig, isAiVisionFeatureEnabled, saveAiVisionFeatureConfig,
  type AiVisionCamera, type AiVisionFeatureConfig,
} from '@/lib/aivision'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { FACE_FEATURE } from './api'

const EMPTY_CONFIG: AiVisionFeatureConfig = { enable: false, value: {} }
const EMPTY_FORM = { roi: '[]', detectionThreshold: '', threshold: '', interval: '0.5', cooldown: '30', recordEnabled: true }

export function useRecognitionConfig() {
  const { isAdmin } = useAuth()
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraKey, setCameraKey] = useState('')
  const [configRevision, setConfigRevision] = useState(0)
  const [form, setForm] = useState(EMPTY_FORM)
  const [config, setConfig] = useState(EMPTY_CONFIG)
  const [loading, setLoading] = useState(false)
  const [cameraLoading, setCameraLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('正在读取摄像头…')
  const [loadedKey, setLoadedKey] = useState('')
  const selectedRef = useRef('')
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
    setLoadedKey('')
    setConfig(EMPTY_CONFIG)
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
        roi: JSON.stringify(value.roi_pos ?? []), threshold: String(value.similarity_threshold),
        detectionThreshold: String(value.detection_threshold),
        interval: String(value.cap_interval ?? 0.5), cooldown: String(value.record_cooldown_seconds ?? 30),
        recordEnabled: value.record_enabled !== false,
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
      const items = await getAiVisionCameras()
      if (!mountedRef.current || request !== cameraRequestRef.current) return
      setCameras(items)
      const enabled = items.filter((camera) => isAiVisionFeatureEnabled(camera, FACE_FEATURE))
      if (!enabled.some((camera) => camera.shm_name === selectedRef.current)) selectCamera(enabled[0]?.shm_name || '')
      setConfigRevision((value) => value + 1)
      if (!enabled.length) setMessage('当前功能未添加摄像头，请先添加摄像头。')
    } catch (error) {
      if (mountedRef.current && request === cameraRequestRef.current) setMessage(`摄像头读取失败：${String(error)}`)
    } finally {
      if (mountedRef.current && request === cameraRequestRef.current) setCameraLoading(false)
    }
  }, [selectCamera])

  useEffect(() => {
    mountedRef.current = true
    void refreshCameras()
    const refresh = () => { void refreshCameras() }
    window.addEventListener('aivision:cameras-changed', refresh)
    return () => {
      mountedRef.current = false
      requestRef.current += 1
      cameraRequestRef.current += 1
      window.removeEventListener('aivision:cameras-changed', refresh)
    }
  }, [refreshCameras])

  useEffect(() => {
    if (!cameraLoading) void loadConfig(cameraKey)
  }, [cameraKey, cameraLoading, configRevision, loadConfig])

  const setCameraEnabled = async (key: string, enable: boolean) => {
    if (!isAdmin) return
    setSaving(true)
    try {
      const payload = await getAiVisionFeatureConfig(FACE_FEATURE, key)
      if (enable && !payload.camera.enable) throw new Error('摄像头已停用，请先在平台启用摄像头。')
      await saveAiVisionFeatureConfig(FACE_FEATURE, key, { ...payload.config, enable })
      if (!mountedRef.current) return
      setMessage(enable ? '摄像头已启用人脸身份识别。' : '摄像头已停用人脸身份识别。')
    } catch (error) {
      if (mountedRef.current) setMessage(`操作失败：${String(error)}`)
      throw error
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }

  const save = async () => {
    if (!isAdmin || !cameraKey || loadedKey !== cameraKey || loading || cameraLoading || saving) return
    const key = cameraKey
    try {
      const detectionThreshold = Number(form.detectionThreshold)
      const threshold = Number(form.threshold), interval = Number(form.interval), cooldown = Number(form.cooldown)
      if (![detectionThreshold, threshold, interval, cooldown].every(Number.isFinite) || !form.detectionThreshold.trim() || detectionThreshold < 0 || detectionThreshold > 1 || !form.threshold.trim() || threshold < 0 || threshold > 1 || interval < 0.1 || interval > 1 || cooldown < 1) {
        throw new Error('人脸检测置信度、相似度应在 0～1，采集间隔应在 0.1～1 秒，记录冷却至少 1 秒。')
      }
      const roi = parseNormalizedRoi(form.roi)
      setSaving(true)
      await saveAiVisionFeatureConfig(FACE_FEATURE, key, {
        ...config, value: { ...config.value, roi_pos: roi, detection_threshold: detectionThreshold, similarity_threshold: threshold, cap_interval: interval, record_cooldown_seconds: cooldown, record_enabled: form.recordEnabled },
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
    cameras, cameraKey, form, setForm, message, loading, cameraLoading, saving,
    disabled: !isAdmin || loading || cameraLoading || saving,
    canSave: isAdmin && Boolean(cameraKey) && loadedKey === cameraKey && !loading && !cameraLoading && !saving,
    selectCamera, loadConfig, setCameraEnabled, save,
  }
}
