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
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
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

type FaceConfig = {
  enable: boolean
  value: {
    roi_pos: number[][]
    cap_interval: number
    alarm_interval: number
    MAX_TIME: number
    MAX_LOST: number
    DETECTION_IOU_THR: number
    TRACK_IOU_THR: number
    FACE_SCORE_THR: number
  }
  alarm: NormalizedFeatureAlarmConfig
}

type FaceConfigResponse = {
  camera_id: number
  name: string
  shm_name: string
  camera_enable: boolean
  detect_face: FaceConfig
}

const defaultForm = {
  cameraName: '',
  roiPos: '',
  faceScoreThreshold: '',
  maxTime: '',
  maxLost: '',
  detectionIouThreshold: '',
  trackIouThreshold: '',
  capInterval: '',
  alarmInterval: '',
}

function formatJson(value: unknown) {
  return JSON.stringify(value || [])
}

function toForm(payload: FaceConfigResponse) {
  return {
    cameraName: payload.shm_name,
    roiPos: formatJson(payload.detect_face.value.roi_pos),
    faceScoreThreshold: String(payload.detect_face.value.FACE_SCORE_THR),
    maxTime: String(payload.detect_face.value.MAX_TIME),
    maxLost: String(payload.detect_face.value.MAX_LOST),
    detectionIouThreshold: String(payload.detect_face.value.DETECTION_IOU_THR),
    trackIouThreshold: String(payload.detect_face.value.TRACK_IOU_THR),
    capInterval: String(payload.detect_face.value.cap_interval),
    alarmInterval: String(payload.detect_face.value.alarm_interval),
  }
}

async function requestFaceConfig(shmName: string, config?: FaceConfig) {
  const payload = config
    ? await saveAiVisionFeatureConfig('detect_face', shmName, config)
    : await getAiVisionFeatureConfig('detect_face', shmName)
  return {
    camera_id: payload.camera.id,
    name: payload.camera.name,
    shm_name: payload.camera.shm_name,
    camera_enable: payload.camera.enable,
    detect_face: payload.config as FaceConfig,
  }
}

export function FaceDetectionSection({ department }: { department: DepartmentId }) {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [faceConfig, setFaceConfig] = useState<FaceConfig | null>(null)
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const enabledCameras = getEnabledFeatureCameras(cameras, 'detect_face', department)
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
    const shmName = getEnabledFeatureCameras(source, 'detect_face', department).some((camera) => camera.shm_name === cameraName.trim()) ? cameraName.trim() : ''
    const requestId = ++configRequestRef.current
    loadedCameraRef.current = ''
    selectedCameraRef.current = shmName
    setFaceConfig(null)
    setForm({ ...defaultForm, cameraName: shmName })
    if (!shmName) {
      setLoading(false)
      setMessage(EMPTY_FEATURE_CAMERA_MESSAGE)
      return
    }

    setLoading(true)
    setMessage('正在读取当前配置...')
    try {
      const payload = await requestFaceConfig(shmName)
      if (requestId !== configRequestRef.current) return
      loadedCameraRef.current = shmName
      setFaceConfig(payload.detect_face)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的人脸逗留检测配置。`)
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
      const nextCamera = selectFeatureCamera(items, 'detect_face', department, preferredCamera ?? selectedCameraRef.current)
      if (!nextCamera) {
        selectedCameraRef.current = ''
        configRequestRef.current += 1
        loadedCameraRef.current = ''
        setLoading(false)
        setFaceConfig(null)
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
    setFaceConfig(null)
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

    if (!faceConfig || loading || loadedCameraRef.current !== shmName) {
      setMessage('保存失败：请先成功读取当前摄像头的配置。')
      return
    }
    const requestId = configRequestRef.current
    if (Object.values(form).some((value) => !value.trim())) {
      setMessage('保存失败：请填写所有必填参数。')
      return
    }

    let roiPos: number[][]
    try {
      const parsedRoi = parseNormalizedRoi(form.roiPos)
      if (!Array.isArray(parsedRoi)) {
        throw new Error('ROI 必须是数组')
      }
      roiPos = parsedRoi
    } catch (error) {
      setMessage(`保存失败：ROI 不是合法 JSON。${error instanceof Error ? error.message : ''}`)
      return
    }

    const maxTime = Number(form.maxTime)
    const maxLost = Number(form.maxLost)
    const detectionIouThreshold = Number(form.detectionIouThreshold)
    const trackIouThreshold = Number(form.trackIouThreshold)
    const faceScoreThreshold = Number(form.faceScoreThreshold)
    const capInterval = Number(form.capInterval)
    const alarmInterval = Number(form.alarmInterval)
    if ([form.maxTime, form.maxLost, form.faceScoreThreshold, form.detectionIouThreshold, form.trackIouThreshold, form.capInterval, form.alarmInterval].some((v) => !v.trim()) ||
      !Number.isFinite(maxTime) || maxTime < 0 || !Number.isInteger(maxLost) || maxLost < 0 ||
      ![faceScoreThreshold, detectionIouThreshold, trackIouThreshold].every((v) => Number.isFinite(v) && v >= 0 && v <= 1) ||
      !Number.isFinite(capInterval) || capInterval <= 0 || !Number.isFinite(alarmInterval) || alarmInterval <= 0) {
      setMessage('保存失败：比例须为 0～1，逗留秒数须 ≥0，丢失次数须为非负整数，处理与告警间隔须 >0。')
      return
    }

    const nextConfig: FaceConfig = {
      ...faceConfig,
      enable: faceConfig.enable,
      value: {
        ...faceConfig.value,
        roi_pos: roiPos,
        FACE_SCORE_THR: faceScoreThreshold,
        MAX_TIME: maxTime,
        MAX_LOST: maxLost,
        DETECTION_IOU_THR: detectionIouThreshold,
        TRACK_IOU_THR: trackIouThreshold,
        cap_interval: capInterval,
        alarm_interval: alarmInterval,
      },
      alarm: faceConfig.alarm,
    }

    setSaving(true)
    setMessage('正在保存配置...')
    try {
      const payload = await requestFaceConfig(shmName, nextConfig)
      if (requestId !== configRequestRef.current) return
      setFaceConfig(payload.detect_face)
      setForm(toForm(payload))
      const items = await refreshCameraList()
      if (requestId !== configRequestRef.current) return
      setMessage(`保存成功：${getCameraDisplayName(payload.shm_name, payload.name, items)} 的人脸逗留检测配置已更新。`)
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
      faceScoreThreshold: '0.6',
      alarmInterval: '5.0',
    }))
    setMessage('已应用白天参数预设，确认后请保存配置。')
  }

  const applyNightPreset = () => {
    setForm((prev) => ({
      ...prev,
      faceScoreThreshold: '0.5',
      alarmInterval: '5.0',
    }))
    setMessage('已应用夜间参数预设，确认后请保存配置。')
  }


  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title="人脸逗留检测"
          subtitle="当前可见目标逗留超时后保持告警状态，通知按告警间隔冷却"
          departmentLabel={DEPARTMENT_LABELS[department]}
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="人脸逗留检测监控" feature="detect_face" department={department} presentation="feature-dashboard" />
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
                feature="detect_face"
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

            <TabsContent value="roi" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !faceConfig || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载 ROI 编辑器..." />}>
                <AiVisionRoiEditor
                  title="人脸逗留检测 ROI 绘制"
                  cameraKey={form.cameraName}
                  roiJson={form.roiPos}
                  disabled={!faceConfig || !isAdmin || loading || saving || !form.cameraName}
                  saving={saving}
                  message={message}
                  onChange={(roiPos) => setForm((prev) => ({ ...prev, roiPos }))}
                  onSave={saveConfig}
                />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !faceConfig || loading || saving}>

              <Card className={DETECTION_CONFIG_CARD_CLASS}>
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="InsightFace 检测人脸框，按轨迹计算逗留时间。" actions={<Badge variant="outline">AiVision detect_face</Badge>} />
              <DetectionConfigCardContent className="space-y-5">
                <AiVisionPresetActions
                  disabled={!faceConfig || !isAdmin || loading || saving || !form.cameraName}
                  onApplyDay={applyDayPreset}
                  onApplyNight={applyNightPreset}
                />
                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="face-camera">摄像头名称</Label>
                    <Select
                      value={form.cameraName}
                      onValueChange={(value) => {
                        setForm((prev) => ({ ...prev, cameraName: value }))
                        loadConfig(value)
                      }}
                      disabled={cameraLoading || loading || saving || enabledCameras.length === 0}
                    >
                      <SelectTrigger id="face-camera" className="w-full">
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
                    <Label htmlFor="face-score">人脸置信度阈值</Label>
                    <Input
                      id="face-score"
                      type="number" min="0" max="1" step="0.01"
                      value={form.faceScoreThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, faceScoreThreshold: event.target.value }))}
                      placeholder="0.6"
                    />
                  </div>



                  <div className="space-y-2">
                    <Label htmlFor="face-max-time">逗留时间阈值（秒，≥0）</Label>
                    <Input id="face-max-time" type="number" min="0"  step="0.1"
                      value={form.maxTime} onChange={(event) => setForm((prev) => ({ ...prev, maxTime: event.target.value }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="face-max-lost">允许连续丢失次数（跟踪更新次数）</Label>
                    <Input id="face-max-lost" type="number" min="0"  step="1"
                      value={form.maxLost} onChange={(event) => setForm((prev) => ({ ...prev, maxLost: event.target.value }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="face-detection-iou">检测框 NMS IoU（0～1）</Label>
                    <Input id="face-detection-iou" type="number" min="0" max="1" step="0.01"
                      value={form.detectionIouThreshold} onChange={(event) => setForm((prev) => ({ ...prev, detectionIouThreshold: event.target.value }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="face-track-iou">跨帧跟踪 IoU（0～1）</Label>
                    <Input id="face-track-iou" type="number" min="0" max="1" step="0.01"
                      value={form.trackIouThreshold} onChange={(event) => setForm((prev) => ({ ...prev, trackIouThreshold: event.target.value }))} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="face-cap-interval">静止画面处理间隔（秒，&gt;0）</Label>
                    <Input id="face-cap-interval" type="number" min="0" step="0.01"
                      value={form.capInterval} onChange={(event) => setForm((prev) => ({ ...prev, capInterval: event.target.value }))} />
                    <p className="text-xs text-slate-500">画面变化时也会触发检测；实际频率受推理耗时影响。丢失次数按跟踪更新累计。</p>
                  </div>

                </div>

                <div className="space-y-2">
                  <Label htmlFor="face-roi">人脸 ROI 区域坐标</Label>
                  <Textarea
                    id="face-roi"
                    value={form.roiPos}
                    onChange={(event) => setForm((prev) => ({ ...prev, roiPos: event.target.value }))}
                    rows={6}
                    placeholder="[]"
                  />
                </div>

              </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!isAdmin || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="model" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !faceConfig || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载模型配置..." />}>
                <AiVisionModelConfig requiredModels={['insightface_detection']} />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!isAdmin || !faceConfig || loading || saving}>

              <AlarmPushConfig
                alarmInterval={form.alarmInterval}
                onAlarmIntervalChange={(alarmInterval) => setForm((previous) => ({ ...previous, alarmInterval }))}
                alarm={faceConfig?.alarm}
                disabled={!faceConfig || !isAdmin || loading || saving || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setFaceConfig((prev) => prev && ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
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
