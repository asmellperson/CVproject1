import { useEffect, useState } from 'react'
import { Bell, Box, Camera, Clock3, MousePointer2, RefreshCw, Save, SlidersHorizontal, Waypoints } from 'lucide-react'
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

type HumanConfig = {
  enable: boolean
  value: {
    cap_interval?: number
    alarm_interval?: number
    CONF_THRESHOLD?: number
    IOU_THR?: number
    MAX_LOST?: number
    MAX_TIME?: number
    roi_pos?: unknown[]
    region?: number[]
    MIN_BOX_AREA?: number
    ASPECT_RATIO_RANGE?: number[]
  }
  alarm: NormalizedFeatureAlarmConfig
}

type HumanConfigResponse = {
  camera_id: number
  name: string
  shm_name: string
  camera_enable: boolean
  detect_human: HumanConfig
}

const defaultForm = {
  cameraName: '',
  roiPos: '[100,100,500,500]',
  region: '[100,100,500,500]',
  confidenceThreshold: '0.3',
  iouThreshold: '0.3',
  maxTime: '10',
  maxLost: '5',
  minBoxArea: '0',
  aspectRatioRange: '[0,10]',
  alarmInterval: '5.0',
}

const defaultHumanConfig: HumanConfig = {
  enable: false,
  value: {
    cap_interval: 0.1,
    alarm_interval: 5.0,
    CONF_THRESHOLD: 0.3,
    IOU_THR: 0.3,
    MAX_LOST: 5,
    MAX_TIME: 10,
    roi_pos: [100, 100, 500, 500],
    region: [100, 100, 500, 500],
    MIN_BOX_AREA: 0,
    ASPECT_RATIO_RANGE: [0, 10],
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

function bboxFromRoiJson(roiJson: string, fallback = '[100,100,500,500]') {
  try {
    const parsed = JSON.parse(roiJson)
    const polygon = Array.isArray(parsed?.[0]?.[0]) ? parsed[0] : parsed
    if (!Array.isArray(polygon)) return fallback
    const points = polygon.filter((point: unknown) => Array.isArray(point) && point.length >= 2) as unknown[][]
    if (!points.length) return fallback
    const xs = points.map((point) => Number(point[0])).filter(Number.isFinite)
    const ys = points.map((point) => Number(point[1])).filter(Number.isFinite)
    if (!xs.length || !ys.length) return fallback
    return JSON.stringify([
      Math.round(Math.min(...xs)),
      Math.round(Math.min(...ys)),
      Math.round(Math.max(...xs)),
      Math.round(Math.max(...ys)),
    ])
  } catch {
    return fallback
  }
}

function toForm(payload: HumanConfigResponse) {
  const value = payload.detect_human.value
  return {
    cameraName: payload.shm_name,
    roiPos: formatJson(value.roi_pos ?? [100, 100, 500, 500]),
    region: formatJson(value.region ?? [100, 100, 500, 500]),
    confidenceThreshold: String(value.CONF_THRESHOLD ?? 0.3),
    iouThreshold: String(value.IOU_THR ?? 0.3),
    maxTime: String(value.MAX_TIME ?? 10),
    maxLost: String(value.MAX_LOST ?? 5),
    minBoxArea: String(value.MIN_BOX_AREA ?? 0),
    aspectRatioRange: formatJson(value.ASPECT_RATIO_RANGE ?? [0, 10]),
    alarmInterval: String(value.alarm_interval ?? 5.0),
  }
}

async function requestHumanConfig(shmName: string, init?: RequestInit) {
  const response = await fetch(`/api/ai/human-config/${encodeURIComponent(shmName)}`, { ...init, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${response.status} ${response.statusText}${detail ? ` ${detail}` : ''}`)
  }
  const payload = (await response.json()) as HumanConfigResponse | HumanConfig
  if ('detect_human' in payload) return payload
  return {
    camera_id: 0,
    name: shmName,
    shm_name: shmName,
    camera_enable: true,
    detect_human: payload,
  }
}

export function HumanDetectionSection() {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [humanConfig, setHumanConfig] = useState<HumanConfig>(defaultHumanConfig)
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
      const payload = await requestHumanConfig(shmName)
      setHumanConfig(payload.detect_human)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的人员逗留检测配置。`)
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
      const enabledCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_human'))
      const nextCamera = enabledCamera?.shm_name || ''
      if (items.length === 0) {
        setMessage('未获取到可用摄像头，请先在 AiVision 中配置。')
        return
      }
      if (!nextCamera) {
        setForm((prev) => ({ ...prev, cameraName: '' }))
        setMessage('当前人员逗留检测未添加摄像头，请先添加摄像头。')
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
    setMessage('正在添加摄像头并启用人员逗留检测...')
    try {
      const payload = await requestHumanConfig(cameraName)
      await requestHumanConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_human, enable: true }),
      })
      await refreshCameraList()
      await loadConfig(cameraName)
      setMessage(`添加成功：${cameraName} 已启用人员逗留检测。`)
    } catch (error) {
      setMessage(`添加失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraAction(false)
    }
  }

  const removeCameraFromFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在停用该摄像头的人员逗留检测...')
    try {
      const payload = await requestHumanConfig(cameraName)
      await requestHumanConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_human, enable: false }),
      })
      const items = await refreshCameraList()
      const nextCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_human'))?.shm_name || ''
      if (form.cameraName === cameraName && nextCamera) {
        await loadConfig(nextCamera)
      } else if (form.cameraName === cameraName) {
        setHumanConfig(defaultHumanConfig)
        setForm({ ...defaultForm, cameraName: '' })
      }
      setMessage(`停用成功：${cameraName} 已关闭人员逗留检测。`)
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

    let roiPos: unknown[]
    let region: number[]
    let aspectRatioRange: number[]
    try {
      const parsedRoi = JSON.parse(form.roiPos)
      const parsedRegion = JSON.parse(form.region)
      const parsedAspect = JSON.parse(form.aspectRatioRange)
      if (!Array.isArray(parsedRoi) || !Array.isArray(parsedRegion) || !Array.isArray(parsedAspect)) {
        throw new Error('ROI、关注区域和宽高比范围必须是数组')
      }
      roiPos = parsedRoi
      region = parsedRegion
      aspectRatioRange = parsedAspect
    } catch (error) {
      setMessage(`保存失败：数组字段不是合法 JSON。${error instanceof Error ? error.message : ''}`)
      return
    }

    const confidenceThreshold = Number(form.confidenceThreshold)
    const iouThreshold = Number(form.iouThreshold)
    const maxTime = Number(form.maxTime)
    const maxLost = Number(form.maxLost)
    const minBoxArea = Number(form.minBoxArea)
    const alarmInterval = Number(form.alarmInterval)
    if (
      !Number.isFinite(confidenceThreshold) ||
      !Number.isFinite(iouThreshold) ||
      !Number.isFinite(maxTime) ||
      !Number.isFinite(maxLost) ||
      !Number.isFinite(minBoxArea) ||
      !Number.isFinite(alarmInterval)
    ) {
      setMessage('保存失败：置信度、IoU、逗留时间、丢失帧数、最小面积和告警间隔必须是数字。')
      return
    }

    const nextConfig: HumanConfig = {
      ...humanConfig,
      enable: true,
      value: {
        ...humanConfig.value,
        roi_pos: roiPos,
        region,
        CONF_THRESHOLD: confidenceThreshold,
        IOU_THR: iouThreshold,
        MAX_TIME: maxTime,
        MAX_LOST: maxLost,
        MIN_BOX_AREA: minBoxArea,
        ASPECT_RATIO_RANGE: aspectRatioRange,
        alarm_interval: alarmInterval,
      },
      alarm: humanConfig.alarm || defaultHumanConfig.alarm,
    }

    setSaving(true)
    setMessage('正在保存配置...')
    try {
      const payload = await requestHumanConfig(shmName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nextConfig),
      })
      setHumanConfig(payload.detect_human)
      setForm(toForm(payload))
      const items = await refreshCameraList()
      setMessage(`保存成功：${getCameraDisplayName(payload.shm_name, payload.name, items)} 的人员逗留检测配置已更新。`)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_human'))

  return (
    <div className="space-y-6">
      <Tabs defaultValue="monitor" className="space-y-6">
        <TabsList className="grid h-auto w-full max-w-md grid-cols-2 p-1">
          <TabsTrigger value="monitor" className="gap-2 py-2">
            <Clock3 className="h-4 w-4" />
            实时监控
          </TabsTrigger>
          <TabsTrigger value="config" className="gap-2 py-2">
            <Waypoints className="h-4 w-4" />
            配置管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="monitor" className="space-y-6">
          <AiVisionMonitor title="人员逗留检测监控" feature="detect_human" />
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
                feature="detect_human"
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
                title="人体逗留 ROI 绘制"
                cameraKey={form.cameraName}
                roiJson={form.roiPos}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(roiPos) => setForm((prev) => ({ ...prev, roiPos, region: bboxFromRoiJson(roiPos, prev.region) }))}
                onSave={saveConfig}
              />
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <Card className="border-slate-200 bg-white/95">
              <CardHeader className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
                <CardTitle className="text-lg">配置表单</CardTitle>
                <Badge variant="outline" className="border-slate-300 text-slate-600">
                  AiVision detect_human
                </Badge>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="human-camera">摄像头名称</Label>
                    <Select
                      value={form.cameraName}
                      onValueChange={(value) => {
                        setForm((prev) => ({ ...prev, cameraName: value }))
                        loadConfig(value)
                      }}
                      disabled={cameraLoading || loading || saving || cameraAction || featureCameras.length === 0}
                    >
                      <SelectTrigger id="human-camera" className="w-full">
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
                    <Label htmlFor="human-confidence">人体置信度阈值</Label>
                    <Input
                      id="human-confidence"
                      value={form.confidenceThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, confidenceThreshold: event.target.value }))}
                      placeholder="0.3"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-iou">跟踪 IoU 阈值</Label>
                    <Input
                      id="human-iou"
                      value={form.iouThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, iouThreshold: event.target.value }))}
                      placeholder="0.3"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-max-time">逗留时间阈值</Label>
                    <Input
                      id="human-max-time"
                      value={form.maxTime}
                      onChange={(event) => setForm((prev) => ({ ...prev, maxTime: event.target.value }))}
                      placeholder="10"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-max-lost">最大丢失帧数</Label>
                    <Input
                      id="human-max-lost"
                      value={form.maxLost}
                      onChange={(event) => setForm((prev) => ({ ...prev, maxLost: event.target.value }))}
                      placeholder="5"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-min-area">最小人体框面积</Label>
                    <Input
                      id="human-min-area"
                      value={form.minBoxArea}
                      onChange={(event) => setForm((prev) => ({ ...prev, minBoxArea: event.target.value }))}
                      placeholder="0"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-interval">告警间隔</Label>
                    <Input
                      id="human-interval"
                      value={form.alarmInterval}
                      onChange={(event) => setForm((prev) => ({ ...prev, alarmInterval: event.target.value }))}
                      placeholder="5.0"
                    />
                  </div>

                </div>

                <div className="grid gap-5 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="human-roi">人体 ROI</Label>
                    <Textarea
                      id="human-roi"
                      value={form.roiPos}
                      onChange={(event) => setForm((prev) => ({ ...prev, roiPos: event.target.value }))}
                      rows={5}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="human-region">关注区域</Label>
                    <Textarea
                      id="human-region"
                      value={form.region}
                      onChange={(event) => setForm((prev) => ({ ...prev, region: event.target.value }))}
                      rows={5}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="human-aspect">宽高比范围</Label>
                    <Textarea
                      id="human-aspect"
                      value={form.aspectRatioRange}
                      onChange={(event) => setForm((prev) => ({ ...prev, aspectRatioRange: event.target.value }))}
                      rows={5}
                    />
                  </div>
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
                alarm={humanConfig.alarm}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setHumanConfig((prev) => ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
                onSave={saveConfig}
              />
            </TabsContent>
          </Tabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}
