import { useEffect, useState } from 'react'
import { Bell, Box, Camera, MousePointer2, RefreshCw, Save, ScanFace, SlidersHorizontal, Waypoints } from 'lucide-react'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { normalizeFeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import { AiVisionModelConfig } from '@/components/AiVisionModelConfig'
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

async function requestFaceConfig(shmName: string, init?: RequestInit) {
  const response = await fetch(`/api/ai/face-config/${encodeURIComponent(shmName)}`, { ...init, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${response.status} ${response.statusText}${detail ? ` ${detail}` : ''}`)
  }
  const payload = (await response.json()) as FaceConfigResponse | FaceConfig
  if ('detect_face' in payload) return payload
  return {
    camera_id: 0,
    name: shmName,
    shm_name: shmName,
    camera_enable: true,
    detect_face: payload,
  }
}

interface FaceDetectionSectionProps {
  department?: string
}

export function FaceDetectionSection({ department }: FaceDetectionSectionProps) {
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
      const items = await getAiVisionCameras(department)
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
  }, [department])

  const refreshCameraList = async () => {
    const items = await getAiVisionCameras(department)
    setCameras(items)
    return items
  }

  const addCameraToFeature = async (cameraName: string) => {
    setCameraAction(true)
    setMessage('正在添加摄像头并启用人脸检测...')
    try {
      const payload = await requestFaceConfig(cameraName)
      await requestFaceConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_face, enable: true }),
      })
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
      await requestFaceConfig(cameraName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload.detect_face, enable: false }),
      })
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
      const payload = await requestFaceConfig(shmName, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(nextConfig),
      })
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

  const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, 'detect_face'))

  return (
    <div className="space-y-6">
      <Tabs defaultValue="monitor" className="space-y-6">
        <TabsList className="grid h-auto w-full max-w-md grid-cols-2 p-1">
          <TabsTrigger value="monitor" className="gap-2 py-2">
            <ScanFace className="h-4 w-4" />
            实时监控
          </TabsTrigger>
          <TabsTrigger value="config" className="gap-2 py-2">
            <Waypoints className="h-4 w-4" />
            配置管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="monitor" className="space-y-6">
          <AiVisionMonitor title="人脸检测监控" feature="detect_face" />
        </TabsContent>

        <TabsContent value="config" className="space-y-6">
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
                feature="detect_face"
                currentCameraName={form.cameraName}
                disabled={!isAdmin || cameraLoading || loading || saving || cameraAction}
                onSelectCamera={(cameraName) => {
                  setForm((prev) => ({ ...prev, cameraName }))
                  loadConfig(cameraName)
                }}
                onAddCamera={addCameraToFeature}
                onRemoveCamera={removeCameraFromFeature}
                department={department}
              />
            </TabsContent>

            <TabsContent value="roi" className="space-y-6">
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
            </TabsContent>

            <TabsContent value="params" className="space-y-6">
              <Card className="border-slate-200 bg-white/95">
              <CardHeader className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
                <CardTitle className="text-lg">配置表单</CardTitle>
                <Badge variant="outline" className="border-slate-300 text-slate-600">
                  AiVision detect_face
                </Badge>
              </CardHeader>
              <CardContent className="space-y-5">
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

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
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
              <AiVisionModelConfig requiredModels={['yolo_face']} />
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
