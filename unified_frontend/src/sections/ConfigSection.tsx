import { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Save, RotateCcw, Video, Shield, Box, CheckCircle2, Bell, UserRound, Smartphone, Moon, Settings2, Plus, Trash2, Building2, Car, MousePointer2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { GuardRoomVehicleRoiEditor } from '@/components/guard_room/GuardRoomVehicleRoiEditor'
import { formatVehicleRoiText, parseVehicleRoiText } from '@/components/guard_room/vehicleRoiGeometry'
import {
  createGuardRoomSiteCamera,
  deleteGuardRoomCamera,
  getGuardRoomSiteConfig,
  getGuardRoomSiteStatus,
  restartGuardRoomSiteRuntime,
  saveGuardRoomSiteConfig,
} from '@/lib/api'
import { useAuth } from '@/auth/useAuth'
import { cn } from '@/lib/utils'
import type { GuardRoomSite } from '@/types'
// ==================== 类型定义 ====================

type AppConfigPayload = {
  video: {
    source: string
    source_cam1: string
    source_cam2: string
    source_cam3: string
    process_every_n_frames: number
    output_dir: string
    save_annotated_video: boolean
    annotated_video_fps: number
    reconnect_seconds: number
    jpeg_quality: number
    camera_buffer_size: number
  }
  models: {
    detector_model: string
    vehicle_detector_model: string
    uniform_cls_model: string
    pose_model_task: string
    detector_conf: number
    phone_conf: number
    vehicle_conf: number
    detector_iou: number
    detector_imgsz: number
    vehicle_imgsz: number
    tracker: string
    device: string
    uniform_cls_imgsz: number
    uniform_cls_conf: number
  }
  room: {
    frame_width: number
    frame_height: number
  }
  rules: {
    absent_seconds: number
    phone_seconds: number
    prone_sleep_seconds: number
    vehicle_occlusion_seconds: number
    phone_near_person_px: number
    phone_near_head_px: number
    vehicle_near_px: number
    vehicle_roi: [number, number][]
    vehicle_exit_direction: string
    vehicle_direction_min_delta_ratio: number
    static_motion_threshold: number
    prone_head_down_ratio_threshold: number
    prone_bbox_height_ratio_threshold: number
    prone_consecutive_frames: number
    state_ttl_seconds: number
    phone_window_seconds: number
    phone_min_hits_in_window: number
    phone_grace_seconds: number
    guard_hold_seconds: number
    dual_sync_seconds: number
    absent_alarm_seconds: number
    alarm_cooldown_absent: number
    alarm_cooldown_phone: number
    alarm_cooldown_prone_sleep: number
    alarm_cooldown_vehicle_unattended: number
  }
  classes: {
    person: number
    play_phone: number
    vehicle_bicycle: number
    vehicle_car: number
    vehicle_motorcycle: number
  }
  runtime: {
    show_window: boolean
    debug: boolean
    draw_debug: boolean
    max_alarm_history: number
    enable_vehicle_unattended: boolean
    vehicle_camera_id: string
  }
  wechat: {
    enable: boolean
    corpid: string
    corpsecret: string
    agentid: number
    alarm_user: string
    camera_name: string
    clip_seconds: number
    enable_phone: boolean
    enable_absent: boolean
    enable_prone_sleep: boolean
  }
}

const defaultConfig: AppConfigPayload = {
  video: {
    source: '',
    source_cam1: '',
    source_cam2: '',
    source_cam3: '',
    process_every_n_frames: 3,
    output_dir: 'outputs',
    save_annotated_video: false,
    annotated_video_fps: 10,
    reconnect_seconds: 1.0,
    jpeg_quality: 80,
    camera_buffer_size: 1,
  },
  models: {
    detector_model: 'yolo11n.pt',
    vehicle_detector_model: 'yolo11n.pt',
    uniform_cls_model: '',
    pose_model_task: '',
    detector_conf: 0.35,
    phone_conf: 0.35,
    vehicle_conf: 0.35,
    detector_iou: 0.45,
    detector_imgsz: 960,
    vehicle_imgsz: 960,
    tracker: 'bytetrack.yaml',
    device: '',
    uniform_cls_imgsz: 224,
    uniform_cls_conf: 0.75,
  },
  room: {
    frame_width: 1920,
    frame_height: 1080,
  },
  rules: {
    absent_seconds: 900,
    phone_seconds: 300,
    prone_sleep_seconds: 300,
    vehicle_occlusion_seconds: 2,
    phone_near_person_px: 220,
    phone_near_head_px: 160,
    vehicle_near_px: 160,
    vehicle_roi: [[0, 0], [1, 0], [1, 1], [0, 1]],
    vehicle_exit_direction: 'any',
    vehicle_direction_min_delta_ratio: 0.03,
    static_motion_threshold: 8.0,
    prone_head_down_ratio_threshold: 0.22,
    prone_bbox_height_ratio_threshold: 0.18,
    prone_consecutive_frames: 8,
    state_ttl_seconds: 20,
    phone_window_seconds: 4,
    phone_min_hits_in_window: 6,
    phone_grace_seconds: 3,
    guard_hold_seconds: 1.3,
    dual_sync_seconds: 1.5,
    absent_alarm_seconds: 60.0,
    alarm_cooldown_absent: 120,
    alarm_cooldown_phone: 60,
    alarm_cooldown_prone_sleep: 300,
    alarm_cooldown_vehicle_unattended: 300,

  },
  classes: {
    person: 0,
    play_phone: 1,
    vehicle_bicycle: 1,
    vehicle_car: 2,
    vehicle_motorcycle: 3,
  },
  runtime: {
    show_window: false,
    debug: true,
    draw_debug: false,
    max_alarm_history: 1000,
    enable_vehicle_unattended: true,
    vehicle_camera_id: 'cam1',
  },
  wechat: {
    enable: false,
    corpid: '',
    corpsecret: '',
    agentid: 1000050,
    alarm_user: '',
    camera_name: '值班室双摄像头',
    clip_seconds: 5.0,
    enable_phone: true,
    enable_absent: true,
    enable_prone_sleep: true,
  },
}

type AppConfigPatch = {
  video?: Partial<AppConfigPayload['video']>
  models?: Partial<AppConfigPayload['models']>
  room?: Partial<AppConfigPayload['room']>
  rules?: Partial<AppConfigPayload['rules']>
  classes?: Partial<AppConfigPayload['classes']>
  runtime?: Partial<AppConfigPayload['runtime']>
  wechat?: Partial<AppConfigPayload['wechat']>
}

function mergeConfig(data: AppConfigPatch | null | undefined): AppConfigPayload {
  return {
    video: { ...defaultConfig.video, ...(data?.video || {}) },
    models: { ...defaultConfig.models, ...(data?.models || {}) },
    room: { ...defaultConfig.room, ...(data?.room || {}) },
    rules: { ...defaultConfig.rules, ...(data?.rules || {}) },
    classes: { ...defaultConfig.classes, ...(data?.classes || {}) },
    runtime: { ...defaultConfig.runtime, ...(data?.runtime || {}) },
    wechat: { ...defaultConfig.wechat, ...(data?.wechat || {}) },
  }
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  return fallback
}

// ==================== 主组件 ====================

type ConfigSectionProps = {
  site: GuardRoomSite | null
  sites: GuardRoomSite[]
  selectedSiteId: number | null
  loadingSites: boolean
  siteError?: string
  onSelectSite: (siteId: number) => void
  department?: string
  onCreateSite: (name: string) => Promise<GuardRoomSite>
  onDeleteSite: (siteId: number) => Promise<void>
  onSitesChanged?: () => void | Promise<void>
}

function ConfigSection({
  site,
  sites,
  selectedSiteId,
  loadingSites,
  siteError,
  onSelectSite,
  department,
  onCreateSite,
  onDeleteSite,
  onSitesChanged,
}: ConfigSectionProps) {
  const { isAdmin } = useAuth()
  const [activeTab, setActiveTab] = useState('sites')
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<AppConfigPayload>(defaultConfig)
  const [cameraName, setCameraName] = useState('')
  const [cameraRtsp, setCameraRtsp] = useState('')
  const [cameraBusy, setCameraBusy] = useState(false)
  const [cameraDialogOpen, setCameraDialogOpen] = useState(false)
  const [roiDialogOpen, setRoiDialogOpen] = useState(false)
  const [siteName, setSiteName] = useState('')
  const [siteBusy, setSiteBusy] = useState(false)
  const [siteActionError, setSiteActionError] = useState('')

  const loadConfig = useCallback(async () => {
    if (!site) {
      setConfig(defaultConfig)
      return
    }
    const next = await getGuardRoomSiteConfig(site.id, department)
    setConfig(mergeConfig(next))
  }, [department, site])

  useEffect(() => {
    setLoading(true)
    loadConfig()
      .catch((err) => {
        console.error('加载配置失败:', err)
      })
      .finally(() => setLoading(false))
  }, [loadConfig])

  useEffect(() => {
    if (!site && activeTab !== 'sites') {
      setActiveTab('sites')
    }
  }, [activeTab, site])

  const [saveError, setSaveError] = useState('')
  const [saving, setSaving] = useState(false)
  const [savePhase, setSavePhase] = useState('')  // 显示当前阶段

  const handleSave = async () => {
    if (!site) {
      setSaveError('请先选择保安室。')
      return
    }
    if (!isAdmin) {
      setSaveError('当前账号为 viewer，只能查看配置。')
      return
    }
    setSaveError('')
    setSaving(true)
    try {
      // 阶段 1: 保存配置
      setSavePhase('正在保存配置...')
      await saveGuardRoomSiteConfig(site.id, {
        video: config.video,
        models: config.models,
        room: config.room,
        rules: config.rules,
        classes: config.classes,
        runtime: config.runtime,
        wechat: config.wechat,
      })

      // 阶段 2: 重启算法
      setSavePhase('正在重启算法（约 15 秒）...')
      await restartGuardRoomSiteRuntime(site.id)

      // 阶段 3: 等后端真的起来
      setSavePhase('等待算法就绪...')
      await waitUntilRunning(20000)  // 最多等 20 秒

      setSavePhase('')
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      await loadConfig()
    } catch (err: unknown) {
      console.error('保存配置失败:', err)
      setSaveError(getErrorMessage(err, '保存失败'))
      setSavePhase('')
    } finally {
      setSaving(false)
    }
  }

// 轮询 /api/status 直到 running=true 或超时
async function waitUntilRunning(timeoutMs: number) {
  if (!site) throw new Error('请先选择保安室')
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const s = await getGuardRoomSiteStatus(site.id, department)
      if (s.running && !s.error) return
    } catch {
      // 重启期间 API 可能短暂不可达，继续等
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('算法启动超时，请检查后端日志')
}

  const handleAddCamera = async () => {
    if (!site || !isAdmin || cameraBusy) return
    const name = cameraName.trim()
    const rtsp = cameraRtsp.trim()
    if (!name || !rtsp) {
      setSaveError('摄像头名称和 RTSP 地址都不能为空。')
      return
    }
    setCameraBusy(true)
    setSaveError('')
    try {
      await createGuardRoomSiteCamera(site.id, { name, rtsp_url: rtsp })
      setCameraName('')
      setCameraRtsp('')
      setCameraDialogOpen(false)
      await onSitesChanged?.()
    } catch (err: unknown) {
      setSaveError(getErrorMessage(err, '添加摄像头失败'))
    } finally {
      setCameraBusy(false)
    }
  }

  const handleDeleteCamera = async (cameraId: number) => {
    if (!isAdmin || cameraBusy) return
    setCameraBusy(true)
    setSaveError('')
    try {
      await deleteGuardRoomCamera(cameraId)
      await onSitesChanged?.()
    } catch (err: unknown) {
      setSaveError(getErrorMessage(err, '删除摄像头失败'))
    } finally {
      setCameraBusy(false)
    }
  }

  const handleCreateSite = async () => {
    const name = siteName.trim()
    if (!name || siteBusy || !isAdmin) return
    setSiteBusy(true)
    setSiteActionError('')
    try {
      await onCreateSite(name)
      setSiteName('')
    } catch (err: unknown) {
      setSiteActionError(getErrorMessage(err, '新增保安室失败'))
    } finally {
      setSiteBusy(false)
    }
  }

  const handleDeleteSite = async (siteId: number) => {
    if (!isAdmin || siteBusy) return
    setSiteBusy(true)
    setSiteActionError('')
    try {
      await onDeleteSite(siteId)
    } catch (err: unknown) {
      setSiteActionError(getErrorMessage(err, '删除保安室失败'))
    } finally {
      setSiteBusy(false)
    }
  }

  // 便捷更新函数
  const setVideo = (patch: Partial<AppConfigPayload['video']>) =>
    setConfig({ ...config, video: { ...config.video, ...patch } })
  const setModels = (patch: Partial<AppConfigPayload['models']>) =>
    setConfig({ ...config, models: { ...config.models, ...patch } })
  const setRoom = (patch: Partial<AppConfigPayload['room']>) =>
    setConfig({ ...config, room: { ...config.room, ...patch } })
  const setRules = (patch: Partial<AppConfigPayload['rules']>) =>
    setConfig({ ...config, rules: { ...config.rules, ...patch } })
  const setClasses = (patch: Partial<AppConfigPayload['classes']>) =>
    setConfig({ ...config, classes: { ...config.classes, ...patch } })
  const setRuntime = (patch: Partial<AppConfigPayload['runtime']>) =>
    setConfig({ ...config, runtime: { ...config.runtime, ...patch } })
  const setWechat = (patch: Partial<AppConfigPayload['wechat']>) =>
    setConfig({ ...config, wechat: { ...config.wechat, ...patch } })
  const selectedVehicleCameraId = config.runtime.vehicle_camera_id || 'cam1'
  const baseVehicleCameraOptions = (site?.cameras || []).map((camera, index) => ({
    id: `cam${index + 1}`,
    label: camera.name || `摄像头 ${index + 1}`,
    enabled: camera.enabled,
  }))
  const vehicleCameraOptions = baseVehicleCameraOptions.some((camera) => camera.id === selectedVehicleCameraId)
    ? baseVehicleCameraOptions
    : [
        ...baseVehicleCameraOptions,
        {
          id: selectedVehicleCameraId,
          label: `${selectedVehicleCameraId}（当前配置）`,
          enabled: true,
        },
      ]
  const selectedVehicleCamera = vehicleCameraOptions.find((camera) => camera.id === selectedVehicleCameraId)
  const vehicleRoiText = formatVehicleRoiText(config.rules.vehicle_roi.length ? config.rules.vehicle_roi : defaultConfig.rules.vehicle_roi)

  return (
    <div className="space-y-6 text-slate-950 dark:text-slate-100">
      {/* 顶部标题栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">配置管理</h2>
          <p className="text-slate-500">系统参数和规则配置</p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:gap-3">
          {saved && (
            <Badge className="bg-green-500 gap-1">
              <CheckCircle2 className="w-4 h-4" />
              已保存并生效
            </Badge>
          )}
          {savePhase && (
            <Badge className="bg-blue-500 gap-1 animate-pulse">
              {savePhase}
            </Badge>
          )}
          {saveError && (
            <Badge variant="destructive" className="gap-1 max-w-xs truncate" title={saveError}>
              {saveError}
            </Badge>
          )}
          {activeTab !== 'sites' && site ? (
            <>
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => loadConfig().catch(() => undefined)}
                disabled={saving}
              >
                <RotateCcw className="w-4 h-4" />
                重载配置
              </Button>
              <Button
                className="gap-2"
                onClick={() => handleSave()}
                disabled={!isAdmin || saving}
              >
                <Save className="w-4 h-4" />
                {saving ? '处理中...' : '保存配置'}
              </Button>
            </>
          ) : null}
        </div>
      </div>

      {/* 标签页 */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="grid h-auto w-full max-w-3xl grid-cols-2 p-1 sm:grid-cols-5">
          <TabsTrigger value="sites" className="gap-2">
            <Building2 className="w-4 h-4" />
            保安室管理
          </TabsTrigger>
          <TabsTrigger value="video" className="gap-2" disabled={!site}>
            <Video className="w-4 h-4" />
            视频源
          </TabsTrigger>
          <TabsTrigger value="rules" className="gap-2" disabled={!site}>
            <Shield className="w-4 h-4" />
            检测规则
          </TabsTrigger>
          <TabsTrigger value="model" className="gap-2" disabled={!site}>
            <Box className="w-4 h-4" />
            模型配置
          </TabsTrigger>
          <TabsTrigger value="wechat" className="gap-2" disabled={!site}>
            <Bell className="w-4 h-4" />
            报警推送
          </TabsTrigger>
        </TabsList>

        <TabsContent value="sites" className="space-y-6">
          <Card className="overflow-hidden border-slate-200/80 bg-white/95 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <CardHeader className="border-b border-slate-100 bg-gradient-to-r from-white to-slate-50/80 dark:border-slate-800 dark:from-slate-900 dark:to-slate-900">
              <CardTitle className="flex items-center gap-2 text-[#10264d] dark:text-slate-100">
                <Building2 className="w-5 h-5 text-blue-600" />
                保安室管理
              </CardTitle>
              <CardDescription>维护保安行为规范检测的保安室，并选择要配置的对象。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5 bg-[#f8fbff] p-4 dark:bg-slate-950/50 sm:p-5 lg:p-6">
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                <Input
                  value={siteName}
                  onChange={(event) => setSiteName(event.target.value)}
                  placeholder="新增保安室名称，例如：一厂区南门保安室"
                  disabled={!isAdmin || siteBusy}
                />
                <Button className="gap-2" onClick={handleCreateSite} disabled={!isAdmin || siteBusy || !siteName.trim()}>
                  <Plus className="h-4 w-4" />
                  {siteBusy ? '新增中' : '新增保安室'}
                </Button>
              </div>

              {siteActionError || siteError ? (
                <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{siteActionError || siteError}</div>
              ) : null}

              <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
                {loadingSites ? (
                  <div className="px-4 py-5 text-sm text-slate-500">正在加载保安室...</div>
                ) : sites.length === 0 ? (
                  <div className="px-4 py-5 text-sm text-slate-500">暂无保安室，请先新增。</div>
                ) : (
                  sites.map((item) => (
                    <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 last:border-b-0">
                      <button
                        type="button"
                        className="min-w-0 text-left"
                        onClick={() => onSelectSite(item.id)}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{item.name}</span>
                          {item.id === selectedSiteId ? <Badge className="bg-blue-600">当前配置</Badge> : null}
                          <Badge variant={item.enabled ? 'outline' : 'secondary'}>{item.enabled ? '启用' : '停用'}</Badge>
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{item.enabled_camera_count}/{item.camera_count} 路摄像头</div>
                      </button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2 text-red-600 hover:text-red-700"
                        onClick={() => handleDeleteSite(item.id)}
                        disabled={!isAdmin || siteBusy}
                      >
                        <Trash2 className="h-4 w-4" />
                        删除
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ==================== 视频源 ==================== */}
        <TabsContent value="video" className="space-y-6">
          {!site ? (
            <Card>
              <CardContent className="p-6 text-sm text-slate-500">请先在保安室管理中新增或选择一个保安室。</CardContent>
            </Card>
          ) : loading ? (
            <div className="text-slate-500">正在加载配置...</div>
          ) : (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Video className="w-5 h-5 text-blue-600" />
                视频源配置
              </CardTitle>
              <CardDescription>配置多路摄像头视频输入源、抽帧、编码与输出参数</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-4 rounded-lg border border-blue-100 bg-blue-50 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <Label className="text-base font-semibold text-blue-800">当前保安室摄像头</Label>
                    <p className="mt-1 text-xs text-blue-600">每个保安室最多 9 路，按列表顺序参与拼接和联合判定。</p>
                  </div>
                  <Badge variant="outline">{site.enabled_camera_count}/{site.camera_count} 路</Badge>
                </div>

                <div className="overflow-hidden rounded-lg border border-blue-100 bg-white dark:border-slate-800 dark:bg-slate-900">
                  {site.cameras.length === 0 ? (
                    <div className="px-4 py-5 text-sm text-slate-500">当前保安室还没有摄像头。</div>
                  ) : (
                    site.cameras.map((camera) => (
                      <div key={camera.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 last:border-b-0">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{camera.name}</span>
                            <Badge variant={camera.enabled ? 'default' : 'secondary'} className={camera.enabled ? 'bg-emerald-600' : ''}>
                              {camera.enabled ? '启用' : '停用'}
                            </Badge>
                          </div>
                          <div className="mt-1 max-w-full truncate text-xs text-slate-500" title={camera.rtsp_url}>{camera.rtsp_url}</div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-2 text-red-600 hover:text-red-700"
                          onClick={() => handleDeleteCamera(camera.id)}
                          disabled={!isAdmin || cameraBusy}
                        >
                          <Trash2 className="h-4 w-4" />
                          删除
                        </Button>
                      </div>
                    ))
                  )}
                </div>

                <Dialog open={cameraDialogOpen} onOpenChange={setCameraDialogOpen}>
                  <DialogTrigger asChild>
                    <Button className="gap-2" disabled={!isAdmin || cameraBusy || site.cameras.length >= 9}>
                      <Plus className="h-4 w-4" />
                      添加摄像头
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>添加摄像头</DialogTitle>
                      <DialogDescription>为当前保安室添加一路 RTSP 摄像头。</DialogDescription>
                    </DialogHeader>
                    <div className="grid gap-4">
                      <Field label="摄像头名称">
                        <Input
                          value={cameraName}
                          onChange={(e) => setCameraName(e.target.value)}
                          placeholder="摄像头名称"
                          disabled={!isAdmin || cameraBusy}
                        />
                      </Field>
                      <Field label="RTSP 地址">
                        <Input
                          value={cameraRtsp}
                          onChange={(e) => setCameraRtsp(e.target.value)}
                          placeholder="rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101"
                          disabled={!isAdmin || cameraBusy}
                        />
                      </Field>
                    </div>
                    <DialogFooter>
                      <Button variant="outline" onClick={() => setCameraDialogOpen(false)} disabled={cameraBusy}>
                        取消
                      </Button>
                      <Button className="gap-2" onClick={handleAddCamera} disabled={!isAdmin || cameraBusy || !cameraName.trim() || !cameraRtsp.trim()}>
                        <Plus className="h-4 w-4" />
                        {cameraBusy ? '处理中' : '添加摄像头'}
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Field label="输出目录">
                  <Input value={config.video.output_dir} onChange={(e) => setVideo({ output_dir: e.target.value })} />
                </Field>
                <Field label="抽帧间隔">
                  <Input
                    type="number"
                    value={config.video.process_every_n_frames}
                    onChange={(e) => setVideo({ process_every_n_frames: Number(e.target.value) })}
                  />
                </Field>
                <Field label="输出视频 FPS">
                  <Input
                    type="number"
                    value={config.video.annotated_video_fps}
                    onChange={(e) => setVideo({ annotated_video_fps: Number(e.target.value) })}
                  />
                </Field>
                <Field label="重连间隔（秒）">
                  <Input
                    type="number"
                    step="0.1"
                    value={config.video.reconnect_seconds}
                    onChange={(e) => setVideo({ reconnect_seconds: Number(e.target.value) })}
                  />
                </Field>
                <Field label="JPEG 质量">
                  <Input
                    type="number"
                    value={config.video.jpeg_quality}
                    onChange={(e) => setVideo({ jpeg_quality: Number(e.target.value) })}
                  />
                </Field>
                <Field label="摄像头缓冲区">
                  <Input
                    type="number"
                    value={config.video.camera_buffer_size}
                    onChange={(e) => setVideo({ camera_buffer_size: Number(e.target.value) })}
                  />
                </Field>
                <Field label="房间宽度基准">
                  <Input
                    type="number"
                    value={config.room.frame_width}
                    onChange={(e) => setRoom({ frame_width: Number(e.target.value) })}
                  />
                </Field>
                <Field label="房间高度基准">
                  <Input
                    type="number"
                    value={config.room.frame_height}
                    onChange={(e) => setRoom({ frame_height: Number(e.target.value) })}
                  />
                </Field>
              </div>

              <SwitchRow
                id="save_annotated_video"
                label="保存标注视频"
                description="是否保存带标注的检测结果视频"
                checked={config.video.save_annotated_video}
                onChange={(checked) => setVideo({ save_annotated_video: checked })}
              />
              <SwitchRow
                id="show_window"
                label="本地窗口显示"
                description="服务器环境一般保持关闭"
                checked={config.runtime.show_window}
                onChange={(checked) => setRuntime({ show_window: checked })}
              />
            </CardContent>
          </Card>
          )}
        </TabsContent>

        {/* ==================== 检测规则 ==================== */}
        <TabsContent value="rules" className="space-y-6">
          <Card className="overflow-hidden border-slate-200/80 bg-white/95 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <CardHeader className="border-b border-slate-100 bg-gradient-to-r from-white to-slate-50/80">
              <CardTitle className="flex items-center gap-2 text-[#10264d] dark:text-slate-100">
                <Shield className="w-5 h-5 text-green-600" />
                检测规则配置
              </CardTitle>
              <CardDescription>配置离岗、玩手机、趴睡等行为检测的阈值参数</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5 bg-[#f8fbff] p-4 sm:p-5 lg:p-6">
              {/* 离岗相关 */}
              <RuleGroup title="离岗检测" icon={UserRound} tone="green">
                <SliderRow
                  title="离岗触发时间（秒）"
                  description="所有在线摄像头均未见保安后，持续达到该时间即触发离岗报警。"
                  value={config.rules.absent_alarm_seconds}
                  min={10}
                  max={600}
                  step={10}
                  onChange={(v) => setRules({ absent_alarm_seconds: v })}
                  tone="green"
                />
                <SliderRow
                  title="离岗重复报警间隔（秒）"
                  description="同一次离岗报警触发后，至少间隔这么久才允许再次推送离岗报警。"
                  value={config.rules.alarm_cooldown_absent}
                  min={30}
                  max={1800}
                  step={30}
                  onChange={(v) => setRules({ alarm_cooldown_absent: v })}
                  tone="green"
                />
              </RuleGroup>

              {/* 手机检测相关 */}
              <RuleGroup title="手机检测" icon={Smartphone} tone="blue">
                <SliderRow
                  title="持续玩手机多久报警（秒）"
                  description="疑似玩手机状态连续累计达到该时间后，才触发报警。"
                  value={config.rules.phone_seconds}
                  min={0.3}
                  max={600}
                  step={0.1}
                  onChange={(v) => setRules({ phone_seconds: v })}
                  tone="blue"
                />
                <SliderRow
                  title="手机重复报警间隔（秒）"
                  description="同一次手机报警触发后，至少间隔这么久才允许再次推送手机报警。"
                  value={config.rules.alarm_cooldown_phone}
                  min={30}
                  max={1800}
                  step={30}
                  onChange={(v) => setRules({ alarm_cooldown_phone: v })}
                  tone="blue"
                />
                <SliderRow
                  title="统计最近几秒内的手机命中"
                  description="系统只统计最近这段时间内识别到手机的次数，用来过滤偶发误检。"
                  value={config.rules.phone_window_seconds}
                  min={1}
                  max={20}
                  step={1}
                  onChange={(v) => setRules({ phone_window_seconds: v })}
                  tone="blue"
                />
                <SliderRow
                  title="统计窗口内至少识别到几次手机"
                  description="在上面的统计时间内，识别到手机的次数达到该值，才认为证据有效。"
                  value={config.rules.phone_min_hits_in_window}
                  min={1}
                  max={30}
                  step={1}
                  onChange={(v) => setRules({ phone_min_hits_in_window: v })}
                  tone="blue"
                />
                <SliderRow
                  title="短暂漏检宽限时间（秒）"
                  description="手机被遮挡或短暂没识别到时，在该时间内不会立刻清零计时。"
                  value={config.rules.phone_grace_seconds}
                  min={0.5}
                  max={10}
                  step={0.5}
                  onChange={(v) => setRules({ phone_grace_seconds: v })}
                  tone="blue"
                />
                <div className="space-y-4 rounded-xl border border-dashed border-blue-300 bg-blue-50/35 p-4 md:col-span-2">
                  <div>
                    <Label className="text-sm font-semibold text-blue-800">高级参数</Label>
                    <p className="mt-1 text-xs leading-5 text-blue-700/70">通常不需要调整。数值越大越宽松，越容易把附近物体判断为手机。</p>
                  </div>
                  <div className="grid gap-5 md:grid-cols-2">
                    <SliderRow
                      title="手机靠近身体判定范围（px）"
                      description="手机中心点落在人体框附近多大范围内，才认为可能属于这个保安。"
                      value={config.rules.phone_near_person_px}
                      min={50}
                      max={400}
                      step={10}
                      onChange={(v) => setRules({ phone_near_person_px: v })}
                      tone="blue"
                    />
                    <SliderRow
                      title="手机靠近头部判定范围（px）"
                      description="手机中心点距离头部估计位置多近，才认为像是在看手机或接打电话。"
                      value={config.rules.phone_near_head_px}
                      min={50}
                      max={300}
                      step={10}
                      onChange={(v) => setRules({ phone_near_head_px: v })}
                      tone="blue"
                    />
                  </div>
                </div>
              </RuleGroup>

              {/* 趴睡检测相关 */}
              <RuleGroup title="趴睡检测" icon={Moon} tone="purple">
                <SliderRow
                  title="持续趴睡多久报警（秒）"
                  description="疑似趴睡状态连续达到该时间后，才触发报警。"
                  value={config.rules.prone_sleep_seconds}
                  min={60}
                  max={1200}
                  step={30}
                  onChange={(v) => setRules({ prone_sleep_seconds: v })}
                  tone="purple"
                />
                <SliderRow
                  title="趴睡重复报警间隔（秒）"
                  description="同一次趴睡报警触发后，至少间隔这么久才允许再次推送趴睡报警。"
                  value={config.rules.alarm_cooldown_prone_sleep}
                  min={30}
                  max={1800}
                  step={30}
                  onChange={(v) => setRules({ alarm_cooldown_prone_sleep: v })}
                  tone="purple"
                />
                <div className="space-y-4 rounded-xl border border-dashed border-violet-300 bg-violet-50/35 p-4 md:col-span-2">
                  <div>
                    <Label className="text-sm font-semibold text-violet-800">高级参数</Label>
                    <p className="mt-1 text-xs leading-5 text-violet-700/70">通常不需要调整。参数越敏感越容易报警，参数越严格越不容易误报。</p>
                  </div>
                  <div className="grid gap-5 lg:grid-cols-3">
                    <SliderRow
                      title="低头判定灵敏度"
                      description="数值越小越容易判定为低头；数值越大越严格。"
                      value={config.rules.prone_head_down_ratio_threshold}
                      min={0.05}
                      max={0.5}
                      step={0.01}
                      onChange={(v) => setRules({ prone_head_down_ratio_threshold: v })}
                      tone="purple"
                    />
                    <SliderRow
                      title="伏桌/趴下判定灵敏度"
                      description="用于判断人体框是否明显变矮。数值越大越容易认为是在伏桌或趴下。"
                      value={config.rules.prone_bbox_height_ratio_threshold}
                      min={0.05}
                      max={0.5}
                      step={0.01}
                      onChange={(v) => setRules({ prone_bbox_height_ratio_threshold: v })}
                      tone="purple"
                    />
                    <SliderRow
                      title="连续低头确认帧数"
                      description="连续识别到低头达到该帧数后，才认为低头证据有效。"
                      value={config.rules.prone_consecutive_frames}
                      min={1}
                      max={30}
                      step={1}
                      onChange={(v) => setRules({ prone_consecutive_frames: v })}
                      tone="purple"
                    />
                  </div>
                </div>
              </RuleGroup>

              {/* 车辆无人值守检测 */}
              <RuleGroup title="车辆后备箱检查" icon={Car} tone="amber">
                <Field label="车辆检测摄像头">
                  <Select
                    value={selectedVehicleCameraId}
                    onValueChange={(value) => setRuntime({ vehicle_camera_id: value })}
                    disabled={!isAdmin || saving || vehicleCameraOptions.length === 0}
                  >
                    <SelectTrigger className="bg-white">
                      <SelectValue placeholder="选择车辆检测摄像头" />
                    </SelectTrigger>
                    <SelectContent>
                      {vehicleCameraOptions.map((camera) => (
                        <SelectItem key={camera.id} value={camera.id}>
                          {camera.id} · {camera.label}{camera.enabled ? '' : '（停用）'}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs leading-5 text-slate-500">车辆后备箱检查只会在这一台摄像头上运行，保存配置后重启算法生效。</p>
                </Field>
                <SliderRow
                  title="车辆离开确认时间（秒）"
                  description="车辆连续消失达到该时间后，才认为车辆已离开并结算本次检查。"
                  value={config.rules.vehicle_occlusion_seconds}
                  min={1}
                  max={10}
                  step={0.5}
                  onChange={(v) => setRules({ vehicle_occlusion_seconds: v })}
                  tone="amber"
                />
                <SliderRow
                  title="保安靠近车辆范围（px）"
                  description="保安人体框靠近车辆框的容差范围。数值越大越容易判定保安已靠近车辆。"
                  value={config.rules.vehicle_near_px}
                  min={40}
                  max={500}
                  step={10}
                  onChange={(v) => setRules({ vehicle_near_px: v })}
                  tone="amber"
                />
                <Field label="出厂车辆方向">
                  <Select
                    value={config.rules.vehicle_exit_direction || 'any'}
                    onValueChange={(value) => setRules({ vehicle_exit_direction: value })}
                    disabled={!isAdmin || saving}
                  >
                    <SelectTrigger className="bg-white">
                      <SelectValue placeholder="选择出厂方向" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">不限制方向</SelectItem>
                      <SelectItem value="down">画面中向下</SelectItem>
                      <SelectItem value="up">画面中向上</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs leading-5 text-slate-500">门上方摄像头按车辆在画面中的上下移动判断出厂；进厂方向应与这里相反。</p>
                </Field>
                <SliderRow
                  title="方向判定最小位移比例"
                  description="车辆中心点移动超过画面宽/高的该比例，才认定方向有效。数值越大越不容易受检测框抖动影响。"
                  value={config.rules.vehicle_direction_min_delta_ratio}
                  min={0.01}
                  max={0.2}
                  step={0.01}
                  onChange={(v) => setRules({ vehicle_direction_min_delta_ratio: v })}
                  tone="amber"
                />
                <SliderRow
                  title="车辆无人值守重复报警间隔（秒）"
                  description="同一类车辆无人值守报警触发后，至少间隔这么久才允许再次推送。"
                  value={config.rules.alarm_cooldown_vehicle_unattended}
                  min={30}
                  max={1800}
                  step={30}
                  onChange={(v) => setRules({ alarm_cooldown_vehicle_unattended: v })}
                  tone="amber"
                />
                <div className="md:col-span-2">
                  <div className="flex flex-col gap-3 rounded-lg border border-amber-100 bg-amber-50/45 p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-slate-800">车辆检测 ROI</div>
                      <div className="mt-1 text-xs leading-5 text-slate-500">
                        当前按 {selectedVehicleCameraId}{selectedVehicleCamera?.label ? ` · ${selectedVehicleCamera.label}` : ''} 的单路画面绘制，已配置 {config.rules.vehicle_roi.length || defaultConfig.rules.vehicle_roi.length} 个顶点。
                      </div>
                    </div>
                    <Dialog open={roiDialogOpen} onOpenChange={setRoiDialogOpen}>
                      <DialogTrigger asChild>
                        <Button variant="outline" className="gap-2 bg-white" disabled={!isAdmin || loading || saving || !site || !selectedVehicleCameraId}>
                          <MousePointer2 className="h-4 w-4" />
                          绘制车辆 ROI
                        </Button>
                      </DialogTrigger>
                      <DialogContent className="max-h-[92dvh] max-w-[calc(100vw-1.5rem)] overflow-y-auto sm:max-w-6xl">
                        <DialogHeader>
                          <DialogTitle>绘制车辆检测 ROI</DialogTitle>
                          <DialogDescription>
                            使用当前车辆检测摄像头的单路画面绘制 ROI，保存配置后重启算法生效。
                          </DialogDescription>
                        </DialogHeader>
                        <GuardRoomVehicleRoiEditor
                          siteId={site?.id ?? null}
                          department={department}
                          cameraId={selectedVehicleCameraId}
                          cameraLabel={selectedVehicleCamera?.label}
                          roi={config.rules.vehicle_roi}
                          fallbackSize={{
                            width: config.room.frame_width,
                            height: config.room.frame_height,
                          }}
                          disabled={!isAdmin || loading || saving || !site}
                          saving={saving}
                          message="车辆 ROI 使用当前车辆检测摄像头的单路画面绘制，并以归一化坐标写入配置。"
                          onChange={(vehicleRoi) => setRules({ vehicle_roi: vehicleRoi })}
                          onSave={handleSave}
                        />
                      </DialogContent>
                    </Dialog>
                  </div>
                </div>
                <Field label="车辆检测 ROI（归一化坐标，每行 x,y）">
                  <Textarea
                    className="min-h-28 font-mono text-sm"
                    value={vehicleRoiText}
                    onChange={(e) => setRules({ vehicle_roi: parseVehicleRoiText(e.target.value) })}
                    disabled={!isAdmin || saving}
                  />
                </Field>
              </RuleGroup>

              {/* 识别稳定性参数 */}
              <RuleGroup title="识别稳定性参数" icon={Settings2} tone="amber">
                <SliderRow
                  title="静止判定灵敏度"
                  description="用于趴睡判断。人体移动小于该范围时，认为基本静止。数值越大越容易判定为静止。"
                  value={config.rules.static_motion_threshold}
                  min={1}
                  max={20}
                  step={1}
                  onChange={(v) => setRules({ static_motion_threshold: v })}
                  tone="amber"
                />
                <SliderRow
                  title="目标短暂消失保留时间（秒）"
                  description="人员被遮挡或短暂丢失后，系统继续保留其跟踪状态的时间。超过该时间会按新目标处理。"
                  value={config.rules.state_ttl_seconds}
                  min={5}
                  max={120}
                  step={1}
                  onChange={(v) => setRules({ state_ttl_seconds: v })}
                  tone="amber"
                />
                <SliderRow
                  title="保安短暂丢失宽限时间（秒）"
                  description="保安被短暂遮挡或制服识别漏判时，在该时间内仍视为保安在场，避免离岗误报。"
                  value={config.rules.guard_hold_seconds}
                  min={0.5}
                  max={10}
                  step={0.1}
                  onChange={(v) => setRules({ guard_hold_seconds: v })}
                  tone="amber"
                />
              </RuleGroup>
            </CardContent>
          </Card>
        </TabsContent>


        {/* ==================== 模型配置 ==================== */}
        <TabsContent value="model" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Box className="w-5 h-5 text-purple-600" />
                模型配置
              </CardTitle>
              <CardDescription>配置检测模型、制服分类模型、类别映射和运行时参数</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <Field label="检测模型">
                <Input value={config.models.detector_model} onChange={(e) => setModels({ detector_model: e.target.value })} />
              </Field>
              <Field label="车辆检测模型">
                <Input value={config.models.vehicle_detector_model} onChange={(e) => setModels({ vehicle_detector_model: e.target.value })} placeholder="例如 yolo11n.pt" />
              </Field>
              <Field label="制服分类模型">
                <Input value={config.models.uniform_cls_model} onChange={(e) => setModels({ uniform_cls_model: e.target.value })} placeholder="路径留空则不启用制服分类" />
              </Field>
              <Field label="姿态模型">
                <Input value={config.models.pose_model_task} onChange={(e) => setModels({ pose_model_task: e.target.value })} placeholder="文件不存在则自动关闭姿态估计" />
              </Field>
              <Field label="跟踪器">
                <Input value={config.models.tracker} onChange={(e) => setModels({ tracker: e.target.value })} />
              </Field>
              <Field label="运行设备">
                <Input value={config.models.device} onChange={(e) => setModels({ device: e.target.value })} placeholder="留空为默认；可填 0 / cpu" />
              </Field>
              <Field label="人体检测置信度">
                <Input type="number" step="0.01" value={config.models.detector_conf} onChange={(e) => setModels({ detector_conf: Number(e.target.value) })} />
              </Field>
              <Field label="手机检测置信度">
                <Input type="number" step="0.01" value={config.models.phone_conf} onChange={(e) => setModels({ phone_conf: Number(e.target.value) })} />
              </Field>
              <Field label="车辆检测置信度">
                <Input type="number" step="0.01" value={config.models.vehicle_conf} onChange={(e) => setModels({ vehicle_conf: Number(e.target.value) })} />
              </Field>
              <Field label="检测 IOU">
                <Input type="number" step="0.01" value={config.models.detector_iou} onChange={(e) => setModels({ detector_iou: Number(e.target.value) })} />
              </Field>
              <Field label="车辆检测输入尺寸">
                <Input type="number" value={config.models.vehicle_imgsz} onChange={(e) => setModels({ vehicle_imgsz: Number(e.target.value) })} />
              </Field>
              <Field label="制服分类置信度">
                <Input type="number" step="0.01" value={config.models.uniform_cls_conf} onChange={(e) => setModels({ uniform_cls_conf: Number(e.target.value) })} />
              </Field>

              {/* 类别ID */}
              <Field label="person 类别 ID">
                <Input type="number" value={config.classes.person} onChange={(e) => setClasses({ person: Number(e.target.value) })} />
              </Field>
              <Field label="play_phone 类别 ID">
                <Input type="number" value={config.classes.play_phone} onChange={(e) => setClasses({ play_phone: Number(e.target.value) })} />
              </Field>
              <Field label="vehicle_bicycle 类别 ID">
                <Input type="number" value={config.classes.vehicle_bicycle} onChange={(e) => setClasses({ vehicle_bicycle: Number(e.target.value) })} />
              </Field>
              <Field label="vehicle_car 类别 ID">
                <Input type="number" value={config.classes.vehicle_car} onChange={(e) => setClasses({ vehicle_car: Number(e.target.value) })} />
              </Field>
              <Field label="vehicle_motorcycle 类别 ID">
                <Input type="number" value={config.classes.vehicle_motorcycle} onChange={(e) => setClasses({ vehicle_motorcycle: Number(e.target.value) })} />
              </Field>

              {/* 运行时开关 */}
              <div className="md:col-span-2 flex flex-col gap-4">
                <SwitchRow id="debug" label="调试模式" description="输出更多调试信息" checked={config.runtime.debug} onChange={(checked) => setRuntime({ debug: checked })} />
                <SwitchRow id="draw_debug" label="叠加调试文字" description="关闭后不再在视频画面左上角绘制调试状态" checked={config.runtime.draw_debug} onChange={(checked) => setRuntime({ draw_debug: checked })} />
                <SwitchRow id="enable_vehicle_unattended" label="启用车辆后备箱检查" description="只在下方指定摄像头和车辆 ROI 内检测车辆无人值守报警" checked={config.runtime.enable_vehicle_unattended} onChange={(checked) => setRuntime({ enable_vehicle_unattended: checked })} />
                <Field label="最大报警历史">
                  <Input type="number" value={config.runtime.max_alarm_history} onChange={(e) => setRuntime({ max_alarm_history: Number(e.target.value) })} />
                </Field>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ==================== 报警推送 ==================== */}
        <TabsContent value="wechat" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="w-5 h-5 text-orange-600" />
                企业微信报警推送
              </CardTitle>
              <CardDescription>配置企业微信应用消息推送，报警时自动发送视频到指定用户</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <SwitchRow
                id="wechat_enable"
                label="启用企业微信推送"
                description="关闭后报警只在前端显示，不推送到企业微信"
                checked={config.wechat.enable}
                onChange={(checked) => setWechat({ enable: checked })}
              />

              {config.wechat.enable && (
                <div className="space-y-6 p-4 bg-orange-50 rounded-lg border border-orange-100">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <Field label="企业 ID（corpid）">
                      <Input
                        value={config.wechat.corpid}
                        onChange={(e) => setWechat({ corpid: e.target.value })}
                        placeholder="企业微信后台 → 我的企业 → 企业ID"
                      />
                    </Field>
                    <Field label="应用 Secret（corpsecret）">
                      <Input
                        type="password"
                        value={config.wechat.corpsecret}
                        onChange={(e) => setWechat({ corpsecret: e.target.value })}
                        placeholder="企业微信后台 → 应用管理 → Secret"
                      />
                    </Field>
                    <Field label="应用 AgentId">
                      <Input
                        type="number"
                        value={config.wechat.agentid}
                        onChange={(e) => setWechat({ agentid: Number(e.target.value) })}
                      />
                    </Field>
                    <Field label="接收报警的用户（alarm_user）">
                      <Input
                        value={config.wechat.alarm_user}
                        onChange={(e) => setWechat({ alarm_user: e.target.value })}
                        placeholder="多个用户用 | 分隔，如 zhangsan|lisi"
                      />
                    </Field>
                    <Field label="摄像头名称">
                      <Input
                        value={config.wechat.camera_name}
                        onChange={(e) => setWechat({ camera_name: e.target.value })}
                        placeholder="显示在报警消息中的摄像头名称"
                      />
                    </Field>
                    <Field label="报警录制时长（秒）">
                      <Input
                        type="number"
                        step="1"
                        value={config.wechat.clip_seconds}
                        onChange={(e) => setWechat({ clip_seconds: Number(e.target.value) })}
                      />
                    </Field>
                  </div>
                  <p className="text-xs text-orange-600">
                    企业微信视频消息限制：单个文件不超过 10MB。如果推送失败请缩短录制时长。修改后需重启算法生效。
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ==================== 通用子组件 ====================

type RuleTone = 'green' | 'blue' | 'purple' | 'amber'

const ruleToneStyles: Record<RuleTone, {
  panel: string
  icon: string
  iconWrap: string
  badge: string
  slider: string
}> = {
  green: {
    panel: 'border-emerald-100 bg-white shadow-[0_12px_28px_rgba(16,185,129,0.06)]',
    icon: 'text-emerald-700',
    iconWrap: 'bg-emerald-500 text-white shadow-emerald-500/20',
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    slider: '[&_[data-slot=slider-range]]:bg-emerald-500 [&_[data-slot=slider-thumb]]:border-emerald-500 [&_[data-slot=slider-thumb]]:ring-emerald-500/20',
  },
  blue: {
    panel: 'border-blue-100 bg-white shadow-[0_12px_28px_rgba(37,99,235,0.06)]',
    icon: 'text-blue-700',
    iconWrap: 'bg-blue-600 text-white shadow-blue-500/20',
    badge: 'border-blue-200 bg-blue-50 text-blue-700',
    slider: '[&_[data-slot=slider-range]]:bg-blue-600 [&_[data-slot=slider-thumb]]:border-blue-600 [&_[data-slot=slider-thumb]]:ring-blue-500/20',
  },
  purple: {
    panel: 'border-violet-100 bg-white shadow-[0_12px_28px_rgba(124,58,237,0.06)]',
    icon: 'text-violet-700',
    iconWrap: 'bg-violet-600 text-white shadow-violet-500/20',
    badge: 'border-violet-200 bg-violet-50 text-violet-700',
    slider: '[&_[data-slot=slider-range]]:bg-violet-600 [&_[data-slot=slider-thumb]]:border-violet-600 [&_[data-slot=slider-thumb]]:ring-violet-500/20',
  },
  amber: {
    panel: 'border-amber-100 bg-white shadow-[0_12px_28px_rgba(245,158,11,0.06)]',
    icon: 'text-amber-700',
    iconWrap: 'bg-amber-500 text-white shadow-amber-500/20',
    badge: 'border-amber-200 bg-amber-50 text-amber-700',
    slider: '[&_[data-slot=slider-range]]:bg-amber-500 [&_[data-slot=slider-thumb]]:border-amber-500 [&_[data-slot=slider-thumb]]:ring-amber-500/20',
  },
}

function RuleGroup({
  title,
  icon: Icon,
  tone,
  children,
}: {
  title: string
  icon: LucideIcon
  tone: RuleTone
  children: React.ReactNode
}) {
  const styles = ruleToneStyles[tone]
  return (
    <section className={cn('rounded-2xl border p-4 sm:p-5', styles.panel)}>
      <div className="mb-5 flex items-center gap-3">
        <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg shadow-sm', styles.iconWrap)}>
          <Icon className="h-4 w-4" />
        </span>
        <Label className={cn('text-base font-bold', styles.icon)}>{title}</Label>
      </div>
      <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">{children}</div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function SwitchRow({
  id,
  label,
  description,
  checked,
  onChange,
}: {
  id: string
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-transparent bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900">
      <div>
        <Label htmlFor={id} className="cursor-pointer">{label}</Label>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      <Switch id={id} checked={checked ?? false} onCheckedChange={onChange} />
    </div>
  )
}

function SliderRow({
  title,
  description,
  value,
  min,
  max,
  step,
  onChange,
  tone = 'blue',
}: {
  title: string
  description?: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
  tone?: RuleTone
}) {
  const safeValue = Number.isFinite(value) ? value : min
  const styles = ruleToneStyles[tone]
  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Label className="text-sm font-bold text-[#1a2e55] dark:text-slate-100">{title}</Label>
          {description && <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>}
        </div>
        <span className={cn('shrink-0 rounded-md border px-2.5 py-1 text-xs font-bold shadow-sm', styles.badge)}>{safeValue}</span>
      </div>
      <Slider
        value={[safeValue]}
        onValueChange={([next]) => onChange(next ?? min)}
        min={min}
        max={max}
        step={step}
        className={styles.slider}
      />
      <div className="flex justify-between text-[11px] font-medium text-slate-500">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  )
}

export { ConfigSection }
export default ConfigSection
