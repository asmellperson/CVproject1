import { useEffect, useState } from 'react'
import { Bell, Box, Camera, MousePointer2, RefreshCw, Save, SlidersHorizontal, UsersRound, Waypoints } from 'lucide-react'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { normalizeFeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import { AiVisionModelConfig } from '@/components/AiVisionModelConfig'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { getAiVisionCameras, isAiVisionFeatureEnabled, type AiVisionCamera } from '@/lib/aivision'
import { useAuth } from '@/auth/useAuth'

type LogisticsSinglePersonElectronicsElectricianConfig = {
  enable: boolean
  value: {
    roi_pos: number[][]
    cap_interval?: number
    alarm_interval?: number
    CONF_THRESHOLD?: number
    IOU_THR?: number
    empty_grace_seconds?: number
    multi_grace_seconds?: number
  }
  alarm: NormalizedFeatureAlarmConfig
}

type LogisticsSinglePersonElectronicsElectricianConfigResponse = {
  camera_id: number
  name: string
  shm_name: string
  camera_enable: boolean
  detect_logistics_single_person_electronics_electrician: LogisticsSinglePersonElectronicsElectricianConfig
}

const defaultForm = {
  cameraName: '',
  roiPos: '[]',
  confidenceThreshold: '0.3',
  iouThreshold: '0.3',
  emptyGraceSeconds: '2.0',
  multiGraceSeconds: '1.0',
  alarmInterval: '5.0',
}

const defaultLogisticsSinglePersonElectronicsElectricianConfig: LogisticsSinglePersonElectronicsElectricianConfig = {
  enable: false,
  value: {
    roi_pos: [],
    cap_interval: 0.2,
    alarm_interval: 5.0,
    CONF_THRESHOLD: 0.3,
    IOU_THR: 0.3,
    empty_grace_seconds: 2.0,
    multi_grace_seconds: 1.0,
  },
  alarm: {
    horn: { enable: false, parm: {} },
    sql: { enable: false, parm: {} },
    wechat: { enable: false, parm: { user: '' } },
  },
}

function formatJson(value: unknown) {
  return JSON.stringify(value || [])
}

function toForm(payload: LogisticsSinglePersonElectronicsElectricianConfigResponse) {
  const value = payload.detect_logistics_single_person_electronics_electrician.value
  return {
    cameraName: payload.shm_name,
    roiPos: formatJson(value.roi_pos),
    confidenceThreshold: String(value.CONF_THRESHOLD ?? 0.3),
    iouThreshold: String(value.IOU_THR ?? 0.3),
    emptyGraceSeconds: String(value.empty_grace_seconds ?? 2.0),
    multiGraceSeconds: String(value.multi_grace_seconds ?? 1.0),
    alarmInterval: String(value.alarm_interval ?? 5.0),
  }
}

async function requestLogisticsSinglePersonElectronicsElectricianConfig(shmName: string, init?: RequestInit) {
  const response = await fetch(`/api/ai/logistics-single-person-electronics-electrician-config/${encodeURIComponent(shmName)}`, { ...init, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${response.status} ${response.statusText}${detail ? ` ${detail}` : ''}`)
  }
  const payload = (await response.json()) as LogisticsSinglePersonElectronicsElectricianConfigResponse | LogisticsSinglePersonElectronicsElectricianConfig
  if ('detect_logistics_single_person_electronics_electrician' in payload) return payload
  return {
    camera_id: 0,
    name: shmName,
    shm_name: shmName,
    camera_enable: true,
    detect_logistics_single_person_electronics_electrician: payload,
  }
}

export function LogisticsSinglePersonElectronicsElectricianDetectionSection() {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [config, setConfig] = useState<LogisticsSinglePersonElectronicsElectricianConfig>(defaultLogisticsSinglePersonElectronicsElectricianConfig)
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [message, setMessage] = useState('正在读取当前配置...')
  const [loading, setLoading] = useState(false)
  const [cameraLoading, setCameraLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [cameraAction, setCameraAction] = useState(false)

  const getCameraDisplayName = (shmName: string, fallback?: string, source: AiVisionCamera[] = cameras) => {
    const key = shmName.trim()
    return source.find((camera) => camera.shm_name === key || camera.id === key)?.name || fallback || key
  }

  const loadConfig = async (cameraName = form.cameraName, source: AiVisionCamera[] = cameras) => {
    const shmName = cameraName.trim()
    if (!shmName) {
      setMessage('读取失败：请先选择摄像头。')
      return
    }

    setLoading(true)
    setMessage('正在读取当前配置...')
    try {
      const payload = await requestLogisticsSinglePersonElectronicsElectricianConfig(shmName)
      setConfig(payload.detect_logistics_single_person_electronics_electrician)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的物流通道单人检测（电子电工）配置。`)
    } catch (error) {
      setMessage(`读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setLoading(false)
    }
  }

  const loadCameras = async () => {
    setCameraLoading(true)
    try {
      const items = await getAiVisionCameras()
      setCameras(items)
      const enabledCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_logistics_single_person_electronics_electrician'))
      const nextCamera = enabledCamera?.shm_name || ''
      if (items.length === 0) {
        setMessage('未获取到可用摄像头，请先在 AiVision 中配置。')
        return
      }
      if (!nextCamera) {
        setForm((prev) => ({ ...prev, cameraName: '' }))
        setMessage('当前物流通道单人检测（电子电工）未添加摄像头，请先添加摄像头。')
        return
      }
      setForm((prev) => ({ ...prev, cameraName: nextCamera }))
      await loadConfig(nextCamera, items)
    } catch (error) {
      setMessage(`摄像头列表读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraLoading(false)
    }
  }

  useEffect(() => {
    loadCameras()
    const refreshCameras = () => {
      loadCameras()
    }
    window.addEventListener('aivision:cameras-changed', refreshCameras)
    return () => window.removeEventListener('aivision:cameras-changed', refreshCameras)
  }, [])

  const refreshCameraList = async () => {
    const items = await getAiVisionCameras()
    setCameras(items)
    return items
  }

  const addCameraToFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在添加摄像头并启用物流通道单人检测（电子电工）...')
    try {
      const payload = await requestLogisticsSinglePersonElectronicsElectricianConfig(cameraName)
      await requestLogisticsSinglePersonElectronicsElectricianConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_logistics_single_person_electronics_electrician, enable: true }),
      })
      await refreshCameraList()
      await loadConfig(cameraName)
      setMessage(`添加成功：${cameraName} 已启用物流通道单人检测（电子电工）。`)
    } catch (error) {
      setMessage(`添加失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraAction(false)
    }
  }

  const removeCameraFromFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在停用该摄像头的物流通道单人检测（电子电工）...')
    try {
      const payload = await requestLogisticsSinglePersonElectronicsElectricianConfig(cameraName)
      await requestLogisticsSinglePersonElectronicsElectricianConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_logistics_single_person_electronics_electrician, enable: false }),
      })
      const items = await refreshCameraList()
      const nextCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_logistics_single_person_electronics_electrician'))?.shm_name || ''
      if (form.cameraName === cameraName && nextCamera) {
        await loadConfig(nextCamera)
      } else if (form.cameraName === cameraName) {
        setConfig(defaultLogisticsSinglePersonElectronicsElectricianConfig)
        setForm({ ...defaultForm, cameraName: '' })
      }
      setMessage(`停用成功：${cameraName} 已关闭物流通道单人检测（电子电工）。`)
    } catch (error) {
      setMessage(`停用失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraAction(false)
    }
  }

  const saveConfig = async () => {
    const shmName = form.cameraName.trim()
    if (!shmName) {
      setMessage('保存失败：请先选择摄像头。')
      return
    }
    if (!isAdmin) {
      setMessage('当前账号为 viewer，只能查看配置。')
      return
    }

    let roiPos: unknown
    try {
      roiPos = JSON.parse(form.roiPos || '[]')
    } catch {
      setMessage('保存失败：ROI 区域坐标必须是合法 JSON。')
      return
    }

    if (!Array.isArray(roiPos)) {
      setMessage('保存失败：ROI 区域坐标必须是数组。')
      return
    }

    const confidenceThreshold = Number(form.confidenceThreshold)
    const iouThreshold = Number(form.iouThreshold)
    const emptyGraceSeconds = Number(form.emptyGraceSeconds)
    const multiGraceSeconds = Number(form.multiGraceSeconds)
    const alarmInterval = Number(form.alarmInterval)

    if (
      !Number.isFinite(confidenceThreshold) ||
      !Number.isFinite(iouThreshold) ||
      !Number.isFinite(emptyGraceSeconds) ||
      !Number.isFinite(multiGraceSeconds) ||
      !Number.isFinite(alarmInterval)
    ) {
      setMessage('保存失败：置信度、IOU、缓冲时间和告警间隔必须是数字。')
      return
    }

    const nextConfig: LogisticsSinglePersonElectronicsElectricianConfig = {
      ...config,
      enable: true,
      value: {
        ...config.value,
        roi_pos: roiPos as number[][],
        CONF_THRESHOLD: confidenceThreshold,
        IOU_THR: iouThreshold,
        empty_grace_seconds: emptyGraceSeconds,
        multi_grace_seconds: multiGraceSeconds,
        alarm_interval: alarmInterval,
      },
      alarm: config.alarm || defaultLogisticsSinglePersonElectronicsElectricianConfig.alarm,
    }

    setSaving(true)
    setMessage('正在保存物流通道单人检测（电子电工）配置...')
    try {
      await requestLogisticsSinglePersonElectronicsElectricianConfig(shmName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nextConfig),
      })
      setMessage('保存成功，正在重新读取当前摄像头配置...')
      const reloaded = await requestLogisticsSinglePersonElectronicsElectricianConfig(shmName)
      setConfig(reloaded.detect_logistics_single_person_electronics_electrician)
      setForm(toForm(reloaded))
      const items = await refreshCameraList()
      setMessage(`保存成功：已重新读取并确认 ${getCameraDisplayName(reloaded.shm_name, reloaded.name, items)} 的物流通道单人检测（电子电工）配置。`)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_logistics_single_person_electronics_electrician'))

  return (
    <div className="space-y-6">
      <Tabs defaultValue="monitor" className="space-y-6">
        <TabsList className="grid h-auto w-full max-w-md grid-cols-2 p-1">
          <TabsTrigger value="monitor" className="gap-2 py-2">
            <UsersRound className="h-4 w-4" />
            实时监控
          </TabsTrigger>
          <TabsTrigger value="config" className="gap-2 py-2">
            <Waypoints className="h-4 w-4" />
            配置管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="monitor" className="space-y-6">
          <AiVisionMonitor title="物流通道单人检测（电子电工）监控" feature="detect_logistics_single_person_electronics_electrician" />
        </TabsContent>

        <TabsContent value="config" className="space-y-6">
          <Tabs defaultValue="camera" className="space-y-6">
            <TabsList className="grid h-auto w-full max-w-4xl grid-cols-2 p-1 sm:grid-cols-3 lg:grid-cols-5">
              <TabsTrigger value="camera" className="gap-2 py-2">
                <Camera className="h-4 w-4" />
                摄像头管理
              </TabsTrigger>
              <TabsTrigger value="params" className="gap-2 py-2">
                <SlidersHorizontal className="h-4 w-4" />
                参数配置
              </TabsTrigger>
              <TabsTrigger value="roi" className="gap-2 py-2">
                <MousePointer2 className="h-4 w-4" />
                ROI绘制
              </TabsTrigger>
              <TabsTrigger value="model" className="gap-2 py-2">
                <Box className="h-4 w-4" />
                模型配置
              </TabsTrigger>
              <TabsTrigger value="alarm" className="gap-2 py-2">
                <Bell className="h-4 w-4" />
                报警推送
              </TabsTrigger>
            </TabsList>

            <TabsContent value="camera" className="space-y-6">
              <FeatureCameraManager
                cameras={cameras}
                feature="detect_logistics_single_person_electronics_electrician"
                currentCameraName={form.cameraName}
                disabled={!isAdmin || cameraLoading || loading || saving || cameraAction}
                onSelectCamera={(cameraName) => {
                  setForm((prev) => ({ ...prev, cameraName }))
                  loadConfig(cameraName)
                }}
                onAddCamera={addCameraToFeature}
                onRemoveCamera={removeCameraFromFeature}
              />
            </TabsContent>

            <TabsContent value="roi" className="space-y-6">
              <AiVisionRoiEditor
                title="物流通道单人检测（电子电工） ROI 绘制"
                cameraKey={form.cameraName}
                roiJson={form.roiPos}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(roiPos) => setForm((prev) => ({ ...prev, roiPos }))}
                onSave={saveConfig}
              />
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <Card className="border-slate-200 bg-white/95">
                <CardHeader className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
                  <CardTitle className="text-lg">配置表单</CardTitle>
                  <Badge variant="outline" className="border-slate-300 text-slate-600">
                    AiVision detect_logistics_single_person_electronics_electrician
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid gap-5 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="logistics-single-person-camera">摄像头名称</Label>
                      <Select
                        value={form.cameraName}
                        onValueChange={(value) => {
                          setForm((prev) => ({ ...prev, cameraName: value }))
                          loadConfig(value)
                        }}
                        disabled={cameraLoading || loading || saving || cameraAction || featureCameras.length === 0}
                      >
                        <SelectTrigger id="logistics-single-person-camera" className="w-full">
                          <SelectValue placeholder={cameraLoading ? '正在读取摄像头' : '选择摄像头'} />
                        </SelectTrigger>
                        <SelectContent>
                          {featureCameras.map((camera) => (
                            <SelectItem key={camera.id} value={camera.shm_name}>
                              {camera.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="logistics-single-person-confidence">人员置信度阈值</Label>
                      <Input
                        id="logistics-single-person-confidence"
                        value={form.confidenceThreshold}
                        onChange={(event) => setForm((prev) => ({ ...prev, confidenceThreshold: event.target.value }))}
                        placeholder="0.3"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="logistics-single-person-iou">IOU 阈值</Label>
                      <Input
                        id="logistics-single-person-iou"
                        value={form.iouThreshold}
                        onChange={(event) => setForm((prev) => ({ ...prev, iouThreshold: event.target.value }))}
                        placeholder="0.3"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="logistics-single-person-empty-grace">无人缓冲时间（秒）</Label>
                      <Input
                        id="logistics-single-person-empty-grace"
                        value={form.emptyGraceSeconds}
                        onChange={(event) => setForm((prev) => ({ ...prev, emptyGraceSeconds: event.target.value }))}
                        placeholder="2.0"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="logistics-single-person-multi-grace">多人缓冲时间（秒）</Label>
                      <Input
                        id="logistics-single-person-multi-grace"
                        value={form.multiGraceSeconds}
                        onChange={(event) => setForm((prev) => ({ ...prev, multiGraceSeconds: event.target.value }))}
                        placeholder="1.0"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="logistics-single-person-interval">告警间隔</Label>
                      <Input
                        id="logistics-single-person-interval"
                        value={form.alarmInterval}
                        onChange={(event) => setForm((prev) => ({ ...prev, alarmInterval: event.target.value }))}
                        placeholder="5.0"
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="logistics-single-person-roi">物流通道单人检测（电子电工） ROI 区域坐标</Label>
                    <Textarea
                      id="logistics-single-person-roi"
                      value={form.roiPos}
                      onChange={(event) => setForm((prev) => ({ ...prev, roiPos: event.target.value }))}
                      rows={6}
                      placeholder="[]"
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="text-sm text-slate-600">{message}</div>
                    <div className="flex gap-2">
                      <Button variant="outline" className="gap-2" onClick={() => loadConfig()} disabled={loading || saving || !form.cameraName}>
                        <RefreshCw className="h-4 w-4" />
                        {loading ? '读取中' : '重新读取'}
                      </Button>
                      <Button className="gap-2" onClick={saveConfig} disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}>
                        <Save className="h-4 w-4" />
                        {saving ? '保存中' : '保存配置'}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="model" className="space-y-6">
              <AiVisionModelConfig requiredModels={['yolo_human']} />
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <AlarmPushConfig
                alarm={config.alarm}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setConfig((prev) => ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
                onSave={saveConfig}
              />
            </TabsContent>
          </Tabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default LogisticsSinglePersonElectronicsElectricianDetectionSection
