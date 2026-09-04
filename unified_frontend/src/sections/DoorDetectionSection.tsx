import { lazy, Suspense, useEffect, useState } from 'react'
import { Bell, Box, Camera, MousePointer2, SlidersHorizontal } from 'lucide-react'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { AiVisionPresetActions } from '@/components/AiVisionPresetActions'
import { normalizeFeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionConfigTab, DetectionConfigTabsList, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { getAiVisionCameras, getAiVisionFeatureConfig, isAiVisionFeatureEnabled, saveAiVisionFeatureConfig, type AiVisionCamera } from '@/lib/aivision'
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

async function requestDoorConfig(shmName: string, config?: DoorConfig) {
  const payload = config
    ? await saveAiVisionFeatureConfig('detect_door', shmName, config)
    : await getAiVisionFeatureConfig('detect_door', shmName)
  return {
    camera_id: payload.camera.id,
    name: payload.camera.name,
    shm_name: payload.camera.shm_name,
    camera_enable: payload.camera.enable,
    detect_door: payload.config as DoorConfig,
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
      await requestDoorConfig(cameraName, { ...payload.detect_door, enable: true })
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
      await requestDoorConfig(cameraName, { ...payload.detect_door, enable: false })
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
      const payload = await requestDoorConfig(shmName, nextConfig)
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
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title="大门开关检测"
          subtitle="大门状态异常监控面板"
          departmentLabel="公共能力"
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="大门开关检测监控" feature="detect_door" presentation="feature-dashboard" />
        </TabsContent>

        <TabsContent value="config" className="mt-0 space-y-6">
          <Tabs defaultValue="camera" className="space-y-6">
            <DetectionConfigTabsList>
              <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
              <DetectionConfigTab value="params" icon={SlidersHorizontal}>检测参数</DetectionConfigTab>
              <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
              <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
              <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
            </DetectionConfigTabsList>

            <TabsContent value="camera" className="space-y-6">
              <FeatureCameraManager
                cameras={cameras}
                feature="detect_door"
                department="general_electric"
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
              <Card className={DETECTION_CONFIG_CARD_CLASS}>
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="维护当前摄像头的大门状态、确认与环境参数。" actions={<Badge variant="outline">AiVision detect_door</Badge>} />
              <DetectionConfigCardContent className="space-y-5">
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

              </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!isAdmin || cameraAction || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />
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
