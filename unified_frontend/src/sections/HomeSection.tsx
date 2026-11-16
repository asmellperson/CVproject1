import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Activity,
  Bell,
  Camera,
  CircleDotDashed,
  Pencil,
  Plus,
  ScanFace,
  Server,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { OverviewMascot } from '@/components/OverviewMascot'
import { OfflineCamerasDialog } from '@/components/OfflineCamerasDialog'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { useAuth } from '@/auth/useAuth'
import { useDepartmentCatalog } from '@/hooks/use-department-catalog'
import {
  getAccessibleAlarmEventTypes,
  getAccessibleDepartments,
  getUserRole,
  canConfigureDepartment,
  hasPageAccess,
  isDepartment,
  type DepartmentId,
} from '@/auth/permissions'
import {
  getAlarms,
  type AlarmEvent,
  type OverviewServiceStatus,
  type OverviewCapability,
} from '@/lib/api'
import { getRecognitionAbilityText, getServiceStatusText } from './HomeSection.status'
import {
  createAiVisionCamera,
  deleteAiVisionCamera,
  getAiVisionCameraKey,
  getAiVisionExceptionAlertSettings,
  saveAiVisionExceptionAlertSettings,
  updateAiVisionCamera,
  type AiVisionCamera,
} from '@/lib/aivision'
import { detectionNavItems } from '@/lib/nav'
import type { OverviewState as OverviewRequest } from '@/hooks/use-overview'

interface HomeSectionProps {
  onNavigate: (page: string, department?: DepartmentId) => void
  overviewState: OverviewRequest
}

const moduleEntries = detectionNavItems.map((item) => ({ id: item.id, title: item.label }))

type OverviewState = {
  todayAlarms: number
  pendingAlarms: number
  recentAlarms: AlarmEvent[]
}

type AlarmSeverity = 'critical' | 'warning' | 'normal'

const defaultOverview: OverviewState = {
  todayAlarms: 0,
  pendingAlarms: 0,
  recentAlarms: [],
}

const criticalAlarmTypes = new Set(['blocks', 'guard_absent', 'tailgating', 'smoke_detection'])
const warningAlarmTypes = new Set([
  'detect_door',
  'detect_phone',
  'guard_phone_use',
  'guard_prone_sleep',
  'guard_vehicle_inspection_missing',
  'security_inspection',
])

function isToday(value?: string) {
  if (!value) return false
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false
  const now = new Date()
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
}

function formatLatestTime(value?: string) {
  if (!value) return '暂无'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无'
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getAlarmSeverity(eventType: string): AlarmSeverity {
  if (criticalAlarmTypes.has(eventType)) return 'critical'
  if (warningAlarmTypes.has(eventType)) return 'warning'
  return 'normal'
}

function getAlarmLocation(alarm: AlarmEvent) {
  return alarm.subject_name || '未知位置'
}

export function HomeSection({ onNavigate, overviewState }: HomeSectionProps) {
  const { user, isAdmin } = useAuth()
  const canManageCameras = isAdmin || (getUserRole(user) === 'department_admin' && getAccessibleDepartments(user).length > 0)
  const [alarmOverview, setAlarmOverview] = useState<{ user: typeof user; data: OverviewState } | null>(null)
  const overview = alarmOverview?.user === user ? alarmOverview.data : defaultOverview
  const [exceptionWechatEnabled, setExceptionWechatEnabled] = useState(false)
  const [exceptionWechatUser, setExceptionWechatUser] = useState('')
  const [exceptionRepeatIntervalMinutes, setExceptionRepeatIntervalMinutes] = useState(60)
  const [exceptionSettingsLoading, setExceptionSettingsLoading] = useState(false)
  const [exceptionSettingsSaving, setExceptionSettingsSaving] = useState(false)
  const [exceptionSettingsMessage, setExceptionSettingsMessage] = useState('')
  const [exceptionSettingsError, setExceptionSettingsError] = useState('')
  const [cameraDialogOpen, setCameraDialogOpen] = useState(false)
  const [cameraDialogMode, setCameraDialogMode] = useState<'create' | 'edit'>('create')
  const [cameraToEdit, setCameraToEdit] = useState<AiVisionCamera | null>(null)
  const [cameraDepartment, setCameraDepartment] = useState('')
  const [cameraName, setCameraName] = useState('')
  const [cameraUrl, setCameraUrl] = useState('')
  const [cameraFps, setCameraFps] = useState('5')
  const [cameraFormError, setCameraFormError] = useState('')
  const [cameraActionKey, setCameraActionKey] = useState('')
  const [cameraToDelete, setCameraToDelete] = useState<AiVisionCamera | null>(null)
  const [cameraDeleteError, setCameraDeleteError] = useState('')
  const {
    options: departmentOptions,
    labels: departmentLabels,
    loading: departmentsLoading,
    error: departmentsError,
    reload: reloadDepartments,
  } = useDepartmentCatalog(Boolean(user))
  const departmentsUnavailable = departmentsLoading || Boolean(departmentsError)
  const cameraDepartmentLabel = (name?: string | null) => name ? departmentLabels[name] || name : '未分配事业部'
  const overviewStatus = overviewState.data
  const platformCameras = overviewStatus?.cameras ?? []
  const accessibleAlarmEventTypes = useMemo(() => getAccessibleAlarmEventTypes(user), [user])
  const visibleStatusCards = overviewStatus?.capabilities ?? moduleEntries.filter((entry) => hasPageAccess(user, entry.id)).map((entry) => ({
    id: entry.id, name: entry.title,
    camera_count: 0, online_camera_count: 0, running: false, model_ready: false,
  }))
  const scopedStatusSummary = {
    capabilityTotal: visibleStatusCards.length,
    capabilityOnline: overviewStatus?.summary.capability_online ?? 0,
    capabilityRunning: overviewStatus?.summary.capability_running ?? 0,
    cameraTotal: overviewStatus?.summary.camera_total ?? 0,
  }
  const cameraInventorySummary = {
    cameraTotal: overviewStatus?.summary.camera_total ?? 0,
    cameraOnline: overviewStatus?.summary.camera_online ?? 0,
    cameraOffline: overviewStatus?.summary.camera_offline ?? 0,
  }
  const cameraStatusReady = overviewStatus !== null && !overviewState.error
  const scopedStatusLevel = overviewStatus?.level ?? 'down'

  useEffect(() => {
    if (!isAdmin) {
      return
    }

    setExceptionSettingsLoading(true)
    getAiVisionExceptionAlertSettings()
      .then((settings) => {
        setExceptionWechatEnabled(Boolean(settings.wechat_enable))
        setExceptionWechatUser(settings.wechat_user || '')
        setExceptionRepeatIntervalMinutes(settings.repeat_interval_minutes || 60)
      })
      .catch((error) => {
        setExceptionSettingsError(`读取全局异常推送配置失败：${error instanceof Error ? error.message : String(error)}`)
      })
      .finally(() => setExceptionSettingsLoading(false))
  }, [isAdmin])

  const handleSaveExceptionSettings = async () => {
    if (exceptionWechatEnabled && !exceptionWechatUser.trim()) {
      setExceptionSettingsError('启用全局异常推送时，接收人不能为空。')
      setExceptionSettingsMessage('')
      return
    }
    if (exceptionRepeatIntervalMinutes < 5 || exceptionRepeatIntervalMinutes > 1440) {
      setExceptionSettingsError('重复提醒间隔必须在 5 到 1440 分钟之间。')
      setExceptionSettingsMessage('')
      return
    }

    setExceptionSettingsSaving(true)
    setExceptionSettingsError('')
    setExceptionSettingsMessage('')
    try {
      const next = await saveAiVisionExceptionAlertSettings({
        wechat_enable: exceptionWechatEnabled,
        wechat_user: exceptionWechatUser.trim(),
        repeat_interval_minutes: exceptionRepeatIntervalMinutes,
      })
      setExceptionWechatEnabled(Boolean(next.wechat_enable))
      setExceptionWechatUser(next.wechat_user || '')
      setExceptionRepeatIntervalMinutes(next.repeat_interval_minutes || 60)
      setExceptionSettingsMessage('全局异常推送配置已保存。')
    } catch (error) {
      setExceptionSettingsError(`保存全局异常推送配置失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setExceptionSettingsSaving(false)
    }
  }

  const allowedCameraDepartments = overviewStatus?.departments ?? []

  useEffect(() => {
    setCameraDialogOpen(false)
    setCameraToEdit(null)
    setCameraToDelete(null)
  }, [user])

  const resetCameraForm = () => {
    setCameraName('')
    setCameraUrl('')
    setCameraFps('5')
    setCameraToEdit(null)
    setCameraFormError('')
  }

  const openCreateCameraDialog = () => {
    setCameraDialogMode('create')
    resetCameraForm()
    setCameraDepartment('')
    if (departmentsError) reloadDepartments()
    setCameraDialogOpen(true)
  }

  const handleCameraDepartmentChange = (nextDepartment: string) => {
    setCameraDepartment(nextDepartment)
    setCameraFormError('')
  }

  const openEditCameraDialog = (camera: AiVisionCamera) => {
    setCameraDialogMode('edit')
    setCameraToEdit(camera)
    setCameraName(camera.name)
    setCameraUrl(camera.url || '')
    setCameraFps(String(camera.fps ?? 5))
    setCameraFormError('')
    setCameraDialogOpen(true)
  }

  const handleSaveCamera = async () => {
    const scope = cameraDialogMode === 'edit' ? cameraToEdit?.department : cameraDepartment
    if (!canConfigureDepartment(user, scope)) return
    const name = cameraName.trim()
    const url = cameraUrl.trim()
    const fps = Number(cameraFps)
    if (!name || !url) {
      setCameraFormError('摄像头名称和 RTSP 地址都不能为空。')
      return
    }
    if (!Number.isInteger(fps) || fps < 1) {
      setCameraFormError('FPS 必须是大于等于 1 的整数。')
      return
    }

    if (cameraDialogMode === 'create' && (
      !isDepartment(cameraDepartment)
      || departmentsUnavailable
      || !allowedCameraDepartments.includes(cameraDepartment)
      || !departmentOptions.some((item) => item.value === cameraDepartment)
    )) {
      setCameraFormError(departmentsError || '请选择已有事业部，等待事业部列表加载完成。')
      return
    }

    const actionKey = cameraDialogMode === 'edit' && cameraToEdit
      ? getAiVisionCameraKey(cameraToEdit)
      : 'aivision:create'
    setCameraActionKey(actionKey)
    setCameraFormError('')
    try {
      if (cameraDialogMode === 'edit' && cameraToEdit) {
        await updateAiVisionCamera(getAiVisionCameraKey(cameraToEdit), { name, url, fps })
      } else if (isDepartment(cameraDepartment)) {
        await createAiVisionCamera({
          name,
          url,
          fps,
          enabled: true,
          department: cameraDepartment,
        })
      }
      overviewState.refresh()
      setCameraDialogOpen(false)
      resetCameraForm()
    } catch (error) {
      setCameraFormError(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraActionKey('')
    }
  }

  const handleDeleteCamera = async () => {
    if (!cameraToDelete || !canConfigureDepartment(user, cameraToDelete.department)) return

    const cameraKey = getAiVisionCameraKey(cameraToDelete)
    setCameraActionKey(cameraKey)
    setCameraDeleteError('')
    try {
      await deleteAiVisionCamera(cameraKey)
      overviewState.refresh()
      setCameraToDelete(null)
    } catch (error) {
      setCameraDeleteError(`删除失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraActionKey('')
    }
  }

  useEffect(() => {
    let cancelled = false

    async function loadOverview() {
      const alarms = await getAlarms(100, accessibleAlarmEventTypes)

      if (cancelled) return
      const allowedAlarmTypes = accessibleAlarmEventTypes ? new Set(accessibleAlarmEventTypes) : null
      const alarmItems = alarms.filter((alarm) => !allowedAlarmTypes || allowedAlarmTypes.has(alarm.event_type))

      setAlarmOverview({ user, data: {
        todayAlarms: alarmItems.filter((alarm) => isToday(alarm.created_at)).length,
        pendingAlarms: alarmItems.filter((alarm) => (alarm.disposition_status || 'pending') === 'pending').length,
        recentAlarms: alarmItems.slice(0, 5),
      } })
    }

    void loadOverview().catch(() => {
      if (!cancelled) {
        setAlarmOverview({ user, data: defaultOverview })
      }
    })

    const timer = window.setInterval(() => {
      void loadOverview().catch(() => {
        if (!cancelled) setAlarmOverview({ user, data: defaultOverview })
      })
    }, 10000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [accessibleAlarmEventTypes, user])

  return (
    <>
      <div className="relative -mx-3 -my-4 min-h-[calc(100dvh-64px)] overflow-hidden bg-[#f5f8fc] p-3 dark:bg-[#07111f] sm:-mx-4 sm:-my-5 sm:min-h-[calc(100vh-72px)] sm:p-4 lg:-mx-8 lg:-my-6 lg:p-8 2xl:-mx-10 2xl:p-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#f8fbff_0%,#eef4fb_48%,#f8fafc_100%)] dark:bg-[linear-gradient(180deg,#07111f_0%,#0b1626_48%,#07111f_100%)]" />
      <div aria-hidden className="pointer-events-none absolute inset-x-10 top-8 h-24 rounded-full bg-blue-200/20 blur-3xl dark:bg-blue-500/10" />

      <div className="relative z-[1] flex w-full min-w-0 flex-col gap-4 sm:gap-7">
        <section className="relative overflow-hidden rounded-[14px] border border-white/80 bg-slate-900 shadow-[0_22px_54px_rgba(15,44,92,0.16)] dark:border-slate-800 dark:shadow-[0_22px_54px_rgba(0,0,0,0.36)] sm:rounded-[18px]">
          <img src="/company-home-bg.jpg" alt="" className="absolute inset-0 h-full w-full object-cover object-center" />
          <div className="absolute inset-0 z-0 bg-[linear-gradient(90deg,rgba(232,242,255,0.96)_0%,rgba(222,236,255,0.78)_50%,rgba(218,235,255,0.16)_100%)] dark:bg-[linear-gradient(90deg,rgba(7,17,31,0.94)_0%,rgba(9,25,48,0.82)_45%,rgba(9,25,48,0.24)_100%)] sm:bg-[linear-gradient(90deg,rgba(232,242,255,0.94)_0%,rgba(222,236,255,0.66)_38%,rgba(218,235,255,0.08)_72%)] dark:sm:bg-[linear-gradient(90deg,rgba(7,17,31,0.92)_0%,rgba(9,25,48,0.72)_42%,rgba(9,25,48,0.16)_78%)]" />
          <div className="absolute inset-0 z-0 bg-[radial-gradient(circle_at_15%_20%,rgba(255,255,255,0.9),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.2),rgba(255,255,255,0))] dark:bg-[radial-gradient(circle_at_15%_20%,rgba(59,130,246,0.18),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.05),rgba(255,255,255,0))]" />
          <OverviewMascot />
          <div className="relative z-[3] flex min-h-[240px] items-center justify-center px-3 py-5 text-center sm:min-h-[280px] sm:px-10 sm:py-7 lg:px-14 2xl:min-h-[380px] 2xl:px-20 2xl:py-10">
            <div className="relative z-[3] flex -translate-y-3 flex-col items-center justify-center sm:-translate-y-4">
              <h2 className="whitespace-nowrap text-[clamp(1rem,4.5vw,3rem)] font-black tracking-[0] text-[#061d45] drop-shadow-[0_10px_22px_rgba(255,255,255,0.65)] dark:text-white dark:drop-shadow-[0_10px_22px_rgba(0,0,0,0.55)] 2xl:text-6xl">
                福达 AI 视觉安全监管平台
              </h2>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]">
            <div className="p-5 sm:p-6">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cyan-600 text-white shadow-sm">
                  <Activity className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">平台汇总</h3>
                  <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">平台总览每 30 秒刷新</p>
                </div>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <MiniStatusMetric label="能力在线" value={`${scopedStatusSummary.capabilityOnline}/${scopedStatusSummary.capabilityTotal}`} />
                <MiniStatusMetric label="正在检测" value={`${scopedStatusSummary.capabilityRunning}/${scopedStatusSummary.capabilityTotal}`} />
                <MiniStatusMetric label="摄像头在线" value={cameraStatusReady ? `${cameraInventorySummary.cameraOnline}/${cameraInventorySummary.cameraTotal}` : overviewState.error ? '加载失败' : '加载中'} />
                <OfflineCamerasDialog overviewState={overviewState}>
                  <button
                    type="button"
                    aria-label="查看离线摄像头"
                    disabled={!cameraStatusReady}
                    className="group rounded-2xl text-left outline-none transition-shadow enabled:hover:ring-2 enabled:hover:ring-blue-200 focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed dark:enabled:hover:ring-blue-800"
                  >
                    <MiniStatusMetric
                      label="摄像头离线"
                      value={cameraStatusReady ? cameraInventorySummary.cameraOffline : overviewState.error ? '加载失败' : '加载中'}
                      warn={cameraStatusReady && cameraInventorySummary.cameraOffline > 0}
                      actionable
                    />
                  </button>
                </OfflineCamerasDialog>
              </div>

              <div className="mt-5 flex h-[360px] flex-col overflow-hidden rounded-2xl border border-blue-100 bg-[#f8fbff] shadow-sm dark:border-slate-800 dark:bg-slate-950/30">
                <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-blue-100 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm font-black text-[#071d3d] dark:text-slate-100">
                      <Camera className="h-4 w-4 text-cyan-600" />
                      全部摄像头
                    </div>
                    <div className="mt-1 text-xs font-medium text-slate-500 dark:text-slate-400">
                      共 {platformCameras.length} 路；已汇总 AiVision、物流通道、保安行为和安检流程摄像头。

                    </div>
                  </div>
                  {canManageCameras ? (
                    <Button size="sm" className="gap-2" onClick={openCreateCameraDialog} disabled={Boolean(cameraActionKey)}>
                      <Plus className="h-4 w-4" />
                      新增摄像头
                    </Button>
                  ) : (
                    <Badge variant="outline" className="shrink-0 bg-white text-xs font-semibold text-slate-500 dark:bg-slate-900">
                      只读
                    </Badge>
                  )}
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto">
                  {overviewState.error ? <div role="alert" className="px-4 py-3 text-sm text-red-600 dark:text-red-400">{overviewState.error}</div> : null}
                  {overviewState.loading ? <div role="status" className="px-4 py-6 text-sm text-slate-500">正在加载摄像头清单…</div> : null}
                  {!overviewState.loading && !overviewState.error && platformCameras.length === 0 ? (
                    <div className="px-4 py-6 text-sm font-medium text-slate-500">暂无摄像头。</div>
                  ) : (
                    <div className="grid grid-cols-1 lg:grid-cols-2">
                      {platformCameras.map((camera) => (
                          <div
                            key={camera.key}
                            className="group relative border-b border-blue-100 bg-white px-4 py-3 outline-none transition-colors hover:bg-blue-50/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 dark:border-slate-800 dark:bg-slate-900/70 dark:hover:bg-slate-800/70 lg:border-r lg:even:border-r-0"
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-bold text-[#071d3d] dark:text-slate-100">{camera.name}</div>
                                <div className="mt-1 truncate text-xs font-medium text-slate-500">
                                  AiVision · {cameraDepartmentLabel(camera.department)} · {camera.identifier}
                                  {camera.online ? ' · 在线' : ' · 离线'}
                                </div>
                              </div>
                              {camera.aivision_camera && canConfigureDepartment(user, camera.aivision_camera.department) ? (
                                <div className="flex shrink-0 items-center gap-2 opacity-100 transition-opacity duration-200 [@media(hover:hover)]:pointer-events-none [@media(hover:hover)]:opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="gap-1.5"
                                    onClick={() => openEditCameraDialog(camera.aivision_camera!)}
                                    disabled={Boolean(cameraActionKey)}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                    修改
                                  </Button>
                                  <Button
                                    variant="destructive"
                                    size="sm"
                                    className="gap-1.5"
                                    onClick={() => {
                                      setCameraToDelete(camera.aivision_camera!)
                                      setCameraDeleteError('')
                                    }}
                                    disabled={Boolean(cameraActionKey)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                    删除
                                  </Button>
                                </div>
                              ) : camera.capabilities[0] ? (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="shrink-0 gap-1.5"
                                  onClick={() => onNavigate(camera.capabilities[0], camera.department)}
                                >
                                  <ArrowRight className="h-3.5 w-3.5" />
                                  配置
                                </Button>
                              ) : null}
                            </div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {camera.capabilities.length ? (
                                camera.capabilities.map((page) => (
                                  <button key={page} type="button" onClick={() => onNavigate(page, camera.department)}><Badge variant="outline" className="bg-emerald-50 text-[11px] font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
                                    {visibleStatusCards.find((capability) => capability.id === page)?.name || page}
                                  </Badge></button>
                                ))
                              ) : (
                                <span className="text-xs font-medium text-slate-400">暂未加入检测功能</span>
                              )}
                            </div>
                          </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className={cn(
            'relative flex flex-col overflow-hidden rounded-[18px] border bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]',
            overview.recentAlarms.length ? 'border-amber-100 dark:border-amber-900/50' : 'border-emerald-100 dark:border-emerald-900/50',
          )}>
            <div className="relative flex h-full flex-col p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">最近异常</h3>
                  <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">
                    {overview.recentAlarms.length ? '最近 5 条可见报警事件' : '当前可见范围内暂无异常'}
                  </p>
                </div>
                <div className={cn(
                  'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl shadow-sm',
                  overview.recentAlarms.length ? 'bg-amber-50 text-amber-600 ring-1 ring-amber-100 dark:bg-amber-950/50 dark:ring-amber-900/70' : 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100 dark:bg-emerald-950/50 dark:ring-emerald-900/70',
                )}>
                  <AlertTriangle className="h-5 w-5" />
                </div>
              </div>

              {overview.recentAlarms.length ? (
                <div className="relative mt-5 flex-1">
                  <div aria-hidden className="absolute left-[5px] bottom-2 top-2 w-px bg-slate-200 dark:bg-slate-700" />
                  <div className="space-y-0">
                    {overview.recentAlarms.map((alarm) => {
                      const severity = getAlarmSeverity(alarm.event_type)
                      return (
                        <div key={alarm.id} className="relative pb-4 pl-7 last:pb-0">
                          <span
                            aria-hidden
                            className={cn(
                              'absolute left-0 top-1 h-3 w-3 rounded-full border-2 border-white shadow-sm dark:border-slate-900',
                              severity === 'critical' && 'bg-red-500',
                              severity === 'warning' && 'bg-amber-400',
                              severity === 'normal' && 'bg-slate-400',
                            )}
                          />
                          <span className="sr-only">{severity === 'critical' ? '严重报警' : severity === 'warning' ? '中等报警' : '普通报警'}</span>
                          <div className="text-[11px] font-medium text-slate-400 dark:text-slate-500">{formatLatestTime(alarm.created_at)}</div>
                          <div className="mt-0.5 truncate text-sm font-black text-[#071d3d] dark:text-slate-100">{alarm.event_label || alarm.event_type}</div>
                          <div className="mt-0.5 truncate text-xs font-medium text-slate-500 dark:text-slate-400">{getAlarmLocation(alarm)}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ) : (
                <div className="mt-5 flex-1 rounded-2xl border border-emerald-100 bg-emerald-50/70 p-5 dark:border-emerald-900/50 dark:bg-emerald-950/20">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_0_6px_rgba(16,185,129,0.14)]" />
                    <div className="text-sm font-semibold leading-6 text-emerald-700 dark:text-emerald-300">
                      今日暂无异常记录，当前总览处于平稳状态。
                    </div>
                  </div>
                </div>
              )}

              <button
                type="button"
                onClick={() => onNavigate('alarms')}
                className="mt-5 flex w-full items-center justify-between border-t border-slate-200 pt-4 text-sm font-bold text-[#09265a] transition hover:text-blue-600 dark:border-slate-800 dark:text-blue-300 dark:hover:text-blue-200"
              >
                <span>查看全部报警</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92">
            <div className="p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_14px_26px_rgba(0,27,67,0.22)] dark:bg-blue-600">
                    <Server className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-xl font-black tracking-[0] text-[#071d3d] dark:text-slate-100">运行状态看板</h3>
                    <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">现场检测模块、摄像头和画面更新时间</p>
                  </div>
                </div>
                <StatusBadge level={scopedStatusLevel} />
              </div>

              {isAdmin ? (
                <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-950/40">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-amber-600 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
                      <Bell className="h-4 w-4" />
                    </div>
                    <div className="min-w-[220px] flex-1">
                      <div className="text-sm font-black text-[#071d3d] dark:text-slate-100">全局异常推送</div>
                      <div className="mt-0.5 truncate text-xs font-medium text-slate-500 dark:text-slate-400">
                        摄像头断流、功能异常、模型 Worker 退出和 API 未处理异常统一推送。
                      </div>
                    </div>
                    <Switch
                      aria-label="启用全局异常推送"
                      checked={exceptionWechatEnabled}
                      onCheckedChange={setExceptionWechatEnabled}
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving}
                    />
                    <Input
                      aria-label="推送群号"
                      className="min-w-[220px] flex-[1_1_280px] bg-white dark:bg-slate-900"
                      value={exceptionWechatUser}
                      onChange={(event) => setExceptionWechatUser(event.target.value)}
                      placeholder="推送群号，多个用 | 分隔；也可填 @all"
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving || !exceptionWechatEnabled}
                    />
                    <div className="flex min-w-[190px] items-center gap-2">
                      <Input
                        aria-label="异常重复提醒间隔（分钟）"
                        className="w-24 bg-white dark:bg-slate-900"
                        type="number"
                        min={5}
                        max={1440}
                        value={exceptionRepeatIntervalMinutes}
                        onChange={(event) => setExceptionRepeatIntervalMinutes(Number(event.target.value))}
                        disabled={exceptionSettingsLoading || exceptionSettingsSaving || !exceptionWechatEnabled}
                      />
                      <span className="whitespace-nowrap text-xs font-medium text-slate-500 dark:text-slate-400">分钟内不重复</span>
                    </div>
                    <Button
                      className="gap-2 bg-[#001b43] text-white hover:bg-[#082a5f] dark:bg-blue-600 dark:hover:bg-blue-500"
                      onClick={handleSaveExceptionSettings}
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving}
                    >
                      <Bell className="h-4 w-4" />
                      {exceptionSettingsSaving ? '保存中' : '保存'}
                    </Button>
                  </div>
                  {exceptionSettingsError ? <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{exceptionSettingsError}</div> : null}
                  {exceptionSettingsMessage ? <div className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">{exceptionSettingsMessage}</div> : null}
                </div>
              ) : null}

              <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {visibleStatusCards.map((card) => (
                  <ServiceStatusCard
                    key={card.id}
                    service={overviewStatus?.service}
                    capability={card}
                  />
                ))}
              </div>
            </div>
          </div>

          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white p-5 shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92 sm:p-6">
            <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-[linear-gradient(180deg,rgba(225,238,255,0.72),rgba(255,255,255,0))] dark:bg-[linear-gradient(180deg,rgba(37,99,235,0.16),rgba(15,23,42,0))]" />
            <div className="relative flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_14px_26px_rgba(0,27,67,0.22)] dark:bg-blue-600">
                    <ShieldCheck className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-xl font-black tracking-[0] text-[#071d3d] dark:text-slate-100">监管概况</h3>
                    <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">当前账号可查看的检测能力与现场异常概况</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="relative mt-6 grid gap-3 sm:grid-cols-2">
              <MetricTile
                title="模块覆盖"
                value={visibleStatusCards.length}
                detail={`每个事业部提供 ${visibleStatusCards.length} 个检测能力`}
                icon={<CircleDotDashed className="h-5 w-5" />}
                tone="blue"
              />
              <MetricTile
                title="接入摄像头"
                value={scopedStatusSummary.cameraTotal}
                detail="平台接入总摄像头数"
                icon={<ScanFace className="h-5 w-5" />}
                tone="cyan"
              />
              <MetricTile
                title="今日异常"
                value={overview.todayAlarms}
                detail="今日累计异常报警数"
                icon={<AlertTriangle className="h-5 w-5" />}
                tone={overview.todayAlarms > 0 ? 'amber' : 'green'}
              />
              <MetricTile
                title="待处理"
                value={overview.pendingAlarms}
                detail="尚未确认处置的报警"
                icon={<AlertTriangle className="h-5 w-5" />}
                tone={overview.pendingAlarms > 0 ? 'amber' : 'green'}
              />
            </div>
          </div>
        </section>

      </div>
      </div>

      <Dialog
        open={cameraDialogOpen}
        onOpenChange={(open) => {
          setCameraDialogOpen(open)
          if (!open && !cameraActionKey) resetCameraForm()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{cameraDialogMode === 'edit' ? '修改摄像头' : '新增摄像头'}</DialogTitle>
            <DialogDescription>
              {cameraDialogMode === 'edit' ? '修改全局摄像头信息，相关检测功能会继续引用该摄像头。' : '新增平台摄像头，保存后可在各检测功能中启用。'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {cameraDialogMode === 'create' ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor="overview-camera-department">所属事业部</Label>
                  <Select
                    value={cameraDepartment}
                    onValueChange={handleCameraDepartmentChange}
                    disabled={Boolean(cameraActionKey) || departmentsLoading}
                  >
                    <SelectTrigger id="overview-camera-department">
                      <SelectValue placeholder={departmentsLoading ? '加载事业部...' : '选择事业部'} />
                    </SelectTrigger>
                    <SelectContent>
                      {departmentOptions
                        .filter((item) => allowedCameraDepartments.includes(item.value))
                        .map((item) => (
                          <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            ) : null}
            <div className="space-y-2">
              <Label htmlFor="overview-camera-name">摄像头名称</Label>
              <Input
                id="overview-camera-name"
                value={cameraName}
                onChange={(event) => setCameraName(event.target.value)}
                placeholder="例如：物流通道3"
                disabled={Boolean(cameraActionKey)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="overview-camera-url">RTSP 流地址</Label>
              <Input
                id="overview-camera-url"
                value={cameraUrl}
                onChange={(event) => setCameraUrl(event.target.value)}
                placeholder="rtsp://user:password@host:554/stream"
                disabled={Boolean(cameraActionKey)}
              />
            </div>
              <div className="space-y-2">
                <Label htmlFor="overview-camera-fps">FPS</Label>
                <Input
                  id="overview-camera-fps"
                  type="number"
                  min="1"
                  step="1"
                  value={cameraFps}
                  onChange={(event) => setCameraFps(event.target.value)}
                  disabled={Boolean(cameraActionKey)}
                />
              </div>

            {(cameraFormError || (cameraDialogMode === 'create' && departmentsError)) ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{cameraFormError || departmentsError}</div> : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCameraDialogOpen(false)} disabled={Boolean(cameraActionKey)}>
              取消
            </Button>
            <Button
              className="gap-2"
              onClick={handleSaveCamera}
              disabled={Boolean(cameraActionKey) || (cameraDialogMode === 'create' && (departmentsUnavailable || !cameraDepartment))}
            >
              {cameraDialogMode === 'edit' ? <Pencil className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
              {cameraActionKey ? '保存中' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={Boolean(cameraToDelete)}
        onOpenChange={(open) => {
          if (!open && !cameraActionKey) {
            setCameraToDelete(null)
            setCameraDeleteError('')
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除摄像头</AlertDialogTitle>
            <AlertDialogDescription>
              删除后会从全局摄像头库移除 {cameraToDelete?.name || '该摄像头'}，并清理它在所有检测功能里的配置。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {cameraDeleteError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{cameraDeleteError}</div> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(cameraActionKey)}>取消</AlertDialogCancel>
            <Button variant="destructive" className="gap-2" onClick={handleDeleteCamera} disabled={Boolean(cameraActionKey)}>
              <Trash2 className="h-4 w-4" />
              {cameraActionKey ? '删除中' : '删除'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function MetricTile({
  title,
  value,
  detail,
  icon,
  tone,
}: {
  title: string
  value: number
  detail: string
  icon: ReactNode
  tone: 'blue' | 'cyan' | 'amber' | 'green'
}) {
  const toneClass = {
    blue: {
      shell: 'border-blue-100 bg-[linear-gradient(180deg,#eff6ff_0%,#ffffff_100%)] dark:border-blue-900/60 dark:bg-[linear-gradient(180deg,rgba(30,64,175,0.24)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-blue-600 text-white dark:bg-blue-500',
      value: 'text-blue-700 dark:text-blue-300',
    },
    cyan: {
      shell: 'border-cyan-100 bg-[linear-gradient(180deg,#ecfeff_0%,#ffffff_100%)] dark:border-cyan-900/60 dark:bg-[linear-gradient(180deg,rgba(14,116,144,0.22)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-cyan-600 text-white dark:bg-cyan-500',
      value: 'text-cyan-700 dark:text-cyan-300',
    },
    amber: {
      shell: 'border-amber-100 bg-[linear-gradient(180deg,#fffbeb_0%,#ffffff_100%)] dark:border-amber-900/60 dark:bg-[linear-gradient(180deg,rgba(180,83,9,0.22)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-amber-500 text-white dark:bg-amber-500',
      value: 'text-amber-700 dark:text-amber-300',
    },
    green: {
      shell: 'border-emerald-100 bg-[linear-gradient(180deg,#ecfdf5_0%,#ffffff_100%)] dark:border-emerald-900/60 dark:bg-[linear-gradient(180deg,rgba(6,95,70,0.22)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-emerald-500 text-white dark:bg-emerald-500',
      value: 'text-emerald-700 dark:text-emerald-300',
    },
  }[tone]

  return (
    <div className={cn('relative overflow-hidden rounded-2xl border p-4 shadow-[0_10px_24px_rgba(15,44,92,0.06)] dark:border-slate-800 dark:bg-slate-950/36', toneClass.shell)}>
      <div className="flex items-center justify-between gap-3">
        <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl shadow-sm', toneClass.icon)}>
          {icon}
        </div>
        <div className={cn('text-3xl font-black tracking-[0]', toneClass.value)}>{value}</div>
      </div>
      <div className="mt-4 text-sm font-bold text-[#071d3d] dark:text-slate-100">{title}</div>
      <div className="mt-1 text-xs font-medium leading-5 text-slate-500 dark:text-slate-400">{detail}</div>
    </div>
  )
}

function StatusBadge({ level }: { level: string }) {
  const label = level === 'healthy' ? '全部正常' : level === 'degraded' ? '部分异常' : '模块离线'
  const className =
    level === 'healthy'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : level === 'degraded'
        ? 'border-amber-200 bg-amber-50 text-amber-700'
        : 'border-red-200 bg-red-50 text-red-700'
  return <Badge className={cn('px-3 py-1.5 text-sm font-bold shadow-none hover:bg-current/0', className)}>{label}</Badge>
}

function ServiceStatusCard({ service, capability }: {
  service?: OverviewServiceStatus
  capability: OverviewCapability
}) {
  const online = Boolean(service?.online)
  const running = capability.running
  const hasError = Boolean(service?.error)
  const modelLoaded = capability.model_ready
  const cameraCount = capability.camera_count
  const onlineCameras = capability.online_camera_count
  const displayName = capability.name
  const featureKey = capability.id
  const statusText = getServiceStatusText({
    online,
    running,
    hasError,
    featureKey,
    cameraCount,
    modelLoaded,
    onlineCameraCount: onlineCameras,
  })

  return (
    <div className="w-full rounded-2xl border border-slate-200 bg-slate-50/70 p-4 text-left shadow-sm dark:border-slate-800 dark:bg-slate-950/30">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-black text-[#071d3d] dark:text-slate-100">{displayName}</div>
          <div className="mt-1 text-xs font-medium text-slate-500">
            {statusText}
          </div>
        </div>
        <span
          className={cn(
            'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
            online && running && !hasError ? 'bg-emerald-500' : online ? 'bg-amber-500' : 'bg-red-500',
          )}
        />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">摄像头</div>
          <div className="mt-1 font-black text-slate-900 dark:text-slate-100">{onlineCameras}/{cameraCount}</div>
        </div>
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">识别能力</div>
          <div className={cn('mt-1 font-black', modelLoaded ? 'text-emerald-600' : 'text-amber-600')}>
            {getRecognitionAbilityText({ modelLoaded, running })}
          </div>
        </div>
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">检测引擎</div>
          <div className="mt-1 font-black text-slate-900 dark:text-slate-100">
            {service?.running ? '已就绪' : '未就绪'}
          </div>
        </div>
      </div>
    </div>
  )
}

function MiniStatusMetric({
  label,
  value,
  warn,
  actionable,
}: {
  label: string
  value: string | number
  warn?: boolean
  actionable?: boolean
}) {
  return (
    <span className="block h-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/30">
      <span className="block text-xs font-medium text-slate-500">{label}</span>
      <span className={cn('mt-2 flex items-center justify-between gap-2 text-2xl font-black', warn ? 'text-amber-600' : 'text-[#071d3d] dark:text-slate-100')}>
        {value}
        {actionable && <ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0 text-slate-400 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-600 dark:group-hover:text-blue-400" />}
      </span>
    </span>
  )
}
