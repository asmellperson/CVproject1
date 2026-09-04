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

type FaceConfig = {
  enable: boolean
  value: {
    roi_pos: number[][]
    cap_interval?: number
    alarm_interval?: number
    FACE_SCORE_THR?: number
    YAW_THRESHOLD?: number[]
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
  roiPos: '[]',
  faceScoreThreshold: '0.6',
  yawThreshold: '[0,0.3]',
  alarmInterval: '5.0',
}

const defaultFaceConfig: FaceConfig = {
  enable: false,
  value: {
    roi_pos: [],
    cap_interval: 0.1,
    alarm_interval: 5.0,
    FACE_SCORE_THR: 0.6,
    YAW_THRESHOLD: [0, 0.3],
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

function toForm(payload: FaceConfigResponse) {
  return {
    cameraName: payload.shm_name,
    roiPos: formatJson(payload.detect_face.value.roi_pos),
    faceScoreThreshold: String(payload.detect_face.value.FACE_SCORE_THR ?? 0.6),
    yawThreshold: formatJson(payload.detect_face.value.YAW_THRESHOLD ?? [0, 0.3]),
    alarmInterval: String(payload.detect_face.value.alarm_interval ?? 5.0),
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

export function FaceDetectionSection() {
  const { isAdmin } = useAuth()
  const [form, setForm] = useState(defaultForm)
  const [faceConfig, setFaceConfig] = useState<FaceConfig>(defaultFaceConfig)
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
      const payload = await requestFaceConfig(shmName)
      setFaceConfig(payload.detect_face)
      setForm(toForm(payload))
      setMessage(`读取成功：已加载 ${getCameraDisplayName(payload.shm_name, payload.name, source)} 的人脸检测配置。`)
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
      const enabledCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_face'))
      const nextCamera = enabledCamera?.shm_name || ''
      if (items.length === 0) {
        setMessage('未获取到可用摄像头，请先在 AiVision 中配置。')
        return
      }
      if (!nextCamera) {
        setForm((prev) => ({ ...prev, cameraName: '' }))
        setMessage('当前人脸检测未添加摄像头，请先添加摄像头。')
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
    setMessage('正在添加摄像头并启用人脸检测...')
    try {
      const payload = await requestFaceConfig(cameraName)
      await requestFaceConfig(cameraName, { ...payload.detect_face, enable: true })
      await refreshCameraList()
      await loadConfig(cameraName)
      setMessage(`添加成功：${cameraName} 已启用人脸检测。`)
    } catch (error) {
      setMessage(`添加失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraAction(false)
    }
  }

  const removeCameraFromFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在停用该摄像头的人脸检测...')
    try {
      const payload = await requestFaceConfig(cameraName)
      await requestFaceConfig(cameraName, { ...payload.detect_face, enable: false })
      const items = await refreshCameraList()
      const nextCamera = items.find((camera) => isAiVisionFeatureEnabled(camera, 'detect_face'))?.shm_name || ''
      if (form.cameraName === cameraName && nextCamera) {
        await loadConfig(nextCamera)
      } else if (form.cameraName === cameraName) {
        setFaceConfig(defaultFaceConfig)
        setForm({ ...defaultForm, cameraName: '' })
      }
      setMessage(`停用成功：${cameraName} 已关闭人脸检测。`)
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
    let yawThreshold: number[]
    try {
      const parsedRoi = JSON.parse(form.roiPos)
      const parsedYaw = JSON.parse(form.yawThreshold)
      if (!Array.isArray(parsedRoi) || !Array.isArray(parsedYaw)) {
        throw new Error('ROI 和偏航角阈值必须是数组')
      }
      roiPos = parsedRoi
      yawThreshold = parsedYaw
    } catch (error) {
      setMessage(`保存失败：ROI 或偏航角阈值不是合法 JSON。${error instanceof Error ? error.message : ''}`)
      return
    }

    const faceScoreThreshold = Number(form.faceScoreThreshold)
    const alarmInterval = Number(form.alarmInterval)
    if (!Number.isFinite(faceScoreThreshold) || !Number.isFinite(alarmInterval)) {
      setMessage('保存失败：人脸置信度阈值和告警间隔必须是数字。')
      return
    }

    const nextConfig: FaceConfig = {
      ...faceConfig,
      enable: true,
      value: {
        ...faceConfig.value,
        roi_pos: roiPos,
        FACE_SCORE_THR: faceScoreThreshold,
        YAW_THRESHOLD: yawThreshold,
        alarm_interval: alarmInterval,
      },
      alarm: faceConfig.alarm || defaultFaceConfig.alarm,
    }

    setSaving(true)
    setMessage('正在保存配置...')
    try {
      const payload = await requestFaceConfig(shmName, nextConfig)
      setFaceConfig(payload.detect_face)
      setForm(toForm(payload))
      const items = await refreshCameraList()
      setMessage(`保存成功：${getCameraDisplayName(payload.shm_name, payload.name, items)} 的人脸检测配置已更新。`)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const applyDayPreset = () => {
    setForm((prev) => ({
      ...prev,
      faceScoreThreshold: '0.6',
      yawThreshold: '[0,0.3]',
      alarmInterval: '5.0',
    }))
    setMessage('已应用白天参数预设，确认后请保存配置。')
  }

  const applyNightPreset = () => {
    setForm((prev) => ({
      ...prev,
      faceScoreThreshold: '0.5',
      yawThreshold: '[0,0.35]',
      alarmInterval: '5.0',
    }))
    setMessage('已应用夜间参数预设，确认后请保存配置。')
  }

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_face'))

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title="人脸检测"
          subtitle="人脸识别实时监控面板"
          departmentLabel="福达新材院"
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="人脸检测监控" feature="detect_face" presentation="feature-dashboard" />
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
                feature="detect_face"
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
                  title="人脸检测 ROI 绘制"
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
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="维护当前摄像头的人脸识别阈值与区域参数。" actions={<Badge variant="outline">AiVision detect_face</Badge>} />
              <DetectionConfigCardContent className="space-y-5">
                <AiVisionPresetActions
                  disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
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
                      disabled={cameraLoading || loading || saving || cameraAction || featureCameras.length === 0}
                    >
                      <SelectTrigger id="face-camera" className="w-full">
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
                    <Label htmlFor="face-score">人脸置信度阈值</Label>
                    <Input
                      id="face-score"
                      value={form.faceScoreThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, faceScoreThreshold: event.target.value }))}
                      placeholder="0.6"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="face-yaw">偏航角阈值</Label>
                    <Input
                      id="face-yaw"
                      value={form.yawThreshold}
                      onChange={(event) => setForm((prev) => ({ ...prev, yawThreshold: event.target.value }))}
                      placeholder="[0,0.3]"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="face-interval">告警间隔</Label>
                    <Input
                      id="face-interval"
                      value={form.alarmInterval}
                      onChange={(event) => setForm((prev) => ({ ...prev, alarmInterval: event.target.value }))}
                      placeholder="5.0"
                    />
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
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!isAdmin || cameraAction || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />
            </TabsContent>

            <TabsContent value="model" className="space-y-6">
              <Suspense fallback={<LazyConfigFallback label="正在加载模型配置..." />}>
                <AiVisionModelConfig requiredModels={['yolo_face']} />
              </Suspense>
            </TabsContent>

            <TabsContent value="alarm" className="space-y-6">
              <AlarmPushConfig
                alarm={faceConfig.alarm}
                disabled={!isAdmin || loading || saving || cameraAction || !form.cameraName}
                saving={saving}
                message={message}
                onChange={(alarm) => setFaceConfig((prev) => ({ ...prev, alarm: normalizeFeatureAlarmConfig(alarm) }))}
                onSave={saveConfig}
              />
            </TabsContent>
          </Tabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}
