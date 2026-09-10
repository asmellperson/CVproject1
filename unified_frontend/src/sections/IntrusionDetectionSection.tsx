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
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
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
  return JSON.stringify(linePoints ?? [])
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
    setBlocks(defaultBlocks)
    if (!shmName) {
      setMessage('读取失败：请先选择摄像头。')
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

  const loadCameras = async () => {
    setCameraLoading(true)
    try {
      const items = await getAiVisionCameras()
      setCameras(items)
      const enabledCameras = items.filter((camera) => isAiVisionFeatureEnabled(camera, 'blocks'))
      const enabledCamera = enabledCameras.find((camera) => camera.shm_name === selectedCameraRef.current) || enabledCameras[0]
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
      await requestBlocksConfig(cameraName, { ...payload.blocks, enable: true })
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
      await requestBlocksConfig(cameraName, { ...payload.blocks, enable: false })
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

    if (loading || loadedCameraRef.current !== shmName) {
      setMessage('保存失败：请先成功读取当前摄像头的配置。')
      return
    }
    const requestId = configRequestRef.current

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
        <DetectionPageHeader
          title="区域入侵检测"
          subtitle="警戒区域实时监控面板"
          departmentLabel="福达新材院"
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <AiVisionMonitor title="区域入侵检测监控" feature="blocks" presentation="feature-dashboard" />
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
              <Card className={DETECTION_CONFIG_CARD_CLASS}>
              <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="维护当前摄像头的区域入侵检测参数。" actions={<Badge variant="outline">AiVision blocks</Badge>} />
              <DetectionConfigCardContent className="space-y-5">
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
              </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={!isAdmin || cameraAction || !form.cameraName} onReload={() => loadConfig()} onSave={saveConfig} />
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
          </DetectionConfigTabs>
        </TabsContent>
      </Tabs>
    </div>
  )
}
