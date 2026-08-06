import { lazy, Suspense, useEffect, useState } from 'react'
import { Bell, Box, Camera, Clock3, MousePointer2, RefreshCw, Save, SlidersHorizontal, Waypoints } from 'lucide-react'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { AiVisionPresetActions } from '@/components/AiVisionPresetActions'
import { normalizeFeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
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

const AiVisionRoiEditor = lazy(() =>
  import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })),
)
const AiVisionModelConfig = lazy(() =>
  import('@/components/AiVisionModelConfig').then((module) => ({ default: module.AiVisionModelConfig })),
)

function LazyConfigFallback({ label }: { label: string }) {
  return (
    <div className="flex min-h-[280px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">
      {label}
    </div>
  )
}

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
    CENTER_DIST_THR?: number
    AREA_RATIO_THR?: number
    MATCH_SCORE_THR?: number
    TRACK_SMOOTH_ALPHA?: number
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
  centerDistThreshold: '0.65',
  areaRatioThreshold: '0.55',
  matchScoreThreshold: '0.35',
  trackSmoothAlpha: '0.7',
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
    CENTER_DIST_THR: 0.65,
    AREA_RATIO_THR: 0.55,
    MATCH_SCORE_THR: 0.35,
    TRACK_SMOOTH_ALPHA: 0.7,
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
    centerDistThreshold: String(value.CENTER_DIST_THR ?? 0.65),
    areaRatioThreshold: String(value.AREA_RATIO_THR ?? 0.55),
    matchScoreThreshold: String(value.MATCH_SCORE_THR ?? 0.35),
    trackSmoothAlpha: String(value.TRACK_SMOOTH_ALPHA ?? 0.7),
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const centerDistThreshold = Number(form.centerDistThreshold)
    const areaRatioThreshold = Number(form.areaRatioThreshold)
    const matchScoreThreshold = Number(form.matchScoreThreshold)
    const trackSmoothAlpha = Number(form.trackSmoothAlpha)
    const alarmInterval = Number(form.alarmInterval)
    if (
      !Number.isFinite(confidenceThreshold) ||
      !Number.isFinite(iouThreshold) ||
      !Number.isFinite(maxTime) ||
      !Number.isFinite(maxLost) ||
      !Number.isFinite(minBoxArea) ||
      !Number.isFinite(centerDistThreshold) ||
      !Number.isFinite(areaRatioThreshold) ||
      !Number.isFinite(matchScoreThreshold) ||
      !Number.isFinite(trackSmoothAlpha) ||
      !Number.isFinite(alarmInterval)
    ) {
      setMessage('保存失败：置信度、IoU、逗留时间、跟踪增强参数和告警间隔必须是数字。')
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
        CENTER_DIST_THR: centerDistThreshold,
        AREA_RATIO_THR: areaRatioThreshold,
        MATCH_SCORE_THR: matchScoreThreshold,
        TRACK_SMOOTH_ALPHA: trackSmoothAlpha,
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

  const applyDayPreset = () => {
    setForm((prev) => ({
      ...prev,
      confidenceThreshold: '0.3',
      iouThreshold: '0.3',
      maxLost: '5',
      minBoxArea: '0',
      centerDistThreshold: '0.65',
      areaRatioThreshold: '0.55',
      matchScoreThreshold: '0.35',
      trackSmoothAlpha: '0.7',
      alarmInterval: '5.0',
    }))
    setMessage('已应用白天参数预设，确认后请保存配置。')
  }

  const applyNightPreset = () => {
    setForm((prev) => ({
      ...prev,
      confidenceThreshold: '0.25',
      iouThreshold: '0.28',
      maxLost: '8',
      minBoxArea: '0',
      centerDistThreshold: '0.8',
      areaRatioThreshold: '0.45',
      matchScoreThreshold: '0.3',
      trackSmoothAlpha: '0.75',
      alarmInterval: '5.0',
    }))
    setMessage('已应用夜间参数预设，确认后请保存配置。')
  }

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_human'))

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-black tracking-tight text-slate-950 sm:text-[28px]">人员逗留监控与配置入口</h1>
            <p className="mt-1 text-sm text-slate-500 sm:text-base">区域逗留超时监控面板</p>
          </div>
          <TabsList className="grid h-auto w-full shrink-0 grid-cols-2 rounded-full border border-slate-200/70 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:w-auto">
            <TabsTrigger value="monitor" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <Clock3 className="h-4 w-4" />
              实时监控
            </TabsTrigger>
            <TabsTrigger value="config" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <Waypoints className="h-4 w-4" />
              配置管理
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="人员逗留检测监控" feature="detect_human" presentation="human-dwell" />
        </TabsContent>

        <TabsContent value="config" className="mt-0 space-y-6">
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
                onConfigCopied={(cameraName) => {
                  setForm((prev) => ({ ...prev, cameraName }))
                  return loadConfig(cameraName)
                }}
              />
            </TabsContent>

            <TabsContent value="roi" className="space-y-6">
              <Suspense fallback={<LazyConfigFallback label="正在加载 ROI 编辑器..." />}>
                <AiVisionRoiEditor
                  title="人体逗留 ROI 绘制"
                  cameraKey={form.cameraName}
                  feature="detect_human"
                  roiJson={form.roiPos}
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                  saving={saving}
                  message={message}
                  onChange={(roiPos) => setForm((prev) => ({ ...prev, roiPos, region: bboxFromRoiJson(roiPos, prev.region) }))}
                  onSave={saveConfig}
                />
              </Suspense>
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <Card className="overflow-hidden border-white/80 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.10)] dark:border-slate-800 dark:bg-slate-900/92">
              <CardHeader className="flex flex-col items-start justify-between gap-4 border-b border-slate-100 bg-[linear-gradient(180deg,#fffbeb_0%,#ffffff_100%)] sm:flex-row sm:items-center dark:border-slate-800 dark:bg-slate-900">
                <CardTitle className="flex items-center gap-3 text-lg font-black text-[#071d3d] dark:text-slate-100">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-500 text-white shadow-[0_12px_24px_rgba(249,115,22,0.22)]">
                    <SlidersHorizontal className="h-5 w-5" />
                  </span>
                  配置表单
                </CardTitle>
                <Badge variant="outline" className="border-slate-300 text-slate-600">
                  AiVision detect_human
                </Badge>
              </CardHeader>
              <CardContent className="space-y-5 bg-[#fffaf2] p-4 sm:p-5 dark:bg-slate-950/30">
                <AiVisionPresetActions
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                  onApplyDay={applyDayPreset}
                  onApplyNight={applyNightPreset}
                />
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
                    <Label htmlFor="human-center-distance">中心距离阈值</Label>
                    <Input
                      id="human-center-distance"
                      value={form.centerDistThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, centerDistThreshold: event.target.value }))}
                      placeholder="0.65"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-area-ratio">面积相似阈值</Label>
                    <Input
                      id="human-area-ratio"
                      value={form.areaRatioThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, areaRatioThreshold: event.target.value }))}
                      placeholder="0.55"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-match-score">匹配分数阈值</Label>
                    <Input
                      id="human-match-score"
                      value={form.matchScoreThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, matchScoreThreshold: event.target.value }))}
                      placeholder="0.35"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-track-smooth">轨迹平滑系数</Label>
                    <Input
                      id="human-track-smooth"
                      value={form.trackSmoothAlpha}
                      onChange={(event) => setForm((prev) => ({ ...prev, trackSmoothAlpha: event.target.value }))}
                      placeholder="0.7"
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

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-orange-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
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
              <Suspense fallback={<LazyConfigFallback label="正在加载模型配置..." />}>
                <AiVisionModelConfig requiredModels={['yolo_human']} />
              </Suspense>
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
