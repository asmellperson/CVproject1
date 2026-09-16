import { useCallback, useEffect, useMemo, useState } from 'react'
import { Bell } from 'lucide-react'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  DETECTION_CONFIG_CARD_CLASS,
  DetectionConfigCardContent,
  DetectionConfigCardHeader,
} from '@/components/detection/DetectionConfigUi'
import {
  getAiVisionCameras,
  getAiVisionFeatureConfig,
  getAiVisionCameraKey,
  isAiVisionFeatureEnabled,
  saveAiVisionFeatureConfig,
  type AiVisionCamera,
  type AiVisionFeatureConfig,
  type AiVisionFeatureMeta,
} from '@/lib/aivision'
import type { FeatureAlarmConfig } from '@/lib/alarm-config'

async function readFeatures(signal?: AbortSignal): Promise<AiVisionFeatureMeta[]> {
  const response = await fetch('/api/features', { credentials: 'include', signal })
  if (!response.ok) throw new Error(`读取检测功能失败（HTTP ${response.status}）`)
  const payload = await response.json() as { features?: AiVisionFeatureMeta[] }
  return (payload.features || []).filter((feature) => {
    const config = feature.default_config as Record<string, unknown> | undefined
    return Boolean(config && Object.prototype.hasOwnProperty.call(config, 'alarm'))
  })
}

export function AlarmPushManagementSection() {
  const [features, setFeatures] = useState<AiVisionFeatureMeta[]>([])
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [featureName, setFeatureName] = useState('')
  const [cameraKey, setCameraKey] = useState('')
  const [config, setConfig] = useState<AiVisionFeatureConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('正在读取报警配置…')

  const availableCameras = useMemo(
    () => cameras.filter((camera) => featureName && isAiVisionFeatureEnabled(camera, featureName)),
    [cameras, featureName],
  )

  const loadBaseData = useCallback(async () => {
    const controller = new AbortController()
    setLoading(true)
    try {
      const [featureItems, cameraItems] = await Promise.all([
        readFeatures(controller.signal),
        getAiVisionCameras(),
      ])
      setFeatures(featureItems)
      setCameras(cameraItems)
      setFeatureName((current) => current && featureItems.some((item) => item.name === current)
        ? current
        : featureItems[0]?.name || '')
      setMessage(featureItems.length ? '请选择检测功能和摄像头。' : '暂无支持统一报警配置的检测功能。')
    } catch (error) {
      setMessage(`读取失败：${String(error)}`)
    } finally {
      setLoading(false)
    }
    return () => controller.abort()
  }, [])

  useEffect(() => {
    void loadBaseData()
    const refresh = () => { void loadBaseData() }
    window.addEventListener('aivision:cameras-changed', refresh)
    return () => window.removeEventListener('aivision:cameras-changed', refresh)
  }, [loadBaseData])

  useEffect(() => {
    setCameraKey((current) => availableCameras.some((camera) => getAiVisionCameraKey(camera) === current)
      ? current
      : (availableCameras[0] ? getAiVisionCameraKey(availableCameras[0]) : ''))
  }, [availableCameras])

  useEffect(() => {
    let active = true
    setConfig(null)
    if (!featureName || !cameraKey) {
      setMessage(featureName ? '当前检测功能还没有启用摄像头。' : '请选择检测功能。')
      return () => { active = false }
    }
    setLoading(true)
    void getAiVisionFeatureConfig(featureName, cameraKey)
      .then((payload) => {
        if (!active) return
        setConfig(payload.config)
        setMessage('当前报警配置已加载。')
      })
      .catch((error) => {
        if (active) setMessage(`读取失败：${String(error)}`)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [featureName, cameraKey])

  const save = async () => {
    if (!featureName || !cameraKey || !config || saving) return
    setSaving(true)
    try {
      const payload = await saveAiVisionFeatureConfig(featureName, cameraKey, config)
      setConfig(payload.config)
      setMessage('报警推送配置已保存并热更新。')
    } catch (error) {
      setMessage(`保存失败：${String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const selectedFeature = features.find((feature) => feature.name === featureName)
  const selectedCamera = availableCameras.find((camera) => getAiVisionCameraKey(camera) === cameraKey)

  return (
    <div className="space-y-6">
      <Card className={DETECTION_CONFIG_CARD_CLASS}>
        <DetectionConfigCardHeader
          icon={Bell}
          tone="amber"
          title="报警推送配置"
          description="统一维护各检测功能、各摄像头的企业微信与喇叭报警绑定。"
        />
        <DetectionConfigCardContent>
          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label>检测功能</Label>
              <Select value={featureName} onValueChange={setFeatureName} disabled={loading || saving || features.length === 0}>
                <SelectTrigger><SelectValue placeholder="选择检测功能" /></SelectTrigger>
                <SelectContent>
                  {features.map((feature) => <SelectItem key={feature.name} value={feature.name}>{feature.display_name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>摄像头</Label>
              <Select value={cameraKey} onValueChange={setCameraKey} disabled={loading || saving || availableCameras.length === 0}>
                <SelectTrigger><SelectValue placeholder="选择已启用当前功能的摄像头" /></SelectTrigger>
                <SelectContent>
                  {availableCameras.map((camera) => {
                    const key = getAiVisionCameraKey(camera)
                    return <SelectItem key={key} value={key}>{camera.name}</SelectItem>
                  })}
                </SelectContent>
              </Select>
            </div>
          </div>
          <p className="mt-4 text-xs text-slate-500">
            {selectedFeature && selectedCamera
              ? `当前对象：${selectedFeature.display_name} / ${selectedCamera.name}`
              : '只有已经启用该检测功能的摄像头才会出现在这里。'}
          </p>
        </DetectionConfigCardContent>
      </Card>

      {config ? (
        <AlarmPushConfig
          alarm={config.alarm as FeatureAlarmConfig | undefined}
          disabled={loading || saving}
          saving={saving}
          message={message}
          onChange={(alarm) => setConfig((current) => current ? { ...current, alarm } : current)}
          onSave={() => void save()}
        />
      ) : (
        <Card className={DETECTION_CONFIG_CARD_CLASS}>
          <DetectionConfigCardContent>
            <p className="py-8 text-center text-sm text-slate-500">{message}</p>
          </DetectionConfigCardContent>
        </Card>
      )}
    </div>
  )
}

export default AlarmPushManagementSection
