import { useCallback, useEffect, useRef, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { getAiVisionCameras, getAiVisionFeatureConfig, saveAiVisionFeatureConfig, type AiVisionCamera } from '@/lib/aivision'
import { EMPTY_FEATURE_CAMERA_MESSAGE, getEnabledFeatureCameras, selectFeatureCamera } from '@/lib/feature-cameras'
import { AGV_FEATURE, toAgvConfig, toAgvForm, type AgvConfig, type AgvForm } from './config'

type Editor = { cameraKey: string; config: AgvConfig; form: AgvForm }

export function useAgvPersonCheckConfig(department: DepartmentId, isAdmin: boolean) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraKey, setCameraKey] = useState('')
  const [editor, setEditor] = useState<Editor | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('正在读取摄像头...')
  const selectedCamera = useRef('')
  const configRequest = useRef(0)
  const cameraRequest = useRef(0)
  const busy = useRef(false)

  const loadConfig = useCallback(async (key: string) => {
    const request = ++configRequest.current
    selectedCamera.current = key
    setCameraKey(key)
    setEditor(null)
    if (!key) {
      setLoading(false)
      setMessage(EMPTY_FEATURE_CAMERA_MESSAGE)
      return
    }
    setLoading(true)
    setMessage('正在读取当前摄像头配置...')
    try {
      const payload = await getAiVisionFeatureConfig(AGV_FEATURE, key)
      if (request !== configRequest.current) return
      const config = payload.config as AgvConfig
      setEditor({ cameraKey: key, config, form: toAgvForm(config) })
      setMessage(`读取成功：已加载 ${payload.camera.name} 的 AGV 检测配置。`)
    } catch (error) {
      if (request === configRequest.current) setMessage(`读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (request === configRequest.current) setLoading(false)
    }
  }, [])

  const loadCameras = useCallback(async (preferredCamera?: string) => {
    if (busy.current) return
    const request = ++cameraRequest.current
    configRequest.current += 1
    setLoading(true)
    setEditor(null)
    setCameraKey('')
    try {
      const items = (await getAiVisionCameras(department)).filter((camera) => camera.department === department)
      if (request !== cameraRequest.current) return
      setCameras(items)
      const next = selectFeatureCamera(items, AGV_FEATURE, department, preferredCamera ?? selectedCamera.current)
      await loadConfig(next)
    } catch (error) {
      if (request !== cameraRequest.current) return
      setCameras([])
      await loadConfig('')
      setMessage(`摄像头列表读取失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [department, loadConfig])

  useEffect(() => {
    void loadCameras()
    const refresh = () => { void loadCameras() }
    window.addEventListener('aivision:cameras-changed', refresh)
    return () => {
      configRequest.current += 1
      cameraRequest.current += 1
      window.removeEventListener('aivision:cameras-changed', refresh)
    }
  }, [loadCameras])

  const updateForm = (update: (form: AgvForm) => AgvForm) => {
    if (!isAdmin || loading || busy.current) return
    setEditor((current) => current ? { ...current, form: update(current.form) } : current)
    setMessage('配置已修改，确认后请保存。')
  }

  const save = async () => {
    if (!isAdmin || !editor || loading || busy.current || editor.cameraKey !== selectedCamera.current) return
    let nextConfig: AgvConfig
    try {
      nextConfig = toAgvConfig(editor.form, editor.config)
      if (nextConfig.enable && !cameras.find((camera) => camera.shm_name === editor.cameraKey)?.enabled) {
        throw new Error('请先在平台总览启用该摄像头。')
      }
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
      return
    }
    const request = configRequest.current
    const key = editor.cameraKey
    busy.current = true
    setSaving(true)
    setMessage('正在保存 AGV 检测配置...')
    let committed = false
    try {
      await saveAiVisionFeatureConfig(AGV_FEATURE, key, nextConfig)
      committed = true
      if (request !== configRequest.current) return
      const reloaded = await getAiVisionFeatureConfig(AGV_FEATURE, key)
      if (request !== configRequest.current) return
      const confirmed = reloaded.config as AgvConfig
      setEditor({ cameraKey: key, config: confirmed, form: toAgvForm(confirmed) })
      setMessage(`保存成功：已重新读取并确认 ${reloaded.camera.name} 的 AGV 检测配置。`)
    } catch (error) {
      if (request === configRequest.current) {
        setMessage(`${committed ? '配置已保存，但重新读取失败，请重新读取' : '保存失败'}：${error instanceof Error ? error.message : String(error)}`)
      }
    } finally {
      busy.current = false
      if (request === configRequest.current) setSaving(false)
    }
  }

  const enabledCameras = getEnabledFeatureCameras(cameras, AGV_FEATURE, department)
  return { cameras, enabledCameras, cameraKey, form: editor?.form ?? null, loading, saving, message, updateForm, save,
    reload: loadCameras, selectCamera: (key: string) => {
      if (!busy.current && (!key || enabledCameras.some((camera) => camera.shm_name === key))) void loadConfig(key)
    } }
}
