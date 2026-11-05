import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  BellRing,
  Camera,
  Clock3,
  Info,
  Settings2,
  Video,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { AlarmEvent } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { MonitorCameraToolbar } from '@/components/monitor/MonitorCameraToolbar'
import { AgvRequestStatusCard } from '@/components/agv_person_check/AgvRequestStatusCard'
import { CurrentDetectionCard } from '@/components/monitor/CurrentDetectionCard'
import { useDetectionStatus } from '@/components/monitor/useDetectionStatus'
import { cn } from '@/lib/utils'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import {
  FEATURE_DASHBOARD_PROFILES,
  type FeatureDashboardKey,
} from './monitorState'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

export function StatCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
  ping = false,
}: {
  label: string
  value: string
  detail: string
  icon: LucideIcon
  tone: 'emerald' | 'indigo' | 'amber' | 'rose' | 'slate'
  ping?: boolean
}) {
  const tones = {
    emerald: 'bg-emerald-50 text-emerald-600',
    indigo: 'bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300',
    amber: 'bg-amber-50 text-amber-600',
    rose: 'bg-rose-50 text-rose-600',
    slate: 'bg-slate-100 text-slate-500',
  }

  return (
    <article className={cn(CARD_CLASS, 'relative min-w-0 p-3 sm:p-4')}>
      <span className={cn('hidden h-9 w-9 items-center justify-center rounded-xl sm:flex', tones[tone])}>
        <Icon className="h-3.5 w-3.5 sm:h-[18px] sm:w-[18px]" />
      </span>
      {ping && (
        <span className="absolute right-4 top-4 flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
        </span>
      )}
      <p className="pr-3 text-xs font-medium text-slate-500 dark:text-slate-400 sm:mt-4 sm:pr-0">{label}</p>
      <p className="mt-1 break-words text-lg font-bold leading-snug text-slate-950 dark:text-slate-100 sm:text-[22px]">{value}</p>
      <p className="mt-1.5 break-words text-xs leading-5 text-slate-500 dark:text-slate-400" title={detail}>{detail}</p>
    </article>
  )
}

function formatBusinessMetric(feature: FeatureDashboardKey, value: Record<string, unknown> | null) {
  if (feature === 'agv_person_check') return formatValue(value?.sample_count, ' 帧')
  if (feature === 'blocks') {
    const side = Number(value?.alarm_side)
    return side === 1 ? '线左侧' : side === -1 ? '线右侧' : '--'
  }
  if (feature === 'detect_face') {
    const threshold = Number(value?.FACE_SCORE_THR)
    return Number.isFinite(threshold) ? threshold.toFixed(2) : '--'
  }
  if (feature === 'detect_phone') {
    const seconds = Number(value?.MIN_CONFIRM_SECONDS)
    return Number.isFinite(seconds) ? `${seconds} 秒` : '--'
  }
  const seconds = Number(value?.first_alarm)
  return Number.isFinite(seconds) ? `${seconds} 秒` : '--'
}

function formatValue(value: unknown, suffix = '') {
  if (typeof value === 'boolean') return value ? '已启用' : '未启用'
  if (value === null || value === undefined || value === '') return '--'
  if (Array.isArray(value)) return JSON.stringify(value)
  return `${String(value)}${suffix}`
}

function ruleRows(feature: FeatureDashboardKey, value: Record<string, unknown> | null) {
  if (feature === 'agv_person_check') {
    return [
      ['触发方式', '收到 HTTP 请求后检测，返回结果后停止'],
      ['判定规则', '任一帧有人即判有人，全部采样帧无人才能判无人'],
      ['人体置信度', formatValue(value?.confidence_threshold)],
      ['检测时长上限', formatValue(value?.request_timeout_seconds, ' 秒')],
    ]
  }
  if (feature === 'blocks') {
    return [
      ['监测区域', '红色警戒线（alarm_line）'],
      ['判定规则', `目标跨越警戒线进入${formatBusinessMetric(feature, value)}`],
      ['检测阈值', formatValue(value?.threshold)],
    ]
  }
  if (feature === 'detect_face') {
    return [
      ['监测区域', '青色区域（face_roi）'],
      ['置信阈值', formatValue(value?.FACE_SCORE_THR)],
      ['逗留时间（秒）', formatValue(value?.MAX_TIME)],
    ]
  }
  if (feature === 'detect_phone') {
    return [
      ['监测区域', '青色区域（phone_roi）'],
      ['手机置信度', formatValue(value?.CONF_THRESHOLD)],
      ['人体关联', formatValue(value?.REQUIRE_PERSON_ASSOCIATION)],
    ]
  }
  return [
    ['监测区域', '青色区域（door_roi）'],
    ['变化阈值', formatValue(value?.threshold)],
    ['首次告警', formatValue(value?.first_alarm, ' 秒')],
  ]
}

function formatClock(value: string | undefined) {
  if (!value) return '--'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '--' : parsed.toLocaleTimeString('zh-CN', { hour12: false })
}

function browserTimestamp() {
  const now = new Date()
  return `${now.getFullYear()}年${String(now.getMonth() + 1).padStart(2, '0')}月${String(now.getDate()).padStart(2, '0')}日 ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
}

export type FeatureDashboardMonitorViewProps = {
  feature: FeatureDashboardKey
  cameras: AiVisionCamera[]
  selectedCamera: string
  selectedCameraInfo?: AiVisionCamera
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  featureValue: Record<string, unknown> | null
  alarms: AlarmEvent[]
  todayAlarmCount: number
  onSelectCamera: (cameraKey: string) => void
  onRefreshCameras: () => void
}

export function FeatureDashboardMonitorView({
  feature,
  cameras,
  selectedCamera,
  selectedCameraInfo,
  loading,
  message,
  frameConnected,
  frameContent,
  featureValue,
  alarms,
  todayAlarmCount,
  onSelectCamera,
  onRefreshCameras,
}: FeatureDashboardMonitorViewProps) {
  const profile = FEATURE_DASHBOARD_PROFILES[feature]
  const cameraKey = selectedCameraInfo ? getAiVisionCameraKey(selectedCameraInfo) : selectedCamera
  const cameraName = selectedCameraInfo?.name || '未选择摄像头'
  const fps = selectedCameraInfo?.fps
  const rows = ruleRows(feature, featureValue)
  const result = useDetectionStatus(selectedCamera, feature, feature !== 'agv_person_check')

  return (
    <div className="space-y-5">
      <ResizableMonitorLayout id={`feature-dashboard-${feature}`} status={feature === 'agv_person_check' && <AgvRequestStatusCard key={`${selectedCameraInfo?.department}:${cameraKey}`} cameraKey={cameraKey} />} summary={
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="摄像头状态" value={frameConnected ? '在线' : '离线'} detail={frameConnected ? `${cameraKey || 'cam'} · 实时画面已连接` : '等待实时画面'} icon={Video} tone={frameConnected ? 'emerald' : 'rose'} ping={frameConnected} />
          <StatCard label="启用摄像头" value={`${cameras.length} 路`} detail={`已启用${profile.videoTitle}`} icon={Camera} tone="indigo" />
          <StatCard label={profile.metricLabel} value={formatBusinessMetric(feature, featureValue)} detail="读取当前摄像头现有配置" icon={Settings2} tone="amber" />
          <StatCard label={`今日${profile.eventLabel}`} value={`${todayAlarmCount} 次`} detail={todayAlarmCount ? `最近一次 ${formatClock(alarms[0]?.created_at)}` : '今日暂无报警'} icon={BellRing} tone={todayAlarmCount ? 'rose' : 'emerald'} />
        </section>
      }>
        <div className="space-y-5">
          {feature !== 'agv_person_check' && <CurrentDetectionCard feature={feature} status={result?.status} error={result?.error} />}
          <Card className={CARD_CLASS}>
            <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Info className="h-4 w-4" /></span>判定说明</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-4 pb-4 sm:px-5 sm:pb-5 text-sm">{rows.map(([label, value]) => <div key={label} className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">{label}</span><span className="break-words text-slate-700 dark:text-slate-300">{value}</span></div>)}</CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center justify-between text-base font-bold text-slate-950 dark:text-slate-100"><span>最近报警</span><Activity className="h-4 w-4 text-slate-300 dark:text-slate-600" /></CardTitle></CardHeader>
            <CardContent className="px-4 pb-4 sm:px-5 sm:pb-5">
              {alarms.length ? <div className="relative space-y-4 pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-slate-200">{alarms.map((alarm) => <div key={alarm.id} className="relative"><span className="absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-rose-500" /><p className="text-sm font-medium text-rose-600">{alarm.event_label || profile.eventLabel}</p><p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{alarm.reason || cameraName}</p><p className="mt-1 font-mono text-[11px] text-slate-400">{formatClock(alarm.created_at)}</p></div>)}</div> : <p className="text-sm text-slate-400">当前摄像头今日暂无报警</p>}
            </CardContent>
          </Card>
        </div>

        <Card className={cn(CARD_CLASS, 'gap-0 overflow-hidden py-0 lg:col-span-2')}>
          <CardHeader className="gap-0 border-b border-slate-100 p-3 [.border-b]:pb-3 dark:border-slate-800 sm:p-4 sm:px-5 sm:[.border-b]:pb-4">
            <div className="flex items-center justify-between gap-2 sm:flex-wrap sm:gap-3">
              <div className="flex min-w-0 items-center gap-3"><span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white dark:bg-blue-700 sm:flex"><Video className="h-5 w-5" /></span><div className="min-w-0"><CardTitle className="text-sm font-bold leading-5 text-slate-950 dark:text-slate-100 sm:text-base">{profile.videoTitle}</CardTitle><p className="mt-0.5 hidden truncate text-xs text-slate-400 sm:block">{cameraKey || 'cam'} · {cameraName}</p></div></div>
              <div className="flex shrink-0 items-center gap-2"><span className="hidden rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-500 sm:inline">FPS {fps?.toFixed(1) ?? '--'}</span><Badge className={cn('rounded-full border-0 px-2.5 py-1 shadow-none', frameConnected ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-500')}>{frameConnected && <span className="relative mr-1.5 flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-70" /><span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" /></span>}{frameConnected ? 'LIVE' : '离线'}</Badge></div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <MonitorCameraToolbar
              cameras={cameras}
              selectedCamera={selectedCamera}
              loading={loading}
              onSelectCamera={onSelectCamera}
              onRefreshCameras={onRefreshCameras}
            />
            <div className="relative overflow-hidden bg-slate-950">
              <div className="relative aspect-video w-full saturate-[.85]">{frameContent}</div>

              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-black/15" />
              <div className="pointer-events-none absolute bottom-3 left-3 font-mono text-[10px] font-semibold sm:left-4 sm:text-base text-white/95 [text-shadow:0_1px_4px_rgba(0,0,0,0.85)]"><Clock3 className="mr-1 inline h-3 w-3 sm:mr-1.5 sm:h-4 sm:w-4" />{browserTimestamp()}</div>
              <span className="pointer-events-none absolute bottom-3 right-3 rounded-full sm:right-4 bg-black/45 px-2 py-1 font-mono text-[10px] text-white backdrop-blur-sm">实时画面</span>
            </div>
            {message && <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-400 dark:border-slate-800">{message}</div>}
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}
