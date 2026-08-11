import { lazy, Suspense, useEffect, useState } from 'react'
import { Bell, Box, Camera, Radar, RefreshCw, Save, SlidersHorizontal, Waypoints } from 'lucide-react'
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

type BlocksConfig = {
  enable: boolean
  value: {
    roi_pos: number[][]
    line_points?: number[][]
    alarm_side?: number
    foot_ratio?: number
    threshold?: number
    cap_interval?: number
    alarm_interval?: number
    blur_kernel?: number
    diff_threshold?: number
    diff_threshold_env?: number
    env_threshold?: number
  }
  alarm: NormalizedFeatureAlarmConfig
}

type BlocksConfigResponse = {
  camera_id: number
  name: string
  shm_name: string
  camera_enable: boolean
  blocks: BlocksConfig
}

const defaultForm = {
  cameraName: '',
  linePoints: '[[0.2,0.7],[0.8,0.7]]',
  alarmSide: '1',
  footRatio: '0.93',
  threshold: '0.1',
  alarmInterval: '5.0',
}

const defaultBlocks: BlocksConfig = {
  enable: false,
  value: {
    roi_pos: [],
    line_points: [[0.2, 0.7], [0.8, 0.7]],
    alarm_side: 1,
    foot_ratio: 0.93,
    threshold: 0.1,
    cap_interval: 0.1,
    alarm_interval: 5.0,
    blur_kernel: 5,
    diff_threshold: 10,
    diff_threshold_env: 10,
    env_threshold: 0.5,
  },
  alarm: {
    horn: { enable: false, parm: {} },
    sql: { enable: false, parm: {} },
    wechat: { enable: false, parm: { user: '' } },
  },
}

function formatLinePoints(linePoints?: number[][]) {
  return JSON.stringify(linePoints && linePoints.length >= 2 ? linePoints.slice(0, 2) : defaultBlocks.value.line_points)
}

function toForm(payload: BlocksConfigResponse) {
  return {
    cameraName: payload.shm_name,
    linePoints: formatLinePoints(payload.blocks.value.line_points),
    alarmSide: String(payload.blocks.value.alarm_side ?? 1),
    footRatio: String(payload.blocks.value.foot_ratio ?? 0.93),
    threshold: String(payload.blocks.value.threshold ?? 0.1),
    alarmInterval: String(payload.blocks.value.alarm_interval ?? 5.0),
  }
}

function parseLinePoints(raw: string) {
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed) || parsed.length < 2) {
    throw new Error('警戒线必须包含两个点')
  }
  const points = parsed.slice(0, 2).map((point) => {
    if (!Array.isArray(point) || point.length < 2) {
      throw new Error('每个点必须是 [x,y]')
    }
    const x = Number(point[0])
    const y = Number(point[1])
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      throw new Error('坐标必须是数字')
    }
    return [x, y]
  })
  if (points[0][0] === points[1][0] && points[0][1] === points[1][1]) {
    throw new Error('两个点不能相同')
  }
  return points
}

async function requestBlocksConfig(shmName: string, init?: RequestInit) {
  const response = await fetch(`/api/ai/blocks-config/${encodeURIComponent(shmName)}`, { ...init, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${response.status} ${response.statusText}${detail ? ` ${detail}` : ''}`)
  }
  const payload = (await response.json()) as BlocksConfigResponse | BlocksConfig
  if ('blocks' in payload) return payload
  return {
    camera_id: 0,
    name: shmName,
    shm_name: shmName,
    camera_enable: true,
    blocks: payload,
  }
}

export function IntrusionDetectionSection() {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [blocks, setBlocks] = useState<BlocksConfig>(defaultBlocks)
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
      const payload = await requestBlocksConfig(shmName)
      setBlocks(payload.blocks)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的区域入侵配置。`)
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
      const enabledCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'blocks'))
      const nextCamera = enabledCamera?.shm_name || ''
      if (items.length === 0) {
        setMessage('未获取到可用摄像头，请先在 AiVision 中配置。')
        return
      }
      if (!nextCamera) {
        setForm((prev) => ({ ...prev, cameraName: '' }))
        setMessage('当前区域入侵检测未添加摄像头，请先添加摄像头。')
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
    setMessage('正在添加摄像头并启用区域入侵检测...')
    try {
      const payload = await requestBlocksConfig(cameraName)
      await requestBlocksConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.blocks, enable: true }),
      })
      await refreshCameraList()
      await loadConfig(cameraName)
      setMessage(`添加成功：${cameraName} 已启用区域入侵检测。`)
    } catch (error) {
      setMessage(`添加失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraAction(false)
    }
  }

  const removeCameraFromFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在停用该摄像头的区域入侵检测...')
    try {
      const payload = await requestBlocksConfig(cameraName)
      await requestBlocksConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.blocks, enable: false }),
      })
      const items = await refreshCameraList()
      const nextCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'blocks'))?.shm_name || ''
      if (form.cameraName === cameraName && nextCamera) {
        await loadConfig(nextCamera)
      } else if (form.cameraName === cameraName) {
        setBlocks(defaultBlocks)
        setForm({ ...defaultForm, cameraName: '' })
      }
      setMessage(`停用成功：${cameraName} 已关闭区域入侵检测。`)
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

    let linePoints: number[][]
    try {
      linePoints = parseLinePoints(form.linePoints)
    } catch (error) {
      setMessage(`保存失败：警戒线坐标不是合法 JSON。${error instanceof Error ? error.message : ''}`)
      return
    }

    const threshold = Number(form.threshold)
    const alarmInterval = Number(form.alarmInterval)
    const footRatio = Number(form.footRatio)
    if (!Number.isFinite(threshold) || !Number.isFinite(alarmInterval) || !Number.isFinite(footRatio)) {
      setMessage('保存失败：检测阈值、告警间隔和脚底比例必须是数字。')
      return
    }
    if (footRatio < 0 || footRatio > 1) {
      setMessage('保存失败：脚底比例必须在 0 到 1 之间。')
      return
    }

    const nextBlocks: BlocksConfig = {
      ...blocks,
      enable: true,
      value: {
        ...blocks.value,
        roi_pos: blocks.value.roi_pos || [],
        line_points: linePoints,
        alarm_side: Number(form.alarmSide) < 0 ? -1 : 1,
        foot_ratio: footRatio,
        threshold,
        alarm_interval: alarmInterval,
      },
      alarm: blocks.alarm || defaultBlocks.alarm,
    }

    setSaving(true)
    setMessage('正在保存配置...')
    try {
      await requestBlocksConfig(shmName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nextBlocks),
      })
      setMessage('保存成功，正在重新读取当前摄像头配置...')
      const reloaded = await requestBlocksConfig(shmName)
      setBlocks(reloaded.blocks)
      setForm(toForm(reloaded))
      const items = await refreshCameraList()
      setMessage(`保存成功：已重新读取并确认 ${getCameraDisplayName(reloaded.shm_name, reloaded.name, items)} 的区域入侵配置。`)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const applyDayPreset = () => {
    setForm((prev) => ({ ...prev, threshold: '0.12', alarmInterval: '5.0' }))
    setMessage('已应用白天参数预设，确认后请保存配置。')
  }

  const applyNightPreset = () => {
    setForm((prev) => ({ ...prev, threshold: '0.08', alarmInterval: '5.0' }))
    setMessage('已应用夜间参数预设，确认后请保存配置。')
  }

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'blocks'))

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-black tracking-tight text-slate-950 dark:text-slate-100 sm:text-[28px]">区域入侵检测监控与配置</h1>
            <p className="mt-1 text-sm text-slate-500 sm:text-base">警戒区域实时监控面板</p>
          </div>
          <TabsList className="grid h-auto w-full shrink-0 grid-cols-2 rounded-full border border-slate-200/70 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:w-auto">
            <TabsTrigger value="monitor" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <Radar className="h-4 w-4" />
              实时监控
            </TabsTrigger>
            <TabsTrigger value="config" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <Waypoints className="h-4 w-4" />
              配置管理
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="区域入侵检测监控" feature="blocks" presentation="feature-dashboard" />
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
              <TabsTrigger value="line" className="gap-2 py-2">
                <Waypoints className="h-4 w-4" />
                警戒线绘制
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
                feature="blocks"
                department="research_institute"
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

            <TabsContent value="line" className="space-y-6">
              <Suspense fallback={<LazyConfigFallback label="正在加载警戒线编辑器..." />}>
                <AiVisionRoiEditor
                  title="区域入侵警戒线绘制"
                  cameraKey={form.cameraName}
                  mode="line"
                  roiJson={form.linePoints}
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                  saving={saving}
                  message={message}
                  onChange={(linePoints) => setForm((prev) => ({ ...prev, linePoints }))}
                  onSave={saveConfig}
                />
              </Suspense>
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <Card className="overflow-hidden border-white/80 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.10)] dark:border-slate-800 dark:bg-slate-900/92">
              <CardHeader className="flex flex-col items-start justify-between gap-4 border-b border-slate-100 bg-[linear-gradient(180deg,#f0fdfa_0%,#ffffff_100%)] sm:flex-row sm:items-center dark:border-slate-800 dark:bg-none dark:bg-slate-900">
                <CardTitle className="flex items-center gap-3 text-lg font-black text-[#071d3d] dark:text-slate-100">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500 text-white shadow-[0_12px_24px_rgba(16,185,129,0.22)]">
                    <SlidersHorizontal className="h-5 w-5" />
                  </span>
                  配置表单
                </CardTitle>
                <Badge variant="outline" className="border-slate-300 text-slate-600">
                  AiVision blocks
                </Badge>
              </CardHeader>
              <CardContent className="space-y-5 bg-[#f7fffc] p-4 sm:p-5 dark:bg-slate-950/30">
                <AiVisionPresetActions
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                  onApplyDay={applyDayPreset}
                  onApplyNight={applyNightPreset}
                />
                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="intrusion-camera">摄像头名称</Label>
                    <Select
                      value={form.cameraName}
                      onValueChange={(value) => {
                        setForm((prev) => ({ ...prev, cameraName: value }))
                        loadConfig(value)
                      }}
                      disabled={cameraLoading || loading || saving || cameraAction || featureCameras.length === 0}
                    >
                      <SelectTrigger id="intrusion-camera" className="w-full">
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
                    <Label htmlFor="intrusion-threshold">检测阈值</Label>
                    <Input
                      id="intrusion-threshold"
                      value={form.threshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, threshold: event.target.value }))}
                      placeholder="0.1"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="intrusion-interval">告警间隔</Label>
                    <Input
                      id="intrusion-interval"
                      value={form.alarmInterval}
                      onChange={(event) => setForm((prev) => ({ ...prev, alarmInterval: event.target.value }))}
                      placeholder="5.0"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="intrusion-side">入侵侧</Label>
                    <Select
                      value={form.alarmSide}
                      onValueChange={(value) => setForm((prev) => ({ ...prev, alarmSide: value }))}
                      disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                    >
                      <SelectTrigger id="intrusion-side" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1">线左侧</SelectItem>
                        <SelectItem value="-1">线右侧</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="intrusion-foot-ratio">脚底比例</Label>
                    <Input
                      id="intrusion-foot-ratio"
                      value={form.footRatio}
                      onChange={(event) => setForm((prev) => ({ ...prev, footRatio: event.target.value }))}
                      placeholder="0.93"
                    />
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
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
                alarm={blocks.alarm}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setBlocks((prev) => ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
                onSave={saveConfig}
              />
            </TabsContent>
          </Tabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}
