import { getEnabledFeatureCameras, selectFeatureCamera, EMPTY_FEATURE_CAMERA_MESSAGE } from '@/lib/feature-cameras'
import { FeatureConfigGate } from '@/components/detection/FeatureConfigGate'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Bell, Box, Camera, MousePointer2, SlidersHorizontal } from 'lucide-react'
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
import {
  getAiVisionCameras,
  getAiVisionFeatureConfig,
  saveAiVisionFeatureConfig,
  type AiVisionCamera,
  type AiVisionFeatureConfig,
} from '@/lib/aivision'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'

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

type HumanConfig = AiVisionFeatureConfig & {
  value: {
    cap_interval: number
    alarm_interval: number
    CONF_THRESHOLD: number
    TRACK_IOU_THR: number
    DETECTION_IOU_THR: number
    MAX_LOST: number
    MAX_TIME: number
    roi_pos: number[][]
    MIN_BOX_AREA: number
    ASPECT_RATIO_RANGE: number[]
    CENTER_DIST_THR: number
    AREA_RATIO_THR: number
    MATCH_SCORE_THR: number
    TRACK_SMOOTH_ALPHA: number
  }
  alarm: NormalizedFeatureAlarmConfig
}

const defaultForm = {
  cameraName: '',
  roiPos: '',
  confidenceThreshold: '',
  detectionIouThreshold: '',
  trackIouThreshold: '',
  maxTime: '',
  maxLost: '',
  minBoxArea: '',
  minAspectRatio: '',
  maxAspectRatio: '',
  centerDistThreshold: '',
  areaRatioThreshold: '',
  matchScoreThreshold: '',
  trackSmoothAlpha: '',
  alarmInterval: '',
}

function formatJson(value: unknown) {
  return JSON.stringify(value || [])
}

function toForm(shmName: string, config: HumanConfig) {
  const value = config.value
  return {
    cameraName: shmName,
    roiPos: formatJson(value.roi_pos),
    confidenceThreshold: String(value.CONF_THRESHOLD),
    detectionIouThreshold: String(value.DETECTION_IOU_THR),
    trackIouThreshold: String(value.TRACK_IOU_THR),
    maxTime: String(value.MAX_TIME),
    maxLost: String(value.MAX_LOST),
    minBoxArea: String(value.MIN_BOX_AREA),
    minAspectRatio: String(value.ASPECT_RATIO_RANGE[0]),
    maxAspectRatio: String(value.ASPECT_RATIO_RANGE[1]),
    centerDistThreshold: String(value.CENTER_DIST_THR),
    areaRatioThreshold: String(value.AREA_RATIO_THR),
    matchScoreThreshold: String(value.MATCH_SCORE_THR),
    trackSmoothAlpha: String(value.TRACK_SMOOTH_ALPHA),
    alarmInterval: String(value.alarm_interval),
  }
}

export function HumanDetectionSection({ department }: { department: DepartmentId }) {
  const title = '人员违规逗留检测'
  const departmentLabel = DEPARTMENT_LABELS[department]
  const feature = 'detect_human'
  const canConfigure = useDepartmentConfigAccess(department, 'detect_human')
  const [form, setForm] = useState(defaultForm)
  const [humanConfig, setHumanConfig] = useState<HumanConfig | null>(null)
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const enabledCameras = getEnabledFeatureCameras(cameras, 'detect_human', department)
  const [message, setMessage] = useState('正在读取当前配置...')
  const [loading, setLoading] = useState(false)
  const [cameraLoading, setCameraLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const configRequestRef = useRef(0)
  const cameraListRequestRef = useRef(0)
  const loadedCameraRef = useRef('')
  const selectedCameraRef = useRef('')

  const getCameraDisplayName = (shmName: string, fallback?: string, source: AiVisionCamera[] = cameras) => {
    const key = shmName.trim()
    return source.find((camera) => camera.shm_name === key || camera.id === key)?.name || fallback || key
  }

  const loadConfig = async (cameraName = form.cameraName, source: AiVisionCamera[] = cameras) => {
    const shmName = getEnabledFeatureCameras(source, 'detect_human', department).some((camera) => camera.shm_name === cameraName.trim()) ? cameraName.trim() : ''
    const requestId = ++configRequestRef.current
    loadedCameraRef.current = ''
    selectedCameraRef.current = shmName
    setHumanConfig(null)
    setForm({ ...defaultForm, cameraName: shmName })
    if (!shmName) {
      setLoading(false)
      setMessage(EMPTY_FEATURE_CAMERA_MESSAGE)
      return
    }

    setLoading(true)
    setMessage('正在读取当前配置...')
    try {
      const payload = await getAiVisionFeatureConfig(feature, shmName)
      if (requestId !== configRequestRef.current) return
      loadedCameraRef.current = shmName
      const config = payload.config as HumanConfig
      selectedCameraRef.current = payload.camera.shm_name
      setHumanConfig(config)
      setForm(toForm(payload.camera.shm_name, config))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.camera.shm_name, payload.camera.name, source)} 的人员违规逗留检测配置。`)
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
      const nextCamera = selectFeatureCamera(items, 'detect_human', department, preferredCamera ?? selectedCameraRef.current)
      if (!nextCamera) {
        selectedCameraRef.current = ''
        configRequestRef.current += 1
        loadedCameraRef.current = ''
        setLoading(false)
        setHumanConfig(null)
        setForm(defaultForm)
        selectedCameraRef.current = ''
        setForm((prev) => ({ ...prev, cameraName: '' }))
        setMessage(EMPTY_FEATURE_CAMERA_MESSAGE)
        return items
      }
      selectedCameraRef.current = nextCamera
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
    setHumanConfig(null)
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
    if (!canConfigure) {
      setMessage('当前账号为 viewer，只能查看配置。')
      return
    }

    if (!humanConfig || loading || loadedCameraRef.current !== shmName) {
      setMessage('保存失败：请先成功读取当前摄像头的配置。')
      return
    }
    const requestId = configRequestRef.current
    if (Object.entries(form).some(([key, value]) => typeof value === 'string' && key !== 'envThreshold' && !value.trim())) {
      setMessage('保存失败：请填写所有必填参数。')
      return
    }

    let roiPos: number[][]
    try {
      roiPos = parseNormalizedRoi(form.roiPos)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : 'ROI 区域无效'}`)
      return
    }
    const aspectRatioRange = [Number(form.minAspectRatio), Number(form.maxAspectRatio)]
    if (!aspectRatioRange.every((value) => Number.isFinite(value) && value >= 0) || aspectRatioRange[0] > aspectRatioRange[1]) {
      setMessage('保存失败：宽高比必须为非负数，最小值不得大于最大值。')
      return
    }

    const confidenceThreshold = Number(form.confidenceThreshold)
    const detectionIouThreshold = Number(form.detectionIouThreshold)
    const trackIouThreshold = Number(form.trackIouThreshold)
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
      !Number.isFinite(detectionIouThreshold) || detectionIouThreshold < 0 || detectionIouThreshold > 1 ||
      !Number.isFinite(trackIouThreshold) || trackIouThreshold < 0 || trackIouThreshold > 1 ||
      !Number.isFinite(maxTime) || maxTime < 0 ||
      !Number.isInteger(maxLost) || maxLost < 0 ||
      !Number.isInteger(minBoxArea) || minBoxArea < 0 ||
      !Number.isFinite(centerDistThreshold) || centerDistThreshold < 0 ||
      !Number.isFinite(areaRatioThreshold) ||
      !Number.isFinite(matchScoreThreshold) ||
      !Number.isFinite(trackSmoothAlpha) ||
      !Number.isFinite(alarmInterval) || alarmInterval <= 0 ||
      ![confidenceThreshold, areaRatioThreshold, matchScoreThreshold, trackSmoothAlpha].every((v) => v >= 0 && v <= 1)
    ) {
      setMessage('保存失败：置信度、IoU、逗留时间、跟踪增强参数和告警间隔必须是数字。')
      return
    }

    const nextConfig: HumanConfig = {
      ...humanConfig,
      enable: humanConfig.enable,
      value: {
        ...humanConfig.value,
        roi_pos: roiPos,
        CONF_THRESHOLD: confidenceThreshold,
        DETECTION_IOU_THR: detectionIouThreshold,
        TRACK_IOU_THR: trackIouThreshold,
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
      alarm: humanConfig.alarm,
    }

    setSaving(true)
    setMessage('正在保存配置...')
    try {
      const payload = await saveAiVisionFeatureConfig(feature, shmName, nextConfig)
      if (requestId !== configRequestRef.current) return
      const config = payload.config as HumanConfig
      selectedCameraRef.current = payload.camera.shm_name
      setHumanConfig(config)
      setForm(toForm(payload.camera.shm_name, config))
      const items = await refreshCameraList()
      if (requestId !== configRequestRef.current) return
      setMessage(`保存成功：${getCameraDisplayName(payload.camera.shm_name, payload.camera.name, items)} 的人员违规逗留检测配置已更新。`)
    } catch (error) {
      if (requestId !== configRequestRef.current) return
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const applyDayPreset = () => {
    setForm((prev) => ({
      ...prev,
      confidenceThreshold: '0.3',
      detectionIouThreshold: '0.3',
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
      detectionIouThreshold: '0.28',
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


  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title={title}
          subtitle="区域逗留超时监控面板"
          departmentLabel={departmentLabel}
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title={`${title}监控`} feature={feature} department={department} presentation="human-dwell" />
        </TabsContent>

        <TabsContent value="config" className="mt-0 space-y-6">
          <DetectionConfigTabs defaultValue="camera" className="space-y-6"
            tabs={<>
              <DetectionConfigTab value="camera" icon={Camera}>摄像头</DetectionConfigTab>
              <DetectionConfigTab value="params" icon={SlidersHorizontal}>检测参数</DetectionConfigTab>
              <DetectionConfigTab value="roi" icon={MousePointer2}>ROI 配置</DetectionConfigTab>
              <DetectionConfigTab value="model" icon={Box}>模型配置</DetectionConfigTab>
              <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
            </>}
          >

            <TabsContent value="camera" className="space-y-6">
              <FeatureCameraManager
                cameras={cameras}
                feature={feature}
                department={department}
                currentCameraName={form.cameraName}
                disabled={!canConfigure || cameraLoading || loading || saving}
                onSelectCamera={(cameraName) => {
                  selectedCameraRef.current = cameraName
                  setForm((prev) => ({ ...prev, cameraName }))
                  loadConfig(cameraName)
                }}
                onCamerasChanged={refreshCameraList}
                onConfigCopied={(cameraName) => loadCameras(cameraName).then(() => undefined)}
              />
            </TabsContent>

            <TabsContent value="roi" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !humanConfig || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载 ROI 编辑器..." />}>
                <AiVisionRoiEditor
                  title="人员违规逗留检测 ROI 绘制"
                  cameraKey={form.cameraName}
                  roiJson={form.roiPos}
                  disabled={!humanConfig || !canConfigure || loading || saving || !form.cameraName}
                  saving={saving}
                  message={message}
                  onChange={(roiPos) => setForm((prev) => ({ ...prev, roiPos }))}
                  onSave={saveConfig}
                />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !humanConfig || loading || saving}>

              <Card className={DETECTION_CONFIG_CARD_CLASS}>
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="维护当前摄像头的逗留、跟踪与人体过滤参数。" />
              <DetectionConfigCardContent className="space-y-5">
                <AiVisionPresetActions
                  disabled={!humanConfig || !canConfigure || loading || saving || !form.cameraName}
                  onApplyDay={applyDayPreset}
                  onApplyNight={applyNightPreset}
                />
                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="human-camera">摄像头名称</Label>
                    <Select
                      value={form.cameraName}
                      onValueChange={(value) => {
                        selectedCameraRef.current = value
                        setForm((prev) => ({ ...prev, cameraName: value }))
                        loadConfig(value)
                      }}
                      disabled={cameraLoading || loading || saving || enabledCameras.length === 0}
                    >
                      <SelectTrigger id="human-camera" className="w-full">
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
                    <Label htmlFor="human-confidence">人体置信度阈值</Label>
                    <Input
                      id="human-confidence"
                      value={form.confidenceThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, confidenceThreshold: event.target.value }))}
                      placeholder="0.3"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-iou">模型推理 IoU（0～1）</Label>
                    <Input
                      id="human-iou" type="number" min="0" max="1" step="0.01"
                      value={form.detectionIouThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, detectionIouThreshold: event.target.value }))}
                      placeholder="0.3"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="human-track-iou">跨帧跟踪 IoU（0～1）</Label>
                    <Input
                      id="human-track-iou" type="number" min="0" max="1" step="0.01"
                      value={form.trackIouThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, trackIouThreshold: event.target.value }))}
                      placeholder="0.3"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-max-time">逗留时间阈值（秒，≥0）</Label>
                    <Input
                      id="human-max-time" type="number" min="0" step="0.1"
                      value={form.maxTime}
                      onChange={(event) => setForm((prev) => ({ ...prev, maxTime: event.target.value }))}
                      placeholder="10"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="human-max-lost">允许连续丢失次数（跟踪更新次数）</Label>
                    <Input
                      id="human-max-lost" type="number" min="0" step="1"
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

                </div>

                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="human-min-aspect">最小宽高比（宽/高）</Label>
                    <Input id="human-min-aspect" type="number" min={0} step={0.1} value={form.minAspectRatio}
                      onChange={(event) => setForm((prev) => ({ ...prev, minAspectRatio: event.target.value }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="human-max-aspect">最大宽高比（宽/高）</Label>
                    <Input id="human-max-aspect" type="number" min={0} step={0.1} value={form.maxAspectRatio}
                      onChange={(event) => setForm((prev) => ({ ...prev, maxAspectRatio: event.target.value }))} />
                  </div>
                </div>

              </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!canConfigure || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="model" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !humanConfig || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载模型配置..." />}>
                <AiVisionModelConfig requiredModels={['yolo_human']} />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !humanConfig || loading || saving}>

              <AlarmPushConfig
                alarmInterval={form.alarmInterval}
                onAlarmIntervalChange={(alarmInterval) => setForm((previous) => ({ ...previous, alarmInterval }))}
                alarm={humanConfig?.alarm}
                disabled={!humanConfig || !canConfigure || loading || saving || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setHumanConfig((prev) => prev && ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
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
