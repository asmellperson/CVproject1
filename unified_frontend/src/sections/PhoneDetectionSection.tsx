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
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { getAiVisionCameras, getAiVisionFeatureConfig, saveAiVisionFeatureConfig, type AiVisionCamera } from '@/lib/aivision'
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

type PhoneRoiPos = number[][]

type PhoneConfig = {
  enable: boolean
  value: {
    roi_pos: PhoneRoiPos
    cap_interval: number
    alarm_interval: number
    CONF_THRESHOLD: number
    IOU_THR: number
    PERSON_CONF_THRESHOLD: number
    MIN_CONFIRM_SECONDS: number
    MIN_CONSECUTIVE_HITS: number
    REQUIRE_PERSON_ASSOCIATION: boolean
    MAX_MISSED_SECONDS: number
    TRACK_TTL_SECONDS: number
    TRACK_IOU_THRESHOLD: number
    PERSON_IOU_THR: number
    HAND_REGION_MAX_Y_RATIO: number
    MIN_PERSON_PHONE_OVERLAP: number
    PERSON_EXPAND_RATIO: number
  }
  alarm: NormalizedFeatureAlarmConfig
}

type PhoneConfigResponse = {
  camera_id: number
  name: string
  shm_name: string
  camera_enable: boolean
  detect_phone: PhoneConfig
}

const defaultForm = {
  cameraName: '',
  roiPos: '',
  confidenceThreshold: '',
  personConfidenceThreshold: '',
  iouThreshold: '',
  alarmInterval: '',
  minConfirmSeconds: '',
  minConsecutiveHits: '',
  requirePersonAssociation: true,
  personExpandRatio: '',
}

function formatJson(value: unknown) {
  return JSON.stringify(value || [])
}

function toForm(payload: PhoneConfigResponse) {
  return {
    cameraName: payload.shm_name,
    roiPos: formatJson(payload.detect_phone.value.roi_pos),
    confidenceThreshold: String(payload.detect_phone.value.CONF_THRESHOLD),
    personConfidenceThreshold: String(payload.detect_phone.value.PERSON_CONF_THRESHOLD),
    iouThreshold: String(payload.detect_phone.value.IOU_THR),
    alarmInterval: String(payload.detect_phone.value.alarm_interval),
    minConfirmSeconds: String(payload.detect_phone.value.MIN_CONFIRM_SECONDS),
    minConsecutiveHits: String(payload.detect_phone.value.MIN_CONSECUTIVE_HITS),
    requirePersonAssociation: payload.detect_phone.value.REQUIRE_PERSON_ASSOCIATION,
    personExpandRatio: String(payload.detect_phone.value.PERSON_EXPAND_RATIO),
  }
}

async function requestPhoneConfig(shmName: string, config?: PhoneConfig) {
  const payload = config
    ? await saveAiVisionFeatureConfig('detect_phone', shmName, config)
    : await getAiVisionFeatureConfig('detect_phone', shmName)
  return {
    camera_id: payload.camera.id,
    name: payload.camera.name,
    shm_name: payload.camera.shm_name,
    camera_enable: payload.camera.enable,
    detect_phone: payload.config as PhoneConfig,
  }
}

export function PhoneDetectionSection({ department }: { department: DepartmentId }) {
  const canConfigure = useDepartmentConfigAccess(department, 'detect_phone')
  const [form, setForm] = useState(defaultForm)
  const [phoneConfig, setPhoneConfig] = useState<PhoneConfig | null>(null)
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const enabledCameras = getEnabledFeatureCameras(cameras, 'detect_phone', department)
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
    const shmName = getEnabledFeatureCameras(source, 'detect_phone', department).some((camera) => camera.shm_name === cameraName.trim()) ? cameraName.trim() : ''
    const requestId = ++configRequestRef.current
    loadedCameraRef.current = ''
    selectedCameraRef.current = shmName
    setPhoneConfig(null)
    setForm({ ...defaultForm, cameraName: shmName })
    if (!shmName) {
      setLoading(false)
      setMessage(EMPTY_FEATURE_CAMERA_MESSAGE)
      return
    }

    setLoading(true)
    setMessage('正在读取当前配置...')
    try {
      const payload = await requestPhoneConfig(shmName)
      if (requestId !== configRequestRef.current) return
      loadedCameraRef.current = shmName
      setPhoneConfig(payload.detect_phone)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的手机使用检测配置。`)
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
      const nextCamera = selectFeatureCamera(items, 'detect_phone', department, preferredCamera ?? selectedCameraRef.current)
      if (!nextCamera) {
        selectedCameraRef.current = ''
        configRequestRef.current += 1
        loadedCameraRef.current = ''
        setLoading(false)
        setPhoneConfig(null)
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
    setPhoneConfig(null)
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

    if (!phoneConfig || loading || loadedCameraRef.current !== shmName) {
      setMessage('保存失败：请先成功读取当前摄像头的配置。')
      return
    }
    const requestId = configRequestRef.current
    if (Object.entries(form).some(([key, value]) => typeof value === 'string' && key !== 'envThreshold' && !value.trim())) {
      setMessage('保存失败：请填写所有必填参数。')
      return
    }

    let roiPos: PhoneRoiPos
    try {
      roiPos = parseNormalizedRoi(form.roiPos)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : 'ROI 坐标无效'}`)
      return
    }

    if (!Array.isArray(roiPos)) {
      setMessage('保存失败：ROI 区域坐标必须是数组。')
      return
    }

    const confidenceThreshold = Number(form.confidenceThreshold)
    const personConfidenceThreshold = Number(form.personConfidenceThreshold)
    const iouThreshold = Number(form.iouThreshold)
    const alarmInterval = Number(form.alarmInterval)
    const minConfirmSeconds = Number(form.minConfirmSeconds)
    const minConsecutiveHits = Number(form.minConsecutiveHits)
    const personExpandRatio = Number(form.personExpandRatio)

    if (
      !Number.isFinite(confidenceThreshold) ||
      !Number.isFinite(personConfidenceThreshold) ||
      !Number.isFinite(iouThreshold) ||
      !Number.isFinite(alarmInterval) ||
      !Number.isFinite(minConfirmSeconds) ||
      !Number.isInteger(minConsecutiveHits) || minConsecutiveHits < 1 ||
      !Number.isFinite(personExpandRatio)
    ) {
      setMessage('保存失败：置信度、IOU、告警间隔和误报控制参数必须是数字。')
      return
    }

    const nextConfig: PhoneConfig = {
      ...phoneConfig,
      enable: phoneConfig.enable,
      value: {
        ...phoneConfig.value,
        roi_pos: roiPos,
        CONF_THRESHOLD: confidenceThreshold,
        PERSON_CONF_THRESHOLD: personConfidenceThreshold,
        IOU_THR: iouThreshold,
        alarm_interval: alarmInterval,
        MIN_CONFIRM_SECONDS: minConfirmSeconds,
        MIN_CONSECUTIVE_HITS: minConsecutiveHits,
        REQUIRE_PERSON_ASSOCIATION: form.requirePersonAssociation,
        PERSON_EXPAND_RATIO: personExpandRatio,
      },
      alarm: phoneConfig.alarm,
    }

    setSaving(true)
    setMessage('正在保存手机使用检测配置...')
    try {
      await requestPhoneConfig(shmName, nextConfig)
      if (requestId !== configRequestRef.current) return
      setMessage('保存成功，正在重新读取当前摄像头配置...')
      const reloaded = await requestPhoneConfig(shmName)
      if (requestId !== configRequestRef.current) return
      setPhoneConfig(reloaded.detect_phone)
      setForm(toForm(reloaded))
      const items = await refreshCameraList()
      if (requestId !== configRequestRef.current) return
      setMessage(`保存成功：已重新读取并确认 ${getCameraDisplayName(reloaded.shm_name, reloaded.name, items)} 的手机检测配置。`)
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
      confidenceThreshold: '0.7',
      iouThreshold: '0.5',
      alarmInterval: '5.0',
      minConfirmSeconds: '1.2',
      minConsecutiveHits: '3',
      requirePersonAssociation: true,
      personExpandRatio: '0.18',
    }))
    setMessage('已应用白天参数预设，确认后请保存配置。')
  }

  const applyNightPreset = () => {
    setForm((prev) => ({
      ...prev,
      confidenceThreshold: '0.62',
      iouThreshold: '0.45',
      alarmInterval: '5.0',
      minConfirmSeconds: '1.6',
      minConsecutiveHits: '4',
      requirePersonAssociation: true,
      personExpandRatio: '0.22',
    }))
    setMessage('已应用夜间参数预设，确认后请保存配置。')
  }


  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title="手机使用检测"
          subtitle="手机使用识别监控面板"
          departmentLabel={DEPARTMENT_LABELS[department]}
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="手机使用检测监控" feature="detect_phone" department={department} presentation="feature-dashboard" />
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
                feature="detect_phone"
                department={department}
                currentCameraName={form.cameraName}
                disabled={!canConfigure || cameraLoading || loading || saving}
                onSelectCamera={(cameraName) => {
                  setForm((prev) => ({ ...prev, cameraName }))
                  loadConfig(cameraName)
                }}
                onCamerasChanged={refreshCameraList}
                onConfigCopied={(cameraName) => loadCameras(cameraName).then(() => undefined)}
              />
            </TabsContent>

            <TabsContent value="roi" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !phoneConfig || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载 ROI 编辑器..." />}>
                <AiVisionRoiEditor
                  title="手机使用检测 ROI 绘制"
                  cameraKey={form.cameraName}
                  roiJson={form.roiPos}
                  disabled={!phoneConfig || !canConfigure || loading || saving || !form.cameraName}
                  saving={saving}
                  message={message}
                  onChange={(roiPos) => setForm((prev) => ({ ...prev, roiPos }))}
                  onSave={saveConfig}
                />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !phoneConfig || loading || saving}>

              <Card className={DETECTION_CONFIG_CARD_CLASS}>
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="维护当前摄像头的手机检测、人员关联与确认参数。" />
              <DetectionConfigCardContent className="space-y-5">
                <AiVisionPresetActions
                  disabled={!phoneConfig || !canConfigure || loading || saving || !form.cameraName}
                  onApplyDay={applyDayPreset}
                  onApplyNight={applyNightPreset}
                />
                <div className="grid gap-5 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="phone-camera">摄像头名称</Label>
                    <Select
                      value={form.cameraName}
                      onValueChange={(value) => {
                        setForm((prev) => ({ ...prev, cameraName: value }))
                        loadConfig(value)
                      }}
                      disabled={cameraLoading || loading || saving || enabledCameras.length === 0}
                    >
                      <SelectTrigger id="phone-camera" className="w-full">
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
                    <Label htmlFor="phone-confidence">手机置信度阈值</Label>
                    <Input
                      id="phone-confidence"
                      value={form.confidenceThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, confidenceThreshold: event.target.value }))}
                      placeholder="0.7"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="phone-person-confidence">人体关联置信度阈值</Label>
                    <Input
                      id="phone-person-confidence"
                      value={form.personConfidenceThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, personConfidenceThreshold: event.target.value }))}
                      placeholder="0.3"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="phone-iou">手机 IOU 阈值</Label>
                    <Input
                      id="phone-iou"
                      value={form.iouThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, iouThreshold: event.target.value }))}
                      placeholder="0.5"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="phone-confirm-seconds">确认持续时间（秒）</Label>
                    <Input
                      id="phone-confirm-seconds"
                      value={form.minConfirmSeconds}
                      onChange={(event) => setForm((prev) => ({ ...prev, minConfirmSeconds: event.target.value }))}
                      placeholder="1.2"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="phone-hit-count">连续命中次数</Label>
                    <Input
                      id="phone-hit-count"
                      type="number" min="1" step="1"
                      value={form.minConsecutiveHits}
                      onChange={(event) => setForm((prev) => ({ ...prev, minConsecutiveHits: event.target.value }))}
                      placeholder="3"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="phone-person-expand">人体关联扩展比例</Label>
                    <Input
                      id="phone-person-expand"
                      value={form.personExpandRatio}
                      onChange={(event) => setForm((prev) => ({ ...prev, personExpandRatio: event.target.value }))}
                      placeholder="0.18"
                    />
                  </div>

                  <div className="flex items-center justify-between gap-4 rounded-xl border border-rose-100 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
                    <Label htmlFor="phone-person-association">启用人体区域关联</Label>
                    <Switch
                      id="phone-person-association"
                      checked={form.requirePersonAssociation}
                      onCheckedChange={(checked) => setForm((prev) => ({ ...prev, requirePersonAssociation: checked }))}
                    />
                  </div>

                </div>

              </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!canConfigure || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="model" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !phoneConfig || loading || saving}>

              <Suspense fallback={<LazyConfigFallback label="正在加载模型配置..." />}>
                <AiVisionModelConfig requiredModels={['yolo_phone']} />
              </Suspense>

              </FeatureConfigGate>
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <FeatureConfigGate cameraKey={form.cameraName} disabled={!canConfigure || !phoneConfig || loading || saving}>

              <AlarmPushConfig
                alarmInterval={form.alarmInterval}
                onAlarmIntervalChange={(alarmInterval) => setForm((previous) => ({ ...previous, alarmInterval }))}
                alarm={phoneConfig?.alarm}
                disabled={!phoneConfig || !canConfigure || loading || saving || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setPhoneConfig((prev) => prev && ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
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

export default PhoneDetectionSection
