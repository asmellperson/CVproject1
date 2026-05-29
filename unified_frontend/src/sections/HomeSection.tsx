import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CircleDotDashed,
  DoorOpen,
  ScanFace,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  UserRound,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useAuth } from '@/auth/useAuth'
import { filterHomeModulesByPermission, getUserDepartment } from '@/lib/permissions'
import { getAlarms, getConfig, type AlarmEvent } from '@/lib/api'
import { getAiVisionCameras } from '@/lib/aivision'
import { getSecurityVlmHealth } from '@/lib/security-vlm'

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
  latestAlarm: AlarmEvent | null
}

const defaultOverview: OverviewState = {
  cameraCount: 0,
  todayAlarms: 0,
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

function countGuardCameras(config: Awaited<ReturnType<typeof getConfig>>) {
  return [config.video.source_cam1, config.video.source_cam2, config.video.source_cam3].filter((source) => source.trim()).length
}

export function HomeSection({ onNavigate }: HomeSectionProps) {
  const { user } = useAuth()
  const visibleModuleEntries = filterHomeModulesByPermission(user, moduleEntries)
  const [overview, setOverview] = useState<OverviewState>(defaultOverview)
  const department = getUserDepartment(user)

  useEffect(() => {
    let cancelled = false

    async function loadOverview() {
      const [aiVisionCameras, guardConfig, securityHealth, alarms] = await Promise.allSettled([
        getAiVisionCameras(),
        getConfig(),
        getSecurityVlmHealth(),
        getAlarms(100),
      ])

      if (cancelled) return

      const alarmItems = alarms.status === 'fulfilled' ? alarms.value : []
      const cameraCount =
        (aiVisionCameras.status === 'fulfilled' ? aiVisionCameras.value.length : 0) +
        (guardConfig.status === 'fulfilled' ? countGuardCameras(guardConfig.value) : 0) +
        (securityHealth.status === 'fulfilled' ? 1 : 0)

      setOverview({
        cameraCount,
        todayAlarms: alarmItems.filter((alarm) => isToday(alarm.created_at)).length,
        latestAlarm: alarmItems[0] || null,
      })
    }

    loadOverview().catch(() => {
      if (!cancelled) {
        setOverview(defaultOverview)
      }
    })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="relative -mx-3 -my-4 min-h-[calc(100dvh-64px)] overflow-hidden bg-[#f5f8fc] p-3 sm:-mx-4 sm:-my-5 sm:min-h-[calc(100vh-72px)] sm:p-4 lg:-mx-8 lg:-my-6 lg:p-8 2xl:-mx-10 2xl:p-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#f8fbff_0%,#eef4fb_48%,#f8fafc_100%)]" />
      <div aria-hidden className="pointer-events-none absolute inset-x-10 top-8 h-24 rounded-full bg-blue-200/20 blur-3xl" />

      <div className="relative z-[1] flex w-full min-w-0 flex-col gap-4 sm:gap-7">
        <section className="relative overflow-hidden rounded-[14px] border border-white/80 bg-slate-900 shadow-[0_22px_54px_rgba(15,44,92,0.16)] sm:rounded-[18px]">
          <img src="/company-home-bg.jpg" alt="" className="absolute inset-0 h-full w-full object-cover object-center" />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(232,242,255,0.96)_0%,rgba(222,236,255,0.78)_50%,rgba(218,235,255,0.16)_100%)] sm:bg-[linear-gradient(90deg,rgba(232,242,255,0.94)_0%,rgba(222,236,255,0.66)_38%,rgba(218,235,255,0.08)_72%)]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(255,255,255,0.9),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.2),rgba(255,255,255,0))]" />
          <div className="relative flex min-h-[320px] px-5 py-7 sm:min-h-[360px] sm:px-10 sm:py-9 lg:px-14">
            <div className="flex max-w-3xl flex-col justify-center">
              <Badge className="mb-4 w-fit border border-blue-200 bg-white/78 px-3 py-1 text-sm font-semibold text-[#09265a] shadow-none hover:bg-white/78">
                {departmentLabel(department)}
              </Badge>
              <h2 className="max-w-2xl text-3xl font-black tracking-[0] text-[#061d45] drop-shadow-[0_10px_22px_rgba(255,255,255,0.65)] sm:text-4xl md:text-5xl">
                福达 AI 视觉安全监管平台
              </h2>
              <p className="mt-4 max-w-2xl text-base font-medium leading-7 text-[#25456f] sm:text-lg">
                汇总安检流程、保安行为、区域异常、人员与手机检测结果，形成面向现场安全管理的统一监控总览。
              </p>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,420px)]">
          <div className="rounded-[14px] border border-white bg-white p-5 shadow-[0_14px_36px_rgba(25,53,93,0.08)] sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-xl font-bold tracking-[0] text-[#071d3d]">统一监管总览</h3>
                <p className="mt-1 text-sm text-slate-500">当前账号可查看的检测能力与现场异常概况</p>
              </div>
              <Badge className="border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-medium text-slate-600 shadow-none hover:bg-slate-50">
                {departmentLabel(department)}
              </Badge>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-500">模块覆盖</div>
                <div className="mt-2 text-2xl font-black text-[#071d3d]">{visibleModuleEntries.length}</div>
                <div className="mt-1 text-xs text-slate-500">按账号权限展示</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-500">接入摄像头</div>
                <div className="mt-2 text-2xl font-black text-[#071d3d]">{overview.cameraCount}</div>
                <div className="mt-1 text-xs text-slate-500">平台接入总摄像头数</div>
              </div>
              <div className="rounded-xl bg-slate-50 p-4">
                <div className="text-sm font-semibold text-slate-500">今日异常</div>
                <div className="mt-2 text-2xl font-black text-[#071d3d]">{overview.todayAlarms}</div>
                <div className="mt-1 text-xs text-slate-500">今日累计异常报警数</div>
              </div>
            </div>
          </div>

          <div className="rounded-[14px] border border-white bg-white p-5 shadow-[0_14px_36px_rgba(25,53,93,0.08)] sm:p-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-lg font-bold tracking-[0] text-[#071d3d]">最近异常</h3>
              <AlertTriangle className={cn('h-5 w-5', overview.latestAlarm ? 'text-amber-500' : 'text-slate-300')} />
            </div>
            {overview.latestAlarm ? (
              <div className="mt-4">
                <div className="text-base font-bold text-[#071d3d]">{overview.latestAlarm.event_label || overview.latestAlarm.event_type}</div>
                <div className="mt-1 text-sm text-slate-500">{overview.latestAlarm.camera_name || overview.latestAlarm.camera_no || '未知摄像头'}</div>
                <div className="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">{overview.latestAlarm.reason}</div>
                <div className="mt-4 text-xs font-semibold text-slate-400">{formatLatestTime(overview.latestAlarm.created_at)}</div>
              </div>
            ) : (
              <div className="mt-4 rounded-xl bg-emerald-50 p-4 text-sm font-medium leading-6 text-emerald-700">
                今日暂无异常记录，当前总览处于平稳状态。
              </div>
            )}
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-7">
          {visibleModuleEntries.map((entry) => {
            const Icon = entry.icon
            return (
              <article
                key={entry.title}
                className={cn(
                  'group relative min-h-[176px] overflow-hidden rounded-[14px] border border-white bg-white shadow-[0_16px_42px_rgba(25,53,93,0.10)] sm:min-h-[218px]',
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
                    className="mt-5 h-11 w-full justify-between rounded-xl bg-[#001b43] px-5 text-base font-semibold text-white shadow-[0_10px_20px_rgba(0,27,67,0.22)] hover:bg-[#082a5f] sm:mt-7 sm:h-12 sm:w-[210px] sm:px-8"
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
