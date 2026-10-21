import { getEnabledFeatureCameras, selectFeatureCamera, EMPTY_FEATURE_CAMERA_MESSAGE } from '@/lib/feature-cameras'
import { FeatureConfigGate } from '@/components/detection/FeatureConfigGate'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Bell, Box, Camera, SlidersHorizontal, Waypoints } from 'lucide-react'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { AiVisionPresetActions } from '@/components/AiVisionPresetActions'
import { normalizeFeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionConfigTab, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { FeatureCameraManager } from '@/components/FeatureCameraManager'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { getAiVisionCameras, getAiVisionFeatureConfig, saveAiVisionFeatureConfig, type AiVisionCamera } from '@/lib/aivision'
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
    line_points: number[][]
    alarm_side: number
    foot_ratio: number
    threshold: number
    cap_interval: number
    alarm_interval: number
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
  linePoints: '',
  alarmSide: '',
  footRatio: '',
  threshold: '',
  alarmInterval: '',
}

function formatLinePoints(linePoints: number[][]) {
  return JSON.stringify(linePoints ?? [])
}

function toForm(payload: BlocksConfigResponse) {
  return {
    cameraName: payload.shm_name,
    linePoints: formatLinePoints(payload.blocks.value.line_points),
    alarmSide: String(payload.blocks.value.alarm_side),
    footRatio: String(payload.blocks.value.foot_ratio),
    threshold: String(payload.blocks.value.threshold),
    alarmInterval: String(payload.blocks.value.alarm_interval),
  }
}

async function requestBlocksConfig(shmName: string, config?: BlocksConfig) {
  const payload = config
    ? await saveAiVisionFeatureConfig('blocks', shmName, config)
    : await getAiVisionFeatureConfig('blocks', shmName)
  return {
    camera_id: payload.camera.id,
    name: payload.camera.name,
    shm_name: payload.camera.shm_name,
    camera_enable: payload.camera.enable,
    blocks: payload.config as BlocksConfig,
  }
}

export function IntrusionDetectionSection({ department }: { department: DepartmentId }) {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [blocks, setBlocks] = useState<BlocksConfig | null>(null)
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const enabledCameras = getEnabledFeatureCameras(cameras, 'blocks', department)
  const [message, setMessage] = useState('正在读取当前配置...')
  const [loading, setLoading] = useState(false)
  const [cameraLoading, setCameraLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const selectedCameraRef = useRef('')
  const configRequestRef = useRef(0)
  const cameraListRequestRef = useRef(0)
  const loadedCameraRef = useRef('')

  const getCameraDisplayName = (shmName: string, fallback?: string, source: AiVisionCamera[] = cameras) => {
    const key = shmName.trim()
    return source.find((camera) => camera.shm_name === key || camera.id === key)?.name || fallback || key
  }

  const loadConfig = async (cameraName = form.cameraName, source: AiVisionCamera[] = cameras) => {
    const shmName = getEnabledFeatureCameras(source, 'blocks', department).some((camera) => camera.shm_name === cameraName.trim()) ? cameraName.trim() : ''
    const requestId = ++configRequestRef.current
    loadedCameraRef.current = ''
    selectedCameraRef.current = shmName
    setBlocks(null)
    setForm({ ...defaultForm, cameraName: shmName })
    if (!shmName) {
      setLoading(false)
      setMessage(EMPTY_FEATURE_CAMERA_MESSAGE)
      return
    }

    setLoading(true)
    setMessage('正在读取当前配置...')
    try {
      const payload = await requestBlocksConfig(shmName)
      if (requestId !== configRequestRef.current) return
      loadedCameraRef.current = shmName
      setBlocks(payload.blocks)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的区域入侵配置。`)
    } catch (error) {
      if (requestId !== configRequestRef.current) return
      setMessage(`读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (requestId === configRequestRef.current) setLoading(false)
    }
  }

  const loadCameras = async (preferredCamera?: string) => {
    const requestId = ++cameraListRequestRef.current
    setCameraLoading(true)
    loadedCameraRef.current = ''
    try {
      const items = await getAiVisionCameras(department)
      if (requestId !== cameraListRequestRef.current) return
      setCameras(items)
      const nextCamera = selectFeatureCamera(items, 'blocks', department, preferredCamera ?? selectedCameraRef.current)
      if (!nextCamera) {
        selectedCameraRef.current = ''
        configRequestRef.current += 1
        loadedCameraRef.current = ''
        setLoading(false)
        setBlocks(null)
        setForm(defaultForm)
        setMessage(EMPTY_FEATURE_CAMERA_MESSAGE)
        return items
      }
      setForm((prev) => ({ ...prev, cameraName: nextCamera }))
      await loadConfig(nextCamera, items)
      return items
    } catch (error) {
      if (requestId !== cameraListRequestRef.current) return
      await loadConfig('')
      setMessage(`摄像头列表读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (requestId === cameraListRequestRef.current) setCameraLoading(false)
    }
  }

  useEffect(() => {
    setCameras([])
    setForm(defaultForm)
    setBlocks(null)
    selectedCameraRef.current = ''
    loadedCameraRef.current = ''
    loadCameras()
    const refreshCameras = () => {
      loadCameras()
    }
    window.addEventListener('aivision:cameras-changed', refreshCameras)
    return () => {
      configRequestRef.current += 1
      cameraListRequestRef.current += 1
      window.removeEventListener('aivision:cameras-changed', refreshCameras)
    }
  }, [department])

  const refreshCameraList = loadCameras

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

    if (!blocks || loading || loadedCameraRef.current !== shmName) {
      setMessage('保存失败：请先成功读取当前摄像头的配置。')
      return
    }
    const requestId = configRequestRef.current
    if (Object.entries(form).some(([key, value]) => typeof value === 'string' && key !== 'envThreshold' && !value.trim())) {
      setMessage('保存失败：请填写所有必填参数。')
      return
    }

    let linePoints: number[][]
    try {
      linePoints = parseNormalizedRoi(form.linePoints, 'line')
    } catch (error) {
      setMessage(`保存失败：警戒线坐标不是合法 JSON。${error instanceof Error ? error.message : ''}`)
      return
    }

    const threshold = Number(form.threshold)
    const alarmInterval = Number(form.alarmInterval)
    const footRatio = Number(form.footRatio)
    if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1 || !Number.isFinite(alarmInterval) || alarmInterval <= 0 || !Number.isFinite(footRatio)) {
      setMessage('保存失败：检测阈值、告警间隔和脚底比例必须是数字。')
      return
    }
    if (footRatio < 0 || footRatio > 1) {
      setMessage('保存失败：脚底比例必须在 0 到 1 之间。')
      return
    }

    const nextBlocks: BlocksConfig = {
      ...blocks,
      enable: blocks.enable,
      value: {
        ...blocks.value,
        roi_pos: blocks.value.roi_pos,
        line_points: linePoints,
        alarm_side: Number(form.alarmSide),
        foot_ratio: footRatio,
        threshold,
        alarm_interval: alarmInterval,
      },
      alarm: blocks.alarm,
    }

    setSaving(true)
    setMessage('正在保存配置...')
    try {
      await requestBlocksConfig(shmName, nextBlocks)
      if (requestId !== configRequestRef.current) return
      setMessage('保存成功，正在重新读取当前摄像头配置...')
      const reloaded = await requestBlocksConfig(shmName)
      if (requestId !== configRequestRef.current) return
      setBlocks(reloaded.blocks)
      setForm(toForm(reloaded))
      const items = await refreshCameraList()
      if (requestId !== configRequestRef.current) return
      setMessage(`保存成功：已重新读取并确认 ${getCameraDisplayName(reloaded.shm_name, reloaded.name, items)} 的区域入侵配置。`)
    } catch (error) {
      if (requestId !== configRequestRef.current) return
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const applyDayPreset = () => {
    setForm((prev) => ({ ...prev, threshold: '0.12' }))
    setMessage('已应用白天参数预设，确认后请保存配置。')
  }

  const applyNightPreset = () => {
    setForm((prev) => ({ ...prev, threshold: '0.08' }))
    setMessage('已应用夜间参数预设，确认后请保存配置。')
  }


  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title="区域入侵检测"
          subtitle="警戒区域实时监控面板"
          departmentLabel={DEPARTMENT_LABELS[department]}
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="区域入侵检测监控" feature="blocks" department={department} presentation="feature-dashboard" />
        </TabsContent>

        <TabsContent value="config" className="mt-0 space-y-6">
          <DetectionConfigTabs defaultValue="camera" className="space-y-6"
            tabs={<>
              <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
              <DetectionConfigTab value="params" icon={SlidersHorizontal}>检测参数</DetectionConfigTab>
              <DetectionConfigTab value="line" icon={Waypoints}>ROI 配置</DetectionConfigTab>
              <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
              <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
            </>}
          >

            <TabsContent value="camera" className="space-y-6">
              <FeatureCameraManager
                cameras={cameras}
                feature="blocks"
                department={department}
                currentCameraName={form.cameraName}
                disabled={!isAdmin || cameraLoading || loading || saving}
                onSelectCamera={(cameraName) => {
                  setForm((prev) => ({ ...prev, cameraName }))
                  loadConfig(cameraName)
                }}
                onCamerasChanged={refreshCameraList}
                onConfigCopied={(cameraName) => loadCameras(cameraName).then(() => undefined)}
              />
            </TabsContent>

            <TabsContent value="line" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !blocks || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载警戒线编辑器..." />}>
                <AiVisionRoiEditor
                  title="区域入侵警戒线绘制"
                  cameraKey={form.cameraName}
                  mode="line"
                  roiJson={form.linePoints}
                  disabled={!blocks || !isAdmin || loading || saving || !form.cameraName}
                  saving={saving}
                  message={message}
                  onChange={(linePoints) => setForm((prev) => ({ ...prev, linePoints }))}
                  onSave={saveConfig}
                />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !blocks || loading || saving}>

              <Card className={DETECTION_CONFIG_CARD_CLASS}>
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="维护当前摄像头的区域入侵检测参数。" />
              <DetectionConfigCardContent className="space-y-5">
                <AiVisionPresetActions
                  disabled={!blocks || !isAdmin || loading || saving || !form.cameraName}
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
                      disabled={cameraLoading || loading || saving || enabledCameras.length === 0}
                    >
                      <SelectTrigger id="intrusion-camera" className="w-full">
                        <SelectValue placeholder={cameraLoading ? '正在读取摄像头' : '选择摄像头'} />
                      </SelectTrigger>
                      <SelectContent>
                        {enabledCameras.map((camera) => (
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
                    <Label htmlFor="intrusion-side">入侵侧</Label>
                    <Select
                      value={form.alarmSide}
                      onValueChange={(value) => setForm((prev) => ({ ...prev, alarmSide: value }))}
                      disabled={!blocks || !isAdmin || loading || saving || !form.cameraName}
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
              </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!isAdmin || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="model" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !blocks || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载模型配置..." />}>
                <AiVisionModelConfig requiredModels={['yolo_human']} />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !blocks || loading || saving}>

              <AlarmPushConfig
                alarmInterval={form.alarmInterval}
                onAlarmIntervalChange={(alarmInterval) => setForm((previous) => ({ ...previous, alarmInterval }))}
                alarm={blocks?.alarm}
                disabled={!blocks || !isAdmin || loading || saving || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setBlocks((prev) => prev && ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
                onSave={saveConfig}
              />

              </FeatureConfigGate>
            </TabsContent>
          </DetectionConfigTabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}
