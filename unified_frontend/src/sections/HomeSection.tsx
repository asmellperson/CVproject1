import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Activity,
  CircleDotDashed,
  DoorOpen,
  ScanFace,
  Server,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  UserRound,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useAuth } from '@/auth/useAuth'
import { filterHomeModulesByPermission, getAccessibleAlarmEventTypes, getUserDepartment } from '@/auth/permissions'
import { getAlarms, getPlatformStatus, type AlarmEvent, type PlatformServiceStatus, type PlatformStatus } from '@/lib/api'

interface HomeSectionProps {
  onNavigate: (page: string) => void
}

const moduleEntries = [
  {
    id: 'security-vlm',
    title: '安检流程规范检测入口',
    icon: ShieldAlert,
    status: '已接入',
    accent: 'from-cyan-500 to-blue-500',
    glow: 'shadow-cyan-500/16',
    iconColor: 'text-cyan-700',
    iconBg: 'from-cyan-50 to-blue-100',
  },
  {
    id: 'guard-behavior',
    title: '保安行为规范检测入口',
    icon: ShieldCheck,
    status: '已接入',
    accent: 'from-sky-500 to-blue-600',
    glow: 'shadow-blue-500/18',
    iconColor: 'text-blue-600',
    iconBg: 'from-blue-50 to-sky-100',
  },
  {
    id: 'intrusion-detection',
    title: '区域入侵检测入口',
    icon: UserRound,
    status: '已接入',
    accent: 'from-teal-400 to-emerald-500',
    glow: 'shadow-emerald-500/16',
    iconColor: 'text-teal-600',
    iconBg: 'from-teal-50 to-cyan-100',
  },
  {
    id: 'door-detection',
    title: '大门开关检测入口',
    icon: DoorOpen,
    status: '已接入',
    accent: 'from-indigo-500 to-blue-600',
    glow: 'shadow-indigo-500/16',
    iconColor: 'text-indigo-600',
    iconBg: 'from-indigo-50 to-blue-100',
  },
  {
    id: 'face-detection',
    title: '人脸检测入口',
    icon: ScanFace,
    status: '已接入',
    accent: 'from-violet-500 to-purple-600',
    glow: 'shadow-violet-500/16',
    iconColor: 'text-violet-600',
    iconBg: 'from-violet-50 to-purple-100',
  },
  {
    id: 'human-detection',
    title: '人员逗留检测入口',
    icon: CircleDotDashed,
    status: '已接入',
    accent: 'from-amber-400 to-orange-500',
    glow: 'shadow-orange-500/16',
    iconColor: 'text-orange-600',
    iconBg: 'from-orange-50 to-amber-100',
  },
  {
    id: 'phone-detection',
    title: '手机使用检测入口',
    icon: Smartphone,
    status: '已接入',
    accent: 'from-rose-500 to-red-500',
    glow: 'shadow-rose-500/16',
    iconColor: 'text-rose-600',
    iconBg: 'from-rose-50 to-red-100',
  },
  
]

type OverviewState = {
  cameraCount: number
  todayAlarms: number
  pendingAlarms: number
  latestAlarm: AlarmEvent | null
}

type ServiceKey = keyof PlatformStatus['services']

type ModuleStatusSource = {
  serviceKey: ServiceKey
  featureKey?: string
}

const moduleStatusSources: Record<string, ModuleStatusSource> = {
  'security-vlm': { serviceKey: 'security_vlm' },
  'guard-behavior': { serviceKey: 'guard_room' },
  'intrusion-detection': { serviceKey: 'aivision', featureKey: 'blocks' },
  'door-detection': { serviceKey: 'aivision', featureKey: 'detect_door' },
  'face-detection': { serviceKey: 'aivision', featureKey: 'detect_face' },
  'human-detection': { serviceKey: 'aivision', featureKey: 'detect_human' },
  'phone-detection': { serviceKey: 'aivision', featureKey: 'detect_phone' },
}

type ModuleStatusCard = (typeof moduleEntries)[number] & ModuleStatusSource

const defaultOverview: OverviewState = {
  cameraCount: 0,
  todayAlarms: 0,
  pendingAlarms: 0,
  latestAlarm: null,
}

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

function departmentLabel(department: ReturnType<typeof getUserDepartment>) {
  if (department === 'general_electric') return '通用电气视图'
  if (department === 'research_institute') return '研究院视图'
  if (department === 'all') return '全局视图'
  return '权限视图'
}

function getRunningConsumers(service?: PlatformServiceStatus) {
  return Array.isArray(service?.running_consumers) ? service.running_consumers.map(String) : []
}

function getFeatureStatus(service?: PlatformServiceStatus, featureKey?: string) {
  if (!featureKey) return undefined
  return service?.feature_status?.[featureKey]
}

function getCapabilityCameraCount(service?: PlatformServiceStatus, featureKey?: string) {
  const featureStatus = getFeatureStatus(service, featureKey)
  return Number(featureStatus?.camera_count ?? service?.camera_count ?? 0)
}

function getCapabilityOnlineCameraCount(service?: PlatformServiceStatus, featureKey?: string) {
  const featureStatus = getFeatureStatus(service, featureKey)
  return Number(featureStatus?.online_camera_count ?? service?.online_camera_count ?? 0)
}

function isCapabilityRunning(service?: PlatformServiceStatus, featureKey?: string) {
  if (!service?.online || !service.running) return false
  if (!featureKey) return true
  const featureStatus = getFeatureStatus(service, featureKey)
  if (featureStatus && Number(featureStatus.camera_count || 0) <= 0) return false
  const runningConsumers = getRunningConsumers(service)
  if (!runningConsumers.length) return true
  return runningConsumers.includes(featureKey)
}

function isCapabilityModelReady(service?: PlatformServiceStatus, featureKey?: string) {
  if (!featureKey) return Boolean(service?.model_status?.loaded)
  const featureStatus = getFeatureStatus(service, featureKey)
  if (featureStatus && Number(featureStatus.camera_count || 0) <= 0) return false
  const runningConsumers = getRunningConsumers(service)
  if (!runningConsumers.length) return Boolean(service?.model_status?.loaded || service?.running)
  return runningConsumers.includes(featureKey)
}

function getStatusLevelForCards(cards: ModuleStatusCard[], platformStatus: PlatformStatus | null) {
  if (!cards.length || !platformStatus) return 'down'
  const services = cards.map((card) => platformStatus.services[card.serviceKey])
  const onlineCount = services.filter((service) => service?.online).length
  const runningCount = cards.filter((card) => isCapabilityRunning(platformStatus.services[card.serviceKey], card.featureKey)).length
  if (onlineCount === cards.length && runningCount === cards.length) return 'healthy'
  if (onlineCount > 0) return 'degraded'
  return 'down'
}

function getVisibleStatusCards(visibleEntries: typeof moduleEntries): ModuleStatusCard[] {
  return visibleEntries.flatMap((entry) => {
    const source = moduleStatusSources[entry.id]
    return source ? [{ ...entry, ...source }] : []
  })
}

function getScopedStatusSummary(cards: ModuleStatusCard[], platformStatus: PlatformStatus | null) {
  if (!platformStatus) {
    return {
      capabilityTotal: cards.length,
      capabilityOnline: 0,
      capabilityRunning: 0,
      cameraTotal: 0,
      cameraOnline: 0,
      cameraOffline: 0,
    }
  }

  const serviceCards = cards.filter((card) => !card.featureKey)
  const featureCards = cards.filter((card) => card.featureKey)
  const uniqueServices = Array.from(new Set(serviceCards.map((card) => card.serviceKey)))
  const serviceCameraTotal = uniqueServices.reduce((total, serviceKey) => {
    return total + Number(platformStatus.services[serviceKey]?.camera_count || 0)
  }, 0)
  const serviceCameraOnline = uniqueServices.reduce((total, serviceKey) => {
    return total + Number(platformStatus.services[serviceKey]?.online_camera_count || 0)
  }, 0)
  const featureCameraTotal = featureCards.reduce((total, card) => {
    return total + getCapabilityCameraCount(platformStatus.services[card.serviceKey], card.featureKey)
  }, 0)
  const featureCameraOnline = featureCards.reduce((total, card) => {
    return total + getCapabilityOnlineCameraCount(platformStatus.services[card.serviceKey], card.featureKey)
  }, 0)
  const cameraTotal = serviceCameraTotal + featureCameraTotal
  const cameraOnline = serviceCameraOnline + featureCameraOnline

  return {
    capabilityTotal: cards.length,
    capabilityOnline: cards.filter((card) => platformStatus.services[card.serviceKey]?.online).length,
    capabilityRunning: cards.filter((card) => isCapabilityRunning(platformStatus.services[card.serviceKey], card.featureKey)).length,
    cameraTotal,
    cameraOnline,
    cameraOffline: Math.max(0, cameraTotal - cameraOnline),
  }
}

export function HomeSection({ onNavigate }: HomeSectionProps) {
  const { user } = useAuth()
  const visibleModuleEntries = useMemo(() => filterHomeModulesByPermission(user, moduleEntries), [user])
  const visibleStatusCards = useMemo(() => getVisibleStatusCards(visibleModuleEntries), [visibleModuleEntries])
  const [overview, setOverview] = useState<OverviewState>(defaultOverview)
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)
  const department = getUserDepartment(user)
  const accessibleAlarmEventTypes = useMemo(() => getAccessibleAlarmEventTypes(user), [user])
  const scopedStatusSummary = useMemo(() => getScopedStatusSummary(visibleStatusCards, platformStatus), [platformStatus, visibleStatusCards])
  const scopedStatusLevel = useMemo(() => getStatusLevelForCards(visibleStatusCards, platformStatus), [platformStatus, visibleStatusCards])

  useEffect(() => {
    let cancelled = false

    async function loadOverview() {
      const [status, alarms] = await Promise.allSettled([
        getPlatformStatus(),
        getAlarms(100),
      ])

      if (cancelled) return
      const currentStatus = status.status === 'fulfilled' ? status.value : null
      setPlatformStatus(currentStatus)

      const allowedAlarmTypes = accessibleAlarmEventTypes ? new Set(accessibleAlarmEventTypes) : null
      const alarmItems = alarms.status === 'fulfilled'
        ? alarms.value.filter((alarm) => !allowedAlarmTypes || allowedAlarmTypes.has(alarm.event_type))
        : []

      setOverview({
        cameraCount: getScopedStatusSummary(getVisibleStatusCards(visibleModuleEntries), currentStatus).cameraTotal,
        todayAlarms: alarmItems.filter((alarm) => isToday(alarm.created_at)).length,
        pendingAlarms: alarmItems.filter((alarm) => (alarm.disposition_status || 'pending') === 'pending').length,
        latestAlarm: alarmItems[0] || null,
      })
    }

    loadOverview().catch(() => {
      if (!cancelled) {
        setPlatformStatus(null)
        setOverview(defaultOverview)
      }
    })

    const timer = window.setInterval(() => {
      loadOverview().catch(() => {
        if (!cancelled) setPlatformStatus(null)
      })
    }, 10000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [accessibleAlarmEventTypes, visibleModuleEntries])

  return (
    <div className="relative -mx-3 -my-4 min-h-[calc(100dvh-64px)] overflow-hidden bg-[#f5f8fc] p-3 dark:bg-[#07111f] sm:-mx-4 sm:-my-5 sm:min-h-[calc(100vh-72px)] sm:p-4 lg:-mx-8 lg:-my-6 lg:p-8 2xl:-mx-10 2xl:p-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#f8fbff_0%,#eef4fb_48%,#f8fafc_100%)] dark:bg-[linear-gradient(180deg,#07111f_0%,#0b1626_48%,#07111f_100%)]" />
      <div aria-hidden className="pointer-events-none absolute inset-x-10 top-8 h-24 rounded-full bg-blue-200/20 blur-3xl dark:bg-blue-500/10" />

      <div className="relative z-[1] flex w-full min-w-0 flex-col gap-4 sm:gap-7">
        <section className="relative overflow-hidden rounded-[14px] border border-white/80 bg-slate-900 shadow-[0_22px_54px_rgba(15,44,92,0.16)] dark:border-slate-800 dark:shadow-[0_22px_54px_rgba(0,0,0,0.36)] sm:rounded-[18px]">
          <img src="/company-home-bg.jpg" alt="" className="absolute inset-0 h-full w-full object-cover object-center" />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(232,242,255,0.96)_0%,rgba(222,236,255,0.78)_50%,rgba(218,235,255,0.16)_100%)] dark:bg-[linear-gradient(90deg,rgba(7,17,31,0.94)_0%,rgba(9,25,48,0.82)_45%,rgba(9,25,48,0.24)_100%)] sm:bg-[linear-gradient(90deg,rgba(232,242,255,0.94)_0%,rgba(222,236,255,0.66)_38%,rgba(218,235,255,0.08)_72%)] dark:sm:bg-[linear-gradient(90deg,rgba(7,17,31,0.92)_0%,rgba(9,25,48,0.72)_42%,rgba(9,25,48,0.16)_78%)]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(255,255,255,0.9),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.2),rgba(255,255,255,0))] dark:bg-[radial-gradient(circle_at_15%_20%,rgba(59,130,246,0.18),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.05),rgba(255,255,255,0))]" />
          <div className="relative flex min-h-[240px] px-5 py-5 sm:min-h-[280px] sm:px-10 sm:py-7 lg:px-14">
            <div className="flex max-w-3xl flex-col justify-center">
              <Badge className="mb-4 w-fit border border-blue-200 bg-white/78 px-3 py-1 text-sm font-semibold text-[#09265a] shadow-none hover:bg-white/78 dark:border-blue-900/70 dark:bg-slate-950/70 dark:text-blue-100 dark:hover:bg-slate-950/70">
                {departmentLabel(department)}
              </Badge>
              <h2 className="max-w-2xl text-3xl font-black tracking-[0] text-[#061d45] drop-shadow-[0_10px_22px_rgba(255,255,255,0.65)] dark:text-white dark:drop-shadow-[0_10px_22px_rgba(0,0,0,0.55)] sm:text-4xl md:text-5xl">
                福达 AI 视觉安全监管平台
              </h2>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]">
            <div className="h-1.5 bg-gradient-to-r from-[#001b43] via-blue-500 to-cyan-400" />
            <div className="relative p-5 sm:p-6">
              <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-[linear-gradient(180deg,rgba(225,238,255,0.72),rgba(255,255,255,0))] dark:bg-[linear-gradient(180deg,rgba(37,99,235,0.16),rgba(15,23,42,0))]" />
              <div className="relative flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_14px_26px_rgba(0,27,67,0.22)] dark:bg-blue-600">
                      <ShieldCheck className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="text-xl font-black tracking-[0] text-[#071d3d] dark:text-slate-100">统一监管总览</h3>
                      <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">当前账号可查看的检测能力与现场异常概况</p>
                    </div>
                  </div>
                </div>
                <Badge className="border border-blue-100 bg-blue-50 px-3 py-1.5 text-sm font-bold text-[#09265a] shadow-none hover:bg-blue-50 dark:border-blue-900/70 dark:bg-blue-950/50 dark:text-blue-100 dark:hover:bg-blue-950/50">
                  {departmentLabel(department)}
                </Badge>
              </div>

              <div className="relative mt-6 grid gap-3 sm:grid-cols-4">
                <MetricTile
                  title="模块覆盖"
                  value={visibleModuleEntries.length}
                  detail="按账号权限展示"
                  icon={<CircleDotDashed className="h-5 w-5" />}
                  tone="blue"
                />
                <MetricTile
                  title="接入摄像头"
                  value={overview.cameraCount}
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
          </div>

          <div className={cn(
            'relative overflow-hidden rounded-[18px] border bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]',
            overview.latestAlarm ? 'border-amber-100 dark:border-amber-900/50' : 'border-emerald-100 dark:border-emerald-900/50',
          )}>
            <div className={cn('h-1.5', overview.latestAlarm ? 'bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500' : 'bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500')} />
            <div className="relative p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">最近异常</h3>
                  <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">
                    {overview.latestAlarm ? '最新一条可见报警事件' : '当前可见范围内暂无异常'}
                  </p>
                </div>
                <div className={cn(
                  'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl shadow-sm',
                  overview.latestAlarm ? 'bg-amber-50 text-amber-600 ring-1 ring-amber-100 dark:bg-amber-950/50 dark:ring-amber-900/70' : 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100 dark:bg-emerald-950/50 dark:ring-emerald-900/70',
                )}>
                  <AlertTriangle className="h-5 w-5" />
                </div>
              </div>

              {overview.latestAlarm ? (
                <div className="mt-5 rounded-2xl border border-amber-100 bg-[linear-gradient(180deg,#fffaf0_0%,#ffffff_100%)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] dark:border-amber-900/50 dark:bg-[linear-gradient(180deg,rgba(69,42,15,0.32)_0%,rgba(15,23,42,0.22)_100%)]">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-base font-black text-[#071d3d] dark:text-slate-100">{overview.latestAlarm.event_label || overview.latestAlarm.event_type}</div>
                      <div className="mt-1 truncate text-sm font-semibold text-slate-500 dark:text-slate-400">{overview.latestAlarm.camera_name || overview.latestAlarm.camera_no || '未知摄像头'}</div>
                    </div>
                    <Badge className="shrink-0 border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-700 shadow-none hover:bg-amber-50">
                      {formatLatestTime(overview.latestAlarm.created_at)}
                    </Badge>
                  </div>
                  <div className="mt-4 rounded-xl border border-white/80 bg-white/78 p-3 text-sm font-medium leading-6 text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-950/42 dark:text-slate-300">
                    <p className="line-clamp-3">{overview.latestAlarm.reason}</p>
                  </div>
                </div>
              ) : (
                <div className="mt-5 rounded-2xl border border-emerald-100 bg-[linear-gradient(180deg,#ecfdf5_0%,#ffffff_100%)] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.86)] dark:border-emerald-900/50 dark:bg-[linear-gradient(180deg,rgba(6,78,59,0.25)_0%,rgba(15,23,42,0.18)_100%)]">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_0_6px_rgba(16,185,129,0.14)]" />
                    <div className="text-sm font-semibold leading-6 text-emerald-700 dark:text-emerald-300">
                      今日暂无异常记录，当前总览处于平稳状态。
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92">
            <div className={cn(
              'h-1.5',
              platformStatus?.level === 'healthy'
                ? 'bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500'
                : platformStatus?.level === 'degraded'
                  ? 'bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500'
                  : 'bg-gradient-to-r from-red-600 via-rose-500 to-orange-500',
            )} />
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

              <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {visibleStatusCards.map((card) => (
                  <ServiceStatusCard
                    key={card.id}
                    service={platformStatus?.services[card.serviceKey]}
                    displayName={card.title}
                    featureKey={card.featureKey}
                  />
                ))}
              </div>
            </div>
          </div>

          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white p-5 shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92 sm:p-6">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cyan-600 text-white shadow-sm">
                <Activity className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">平台汇总</h3>
                <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">每 10 秒自动刷新</p>
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <MiniStatusMetric label="能力在线" value={`${scopedStatusSummary.capabilityOnline}/${scopedStatusSummary.capabilityTotal}`} />
              <MiniStatusMetric label="正在检测" value={`${scopedStatusSummary.capabilityRunning}/${scopedStatusSummary.capabilityTotal}`} />
              <MiniStatusMetric label="摄像头在线" value={`${scopedStatusSummary.cameraOnline}/${scopedStatusSummary.cameraTotal}`} />
              <MiniStatusMetric label="摄像头离线" value={scopedStatusSummary.cameraOffline} warn={scopedStatusSummary.cameraOffline > 0} />
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-7">
          {visibleModuleEntries.map((entry) => {
            const Icon = entry.icon
            return (
              <article
                key={entry.title}
                className={cn(
                  'group relative min-h-[176px] overflow-hidden rounded-[14px] border border-white bg-white shadow-[0_16px_42px_rgba(25,53,93,0.10)] dark:border-slate-800 dark:bg-slate-900/92 dark:shadow-[0_16px_42px_rgba(0,0,0,0.30)] sm:min-h-[218px]',
                  'transition duration-200 hover:-translate-y-1 hover:shadow-[0_24px_58px_rgba(25,53,93,0.16)]',
                  entry.glow,
                )}
              >
                <div className={`h-1.5 bg-gradient-to-r ${entry.accent}`} />
                <div className="absolute -right-10 bottom-2 opacity-[0.055] transition duration-200 group-hover:scale-105 group-hover:opacity-[0.08] sm:-right-12">
                  <Icon className="h-32 w-32 text-slate-900 sm:h-40 sm:w-40" strokeWidth={1.4} />
                </div>
                <div className="relative flex h-full flex-col justify-between p-5 sm:p-7">
                  <div className="flex items-start gap-4 sm:gap-5">
                    <div className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${entry.iconBg} shadow-[0_10px_26px_rgba(30,78,141,0.12)] ring-1 ring-white sm:h-[74px] sm:w-[74px]`}>
                      <Icon className={`h-7 w-7 sm:h-9 sm:w-9 ${entry.iconColor}`} strokeWidth={1.8} />
                    </div>
                    <div className="min-w-0 pt-1 sm:pt-3">
                      <h3 className="text-lg font-bold tracking-[0] text-[#071d3d] sm:text-[22px]">{entry.title}</h3>
                      <Badge className="mt-3 border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-600 shadow-none hover:bg-emerald-50">
                        {entry.status}
                      </Badge>
                    </div>
                  </div>
                  <Button
                    className="mt-5 h-11 w-full justify-between rounded-xl bg-[#001b43] px-5 text-base font-semibold text-white shadow-[0_10px_20px_rgba(0,27,67,0.22)] hover:bg-[#082a5f] dark:bg-blue-600 dark:hover:bg-blue-500 sm:mt-7 sm:h-12 sm:w-[210px] sm:px-8"
                    onClick={() => onNavigate(entry.id)}
                  >
                    进入功能
                    <ArrowRight className="h-5 w-5" />
                  </Button>
                </div>
              </article>
            )
          })}
        </section>
      </div>
    </div>
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
      shell: 'border-blue-100 bg-[linear-gradient(180deg,#eff6ff_0%,#ffffff_100%)]',
      icon: 'bg-blue-600 text-white',
      value: 'text-blue-700',
    },
    cyan: {
      shell: 'border-cyan-100 bg-[linear-gradient(180deg,#ecfeff_0%,#ffffff_100%)]',
      icon: 'bg-cyan-600 text-white',
      value: 'text-cyan-700',
    },
    amber: {
      shell: 'border-amber-100 bg-[linear-gradient(180deg,#fffbeb_0%,#ffffff_100%)]',
      icon: 'bg-amber-500 text-white',
      value: 'text-amber-700',
    },
    green: {
      shell: 'border-emerald-100 bg-[linear-gradient(180deg,#ecfdf5_0%,#ffffff_100%)]',
      icon: 'bg-emerald-500 text-white',
      value: 'text-emerald-700',
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

function ServiceStatusCard({
  service,
  displayName,
  featureKey,
}: {
  service?: PlatformServiceStatus
  displayName: string
  featureKey?: string
}) {
  const online = Boolean(service?.online)
  const running = isCapabilityRunning(service, featureKey)
  const modelLoaded = isCapabilityModelReady(service, featureKey)
  const cameraCount = getCapabilityCameraCount(service, featureKey)
  const onlineCameras = getCapabilityOnlineCameraCount(service, featureKey)
  const frameAge = service?.last_frame_age_sec

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/30">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-black text-[#071d3d] dark:text-slate-100">{displayName}</div>
          <div className="mt-1 text-xs font-medium text-slate-500">
            {online ? (running ? '正常检测中' : featureKey && cameraCount <= 0 ? '未配置检测摄像头' : featureKey ? '服务在线，能力未启动' : '已连接，未开始检测') : '暂时不可用'}
          </div>
        </div>
        <span
          className={cn(
            'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
            online && running ? 'bg-emerald-500' : online ? 'bg-amber-500' : 'bg-red-500',
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
            {modelLoaded ? (featureKey ? '已启用' : '已就绪') : '待确认'}
          </div>
        </div>
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">画面更新</div>
          <div className={cn('mt-1 font-black', frameAge && frameAge > 10 ? 'text-amber-600' : 'text-slate-900 dark:text-slate-100')}>
            {typeof frameAge === 'number' ? `${frameAge}s` : '-'}
          </div>
        </div>
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">连接响应</div>
          <div className="mt-1 font-black text-slate-900 dark:text-slate-100">
            {typeof service?.latency_ms === 'number' ? `${service.latency_ms}ms` : '-'}
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
}: {
  label: string
  value: string | number
  warn?: boolean
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/30">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={cn('mt-2 text-2xl font-black', warn ? 'text-amber-600' : 'text-[#071d3d] dark:text-slate-100')}>
        {value}
      </div>
    </div>
  )
}
