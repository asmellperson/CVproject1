import { lazy, Suspense, useEffect, useState } from 'react'
import { Bell, Box, Camera, DoorOpen, MousePointer2, RefreshCw, Save, SlidersHorizontal, Waypoints } from 'lucide-react'
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

type DoorConfig = {
  enable: boolean
  value: {
    roi_pos: number[][]
    threshold?: number
    cap_interval?: number
    alarm_interval?: number
    blur_kernel?: number
    diff_threshold?: number
    diff_threshold_env?: number
    env_threshold?: number
    first_alarm?: number
    stable_confirm_seconds?: number
    stable_confirm_hits?: number
    background_update_alpha?: number
    global_motion_threshold?: number
  }
  alarm: NormalizedFeatureAlarmConfig
}

type DoorConfigResponse = {
  camera_id: number
  name: string
  shm_name: string
  camera_enable: boolean
  detect_door: DoorConfig
}

const defaultForm = {
  cameraName: '',
  roiPos: '[[100,100],[500,100],[500,500],[100,500]]',
  threshold: '0.5',
  firstAlarm: '60',
  alarmInterval: '5.0',
  stableConfirmSeconds: '1.0',
  stableConfirmHits: '3',
  globalMotionThreshold: '0.22',
  backgroundUpdateAlpha: '0.05',
}

const defaultDoorConfig: DoorConfig = {
  enable: false,
  value: {
    roi_pos: [],
    threshold: 0.5,
    cap_interval: 0.1,
    alarm_interval: 5.0,
    blur_kernel: 5,
    diff_threshold: 5,
    diff_threshold_env: 10,
    env_threshold: 10,
    first_alarm: 60,
    stable_confirm_seconds: 1.0,
    stable_confirm_hits: 3,
    background_update_alpha: 0.05,
    global_motion_threshold: 0.22,
  },
  alarm: {
    horn: { enable: false, parm: {} },
    sql: { enable: false, parm: {} },
    wechat: { enable: false, parm: { user: '' } },
  },
}

function formatRoi(roiPos: number[][]) {
  return JSON.stringify(roiPos || [])
}

function toForm(payload: DoorConfigResponse) {
  return {
    cameraName: payload.shm_name,
    roiPos: formatRoi(payload.detect_door.value.roi_pos),
    threshold: String(payload.detect_door.value.threshold ?? 0.5),
    firstAlarm: String(payload.detect_door.value.first_alarm ?? 60),
    alarmInterval: String(payload.detect_door.value.alarm_interval ?? 5.0),
    stableConfirmSeconds: String(payload.detect_door.value.stable_confirm_seconds ?? 1.0),
    stableConfirmHits: String(payload.detect_door.value.stable_confirm_hits ?? 3),
    globalMotionThreshold: String(payload.detect_door.value.global_motion_threshold ?? 0.22),
    backgroundUpdateAlpha: String(payload.detect_door.value.background_update_alpha ?? 0.05),
  }
}

async function requestDoorConfig(shmName: string, init?: RequestInit) {
  const response = await fetch(`/api/ai/door-config/${encodeURIComponent(shmName)}`, { ...init, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${response.status} ${response.statusText}${detail ? ` ${detail}` : ''}`)
  }
  const payload = (await response.json()) as DoorConfigResponse | DoorConfig
  if ('detect_door' in payload) return payload
  return {
    camera_id: 0,
    name: shmName,
    shm_name: shmName,
    camera_enable: true,
    detect_door: payload,
  }
}

export function DoorDetectionSection() {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [doorConfig, setDoorConfig] = useState<DoorConfig>(defaultDoorConfig)
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
      const payload = await requestDoorConfig(shmName)
      setDoorConfig(payload.detect_door)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的大门开关异常检测配置。`)
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
      const enabledCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_door'))
      const nextCamera = enabledCamera?.shm_name || ''
      if (items.length === 0) {
        setMessage('未获取到可用摄像头，请先在 AiVision 中配置。')
        return
      }
      if (!nextCamera) {
        setForm((prev) => ({ ...prev, cameraName: '' }))
        setMessage('当前大门开关检测未添加摄像头，请先添加摄像头。')
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
    setMessage('正在添加摄像头并启用大门开关检测...')
    try {
      const payload = await requestDoorConfig(cameraName)
      await requestDoorConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_door, enable: true }),
      })
      await refreshCameraList()
      await loadConfig(cameraName)
      setMessage(`添加成功：${cameraName} 已启用大门开关检测。`)
    } catch (error) {
      setMessage(`添加失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraAction(false)
    }
  }

  const removeCameraFromFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在停用该摄像头的大门开关检测...')
    try {
      const payload = await requestDoorConfig(cameraName)
      await requestDoorConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_door, enable: false }),
      })
      const items = await refreshCameraList()
      const nextCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_door'))?.shm_name || ''
      if (form.cameraName === cameraName && nextCamera) {
        await loadConfig(nextCamera)
      } else if (form.cameraName === cameraName) {
        setDoorConfig(defaultDoorConfig)
        setForm({ ...defaultForm, cameraName: '' })
      }
      setMessage(`停用成功：${cameraName} 已关闭大门开关检测。`)
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

    let roiPos: number[][]
    try {
      const parsed = JSON.parse(form.roiPos)
      if (!Array.isArray(parsed)) {
        throw new Error('ROI 必须是二维数组')
      }
      roiPos = parsed
    } catch (error) {
      setMessage(`保存失败：ROI 坐标不是合法 JSON。${error instanceof Error ? error.message : ''}`)
      return
    }

    const threshold = Number(form.threshold)
    const firstAlarm = Number(form.firstAlarm)
    const alarmInterval = Number(form.alarmInterval)
    const stableConfirmSeconds = Number(form.stableConfirmSeconds)
    const stableConfirmHits = Number(form.stableConfirmHits)
    const globalMotionThreshold = Number(form.globalMotionThreshold)
    const backgroundUpdateAlpha = Number(form.backgroundUpdateAlpha)
    if (
      !Number.isFinite(threshold) ||
      !Number.isFinite(firstAlarm) ||
      !Number.isFinite(alarmInterval) ||
      !Number.isFinite(stableConfirmSeconds) ||
      !Number.isFinite(stableConfirmHits) ||
      !Number.isFinite(globalMotionThreshold) ||
      !Number.isFinite(backgroundUpdateAlpha)
    ) {
      setMessage('保存失败：检测阈值、告警时间、持续确认和背景稳定参数必须是数字。')
      return
    }

    const nextConfig: DoorConfig = {
      ...doorConfig,
      enable: true,
      value: {
        ...doorConfig.value,
        roi_pos: roiPos,
        threshold,
        first_alarm: firstAlarm,
        alarm_interval: alarmInterval,
        stable_confirm_seconds: stableConfirmSeconds,
        stable_confirm_hits: Math.max(1, Math.round(stableConfirmHits)),
        global_motion_threshold: globalMotionThreshold,
        background_update_alpha: backgroundUpdateAlpha,
      },
      alarm: doorConfig.alarm || defaultDoorConfig.alarm,
    }

    setSaving(true)
    setMessage('正在保存配置...')
    try {
      const payload = await requestDoorConfig(shmName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nextConfig),
      })
      setDoorConfig(payload.detect_door)
      setForm(toForm(payload))
      const items = await refreshCameraList()
      setMessage(`保存成功：${getCameraDisplayName(payload.shm_name, payload.name, items)} 的大门开关异常检测配置已更新。`)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const applyDayPreset = () => {
    setForm((prev) => ({
      ...prev,
      threshold: '0.5',
      firstAlarm: '60',
      alarmInterval: '5.0',
      stableConfirmSeconds: '1.0',
      stableConfirmHits: '3',
      globalMotionThreshold: '0.22',
      backgroundUpdateAlpha: '0.05',
    }))
    setMessage('已应用白天参数预设，确认后请保存配置。')
  }

  const applyNightPreset = () => {
    setForm((prev) => ({
      ...prev,
      threshold: '0.42',
      firstAlarm: '90',
      alarmInterval: '5.0',
      stableConfirmSeconds: '1.5',
      stableConfirmHits: '4',
      globalMotionThreshold: '0.28',
      backgroundUpdateAlpha: '0.04',
    }))
    setMessage('已应用夜间参数预设，确认后请保存配置。')
  }

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_door'))

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-black tracking-tight text-slate-950 sm:text-[28px]">大门开关检测监控与配置</h1>
            <p className="mt-1 text-sm text-slate-500 sm:text-base">大门状态异常监控面板</p>
          </div>
          <TabsList className="grid h-auto w-full shrink-0 grid-cols-2 rounded-full border border-slate-200/70 bg-white p-1 shadow-sm sm:w-auto">
            <TabsTrigger value="monitor" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <DoorOpen className="h-4 w-4" />
              实时监控
            </TabsTrigger>
            <TabsTrigger value="config" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <Waypoints className="h-4 w-4" />
              配置管理
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="大门开关检测监控" feature="detect_door" presentation="feature-dashboard" />
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
                feature="detect_door"
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
                  title="大门开关异常检测 ROI 绘制"
                  cameraKey={form.cameraName}
                  feature="detect_door"
                  roiJson={form.roiPos}
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                  saving={saving}
                  message={message}
                  onChange={(roiPos) => setForm((prev) => ({ ...prev, roiPos }))}
                  onSave={saveConfig}
                />
              </Suspense>
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <Card className="overflow-hidden border-white/80 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.10)] dark:border-slate-800 dark:bg-slate-900/92">
              <CardHeader className="flex flex-col items-start justify-between gap-4 border-b border-slate-100 bg-[linear-gradient(180deg,#eef2ff_0%,#ffffff_100%)] sm:flex-row sm:items-center dark:border-slate-800 dark:bg-slate-900">
                <CardTitle className="flex items-center gap-3 text-lg font-black text-[#071d3d] dark:text-slate-100">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white shadow-[0_12px_24px_rgba(79,70,229,0.22)]">
                    <SlidersHorizontal className="h-5 w-5" />
                  </span>
                  配置表单
                </CardTitle>
                <Badge variant="outline" className="border-slate-300 text-slate-600">
                  AiVision detect_door
                </Badge>
              </CardHeader>
              <CardContent className="space-y-5 bg-[#f8faff] p-4 sm:p-5 dark:bg-slate-950/30">
                <AiVisionPresetActions
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                  onApplyDay={applyDayPreset}
                  onApplyNight={applyNightPreset}
                />
                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="door-camera">摄像头名称</Label>
                    <Select
                      value={form.cameraName}
                      onValueChange={(value) => {
                        setForm((prev) => ({ ...prev, cameraName: value }))
                        loadConfig(value)
                      }}
                      disabled={cameraLoading || loading || saving || cameraAction || featureCameras.length === 0}
                    >
                      <SelectTrigger id="door-camera" className="w-full">
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
                    <Label htmlFor="door-threshold">检测阈值</Label>
                    <Input
                      id="door-threshold"
                      value={form.threshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, threshold: event.target.value }))}
                      placeholder="0.5"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="door-first-alarm">首次告警时间</Label>
                    <Input
                      id="door-first-alarm"
                      value={form.firstAlarm}
                      onChange={(event) => setForm((prev) => ({ ...prev, firstAlarm: event.target.value }))}
                      placeholder="60"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="door-interval">告警间隔</Label>
                    <Input
                      id="door-interval"
                      value={form.alarmInterval}
                      onChange={(event) => setForm((prev) => ({ ...prev, alarmInterval: event.target.value }))}
                      placeholder="5.0"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="door-stable-seconds">变化确认时间</Label>
                    <Input
                      id="door-stable-seconds"
                      value={form.stableConfirmSeconds}
                      onChange={(event) => setForm((prev) => ({ ...prev, stableConfirmSeconds: event.target.value }))}
                      placeholder="1.0"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="door-stable-hits">连续确认次数</Label>
                    <Input
                      id="door-stable-hits"
                      value={form.stableConfirmHits}
                      onChange={(event) => setForm((prev) => ({ ...prev, stableConfirmHits: event.target.value }))}
                      placeholder="3"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="door-global-motion">背景抖动阈值</Label>
                    <Input
                      id="door-global-motion"
                      value={form.globalMotionThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, globalMotionThreshold: event.target.value }))}
                      placeholder="0.22"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="door-bg-alpha">背景更新速率</Label>
                    <Input
                      id="door-bg-alpha"
                      value={form.backgroundUpdateAlpha}
                      onChange={(event) => setForm((prev) => ({ ...prev, backgroundUpdateAlpha: event.target.value }))}
                      placeholder="0.05"
                    />
                  </div>

                </div>

                <div className="space-y-2">
                  <Label htmlFor="door-roi">大门 ROI 区域坐标</Label>
                  <Textarea
                    id="door-roi"
                    value={form.roiPos}
                    onChange={(event) => setForm((prev) => ({ ...prev, roiPos: event.target.value }))}
                    rows={6}
                    placeholder="[[100,100],[500,100],[500,500],[100,500]]"
                  />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-indigo-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
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
                <AiVisionModelConfig requiredModels={[]} />
              </Suspense>
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <AlarmPushConfig
                alarm={doorConfig.alarm}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setDoorConfig((prev) => ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
                onSave={saveConfig}
              />
            </TabsContent>
          </Tabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}
