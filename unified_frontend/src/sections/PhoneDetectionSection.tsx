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
import { Switch } from '@/components/ui/switch'
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

type PhoneRoiPos = number[][]

type PhoneConfig = {
  enable: boolean
  value: {
    roi_pos: PhoneRoiPos
    cap_interval?: number
    alarm_interval?: number
    CONF_THRESHOLD?: number
    IOU_THR?: number
    PERSON_CONF_THRESHOLD?: number
    MIN_CONFIRM_SECONDS?: number
    MIN_CONSECUTIVE_HITS?: number
    REQUIRE_PERSON_ASSOCIATION?: boolean
    PERSON_EXPAND_RATIO?: number
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
  roiPos: '[]',
  confidenceThreshold: '0.7',
  personConfidenceThreshold: '0.3',
  iouThreshold: '0.5',
  alarmInterval: '5.0',
  minConfirmSeconds: '1.2',
  minConsecutiveHits: '3',
  requirePersonAssociation: true,
  personExpandRatio: '0.18',
}

const defaultPhoneConfig: PhoneConfig = {
  enable: false,
  value: {
    roi_pos: [],
    cap_interval: 0.1,
    alarm_interval: 5.0,
    CONF_THRESHOLD: 0.7,
    PERSON_CONF_THRESHOLD: 0.3,
    IOU_THR: 0.5,
    MIN_CONFIRM_SECONDS: 1.2,
    MIN_CONSECUTIVE_HITS: 3,
    REQUIRE_PERSON_ASSOCIATION: true,
    PERSON_EXPAND_RATIO: 0.18,
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

function toForm(payload: PhoneConfigResponse) {
  return {
    cameraName: payload.shm_name,
    roiPos: formatJson(payload.detect_phone.value.roi_pos),
    confidenceThreshold: String(payload.detect_phone.value.CONF_THRESHOLD ?? 0.7),
    personConfidenceThreshold: String(payload.detect_phone.value.PERSON_CONF_THRESHOLD ?? 0.3),
    iouThreshold: String(payload.detect_phone.value.IOU_THR ?? 0.5),
    alarmInterval: String(payload.detect_phone.value.alarm_interval ?? 5.0),
    minConfirmSeconds: String(payload.detect_phone.value.MIN_CONFIRM_SECONDS ?? 1.2),
    minConsecutiveHits: String(payload.detect_phone.value.MIN_CONSECUTIVE_HITS ?? 3),
    requirePersonAssociation: payload.detect_phone.value.REQUIRE_PERSON_ASSOCIATION ?? true,
    personExpandRatio: String(payload.detect_phone.value.PERSON_EXPAND_RATIO ?? 0.18),
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

export function PhoneDetectionSection() {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [phoneConfig, setPhoneConfig] = useState<PhoneConfig>(defaultPhoneConfig)
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [message, setMessage] = useState('正在读取当前配置...')
  const [loading, setLoading] = useState(false)
  const [cameraLoading, setCameraLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [cameraAction, setCameraAction] = useState(false)
  const selectedCameraRef = useRef('')
  const configRequestRef = useRef(0)
  const loadedCameraRef = useRef('')

  const getCameraDisplayName = (shmName: string, fallback?: string, source: AiVisionCamera[] = cameras) => {
    const key = shmName.trim()
    return source.find((camera) => camera.shm_name === key || camera.id === key)?.name || fallback || key
  }

  const loadConfig = async (cameraName = form.cameraName, source: AiVisionCamera[] = cameras) => {
    const shmName = cameraName.trim()
    const requestId = ++configRequestRef.current
    loadedCameraRef.current = ''
    selectedCameraRef.current = shmName
    setPhoneConfig(defaultPhoneConfig)
    if (!shmName) {
      setMessage('读取失败：请先选择摄像头。')
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

  const loadCameras = async () => {
    setCameraLoading(true)
    try {
      const items = await getAiVisionCameras()
      setCameras(items)
      const enabledCameras = items.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_phone'))
      const enabledCamera = enabledCameras.find((camera) => camera.shm_name === selectedCameraRef.current) || enabledCameras[0]
      const nextCamera = enabledCamera?.shm_name || ''
      if (items.length === 0) {
        setMessage('未获取到可用摄像头，请先在 AiVision 中配置。')
        return
      }
      if (!nextCamera) {
        setForm((prev) => ({ ...prev, cameraName: '' }))
        setMessage('当前手机使用检测未添加摄像头，请先添加摄像头。')
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
    setMessage('正在添加摄像头并启用手机使用检测...')
    try {
      const payload = await requestPhoneConfig(cameraName)
      await requestPhoneConfig(cameraName, { ...payload.detect_phone, enable: true })
      await refreshCameraList()
      await loadConfig(cameraName)
      setMessage(`添加成功：${cameraName} 已启用手机使用检测。`)
    } catch (error) {
      setMessage(`添加失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraAction(false)
    }
  }

  const removeCameraFromFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在停用该摄像头的手机检测...')
    try {
      const payload = await requestPhoneConfig(cameraName)
      await requestPhoneConfig(cameraName, { ...payload.detect_phone, enable: false })
      const items = await refreshCameraList()
      const nextCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_phone'))?.shm_name || ''
      if (form.cameraName === cameraName && nextCamera) {
        await loadConfig(nextCamera)
      } else if (form.cameraName === cameraName) {
        setPhoneConfig(defaultPhoneConfig)
        setForm({ ...defaultForm, cameraName: '' })
      }
      setMessage(`停用成功：${cameraName} 已关闭手机检测。`)
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

    if (loading || loadedCameraRef.current !== shmName) {
      setMessage('保存失败：请先成功读取当前摄像头的配置。')
      return
    }
    const requestId = configRequestRef.current

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
      !Number.isFinite(minConsecutiveHits) ||
      !Number.isFinite(personExpandRatio)
    ) {
      setMessage('保存失败：置信度、IOU、告警间隔和误报控制参数必须是数字。')
      return
    }

    const nextConfig: PhoneConfig = {
      ...phoneConfig,
      enable: true,
      value: {
        ...phoneConfig.value,
        roi_pos: roiPos,
        CONF_THRESHOLD: confidenceThreshold,
        PERSON_CONF_THRESHOLD: personConfidenceThreshold,
        IOU_THR: iouThreshold,
        alarm_interval: alarmInterval,
        MIN_CONFIRM_SECONDS: minConfirmSeconds,
        MIN_CONSECUTIVE_HITS: Math.max(1, Math.round(minConsecutiveHits)),
        REQUIRE_PERSON_ASSOCIATION: form.requirePersonAssociation,
        PERSON_EXPAND_RATIO: personExpandRatio,
      },
      alarm: phoneConfig.alarm || defaultPhoneConfig.alarm,
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

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_phone'))

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title="手机识别检测"
          subtitle="手机使用识别监控面板"
          departmentLabel="福达新材院"
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="手机识别检测监控" feature="detect_phone" presentation="feature-dashboard" />
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

            <TabsContent value="roi" className="space-y-6">
              <Suspense fallback={<LazyConfigFallback label="正在加载 ROI 编辑器..." />}>
                <AiVisionRoiEditor
                  title="手机使用检测 ROI 绘制"
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
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="维护当前摄像头的手机检测、人员关联与确认参数。" actions={<Badge variant="outline">AiVision detect_phone</Badge>} />
              <DetectionConfigCardContent className="space-y-5">
                <AiVisionPresetActions
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
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
                      disabled={cameraLoading || loading || saving || cameraAction || featureCameras.length === 0}
                    >
                      <SelectTrigger id="phone-camera" className="w-full">
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
                    <Label htmlFor="phone-interval">告警间隔</Label>
                    <Input
                      id="phone-interval"
                      value={form.alarmInterval}
                      onChange={(event) => setForm((prev) => ({ ...prev, alarmInterval: event.target.value }))}
                      placeholder="5.0"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="phone-confirm-seconds">确认持续时间</Label>
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

                <div className="space-y-2">
                  <Label htmlFor="phone-roi">手机使用检测 ROI 区域坐标</Label>
                  <Textarea
                    id="phone-roi"
                    value={form.roiPos}
                    onChange={(event) => setForm((prev) => ({ ...prev, roiPos: event.target.value }))}
                    rows={6}
                    placeholder="[]"
                  />
                </div>

              </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!isAdmin || cameraAction || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />
            </TabsContent>

            <TabsContent value="model" className="space-y-6">
              <Suspense fallback={<LazyConfigFallback label="正在加载模型配置..." />}>
                <AiVisionModelConfig requiredModels={['yolo_phone']} />
              </Suspense>
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <AlarmPushConfig
                alarm={phoneConfig.alarm}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setPhoneConfig((prev) => ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
                onSave={saveConfig}
              />
            </TabsContent>
          </DetectionConfigTabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default PhoneDetectionSection
