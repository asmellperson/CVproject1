import { CurrentDetectionCard } from '@/components/monitor/CurrentDetectionCard'
import type { DetectionStatus } from '@/components/monitor/useDetectionStatus'
import {
  Activity,
  AlertTriangle,
  BellRing,
  Clock3,
  Info,
  Timer,
  Users,
  Video,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { MonitorCameraToolbar } from '@/components/monitor/MonitorCameraToolbar'
import { cn } from '@/lib/utils'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import type { HumanDwellMonitorEvent } from './monitorState'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

function GlassPill({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 rounded-full bg-black/45 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-sm',
      danger && 'bg-rose-500/90',
    )}>
      {children}
    </span>
  )
}

function formatClock(value: string | null) {
  if (!value) return '--'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '--' : parsed.toLocaleTimeString('zh-CN', { hour12: false })
}

export type HumanDwellMonitorViewProps = {
  cameras: AiVisionCamera[]
  selectedCamera: string
  selectedCameraInfo?: AiVisionCamera
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  featureValue: Record<string, unknown> | null
  error?: string
  status: DetectionStatus | null
  events: HumanDwellMonitorEvent[]
  todayAlarmCount: number
  latestAlarmAt: string | null
  onSelectCamera: (cameraKey: string) => void
  onRefreshCameras: () => void
}

export function HumanDwellMonitorView({
  cameras,
  selectedCamera,
  selectedCameraInfo,
  loading,
  message,
  frameConnected,
  frameContent,
  featureValue,
  status,
  error,
  events,
  todayAlarmCount,
  latestAlarmAt,
  onSelectCamera,
  onRefreshCameras,
}: HumanDwellMonitorViewProps) {
  const count = status?.count ?? null
  const countText = count === null ? '--' : String(count)
  const alarm = Boolean(status?.alarm)
  const runtimeThreshold = status?.threshold_seconds ?? null
  const runtimeThresholdText = runtimeThreshold === null ? '--' : String(Math.round(runtimeThreshold))
  const configuredThreshold = Number(featureValue?.MAX_TIME ?? 10)
  const configuredThresholdText = Number.isFinite(configuredThreshold) ? Math.round(configuredThreshold) : 10
  const cameraKey = selectedCameraInfo ? getAiVisionCameraKey(selectedCameraInfo) : selectedCamera
  const cameraName = selectedCameraInfo?.name || '未选择摄像头'
  const fps = selectedCameraInfo?.fps
  const now = new Date()
  const timestamp = `${now.getFullYear()}年${String(now.getMonth() + 1).padStart(2, '0')}月${String(now.getDate()).padStart(2, '0')}日 ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`

  return (
    <div className="space-y-5">
      <ResizableMonitorLayout id="human-dwell" summary={
        <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="摄像头状态" value={frameConnected ? '在线' : '离线'} detail={frameConnected ? `${cameraKey || 'cam'} · 实时画面已连接` : '等待实时画面'} icon={Video} tone={frameConnected ? 'emerald' : 'rose'} ping={frameConnected} />
          <StatCard label="区域当前人数" value={`${countText} 人`} detail="蓝色区域内实时统计" icon={Users} tone={alarm ? 'rose' : count !== null && count > 0 ? 'indigo' : 'slate'} />
          <StatCard label="逗留阈值" value={runtimeThreshold === null ? '--' : `${runtimeThresholdText} 秒`} detail="超时自动触发告警" icon={Timer} tone="amber" />
          <StatCard label="今日逗留告警次数" value={`${todayAlarmCount} 次`} detail={todayAlarmCount ? `最近一次 ${formatClock(latestAlarmAt)}` : '今日暂无逗留告警'} icon={BellRing} tone={todayAlarmCount ? 'rose' : 'emerald'} />
        </section>
      }>
        <div className="space-y-5">
          <CurrentDetectionCard feature="detect_human" status={status} error={error} />
          <Card className={CARD_CLASS}>
            <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Info className="h-4 w-4" /></span>判定说明</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-4 pb-4 sm:px-5 sm:pb-5 text-sm">
              <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">监测区域</span><span className="text-slate-700">画面中的青色 ROI 边框</span></div>
              <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">判定规则</span><span className="text-slate-700">人员进入区域并停留超过 {configuredThresholdText} 秒</span></div>
              <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">告警方式</span><span className="text-slate-700">平台实时推送 + 报警记录入库</span></div>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center justify-between text-base font-bold text-slate-950 dark:text-slate-100"><span>实时事件</span><Activity className="h-4 w-4 text-slate-300 dark:text-slate-600" /></CardTitle></CardHeader>
            <CardContent className="px-4 pb-4 sm:px-5 sm:pb-5">
              {events.length ? <div className="relative space-y-4 pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-slate-200">{events.map((event) => <div key={event.id} className="relative"><span className={cn('absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white', event.tone === 'danger' ? 'bg-rose-500' : 'bg-slate-300')} /><p className={cn('text-sm font-medium', event.tone === 'danger' ? 'text-rose-600' : 'text-slate-600')}>{event.label}</p><p className="mt-1 font-mono text-[11px] text-slate-400">{formatClock(event.occurredAt)}</p></div>)}</div> : <p className="text-sm text-slate-400">等待区域逗留事件</p>}
            </CardContent>
          </Card>
        </div>

        <Card className={cn(CARD_CLASS, 'gap-0 overflow-hidden py-0 lg:col-span-2')}>
          <CardHeader className="min-w-0 grid-cols-[minmax(0,1fr)] gap-0 border-b border-slate-100 p-3 [.border-b]:pb-3 dark:border-slate-800 sm:p-4 sm:px-5 sm:[.border-b]:pb-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3"><span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white dark:bg-blue-700 sm:flex"><Video className="h-5 w-5" /></span><div className="min-w-0"><CardTitle className="text-sm font-bold leading-5 text-slate-950 dark:text-slate-100 sm:text-base">人员违规逗留检测监控</CardTitle><p className="mt-0.5 hidden truncate text-xs text-slate-400 sm:block">{cameraKey || 'cam'} · {cameraName}</p></div></div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={cn('rounded-full border-0 px-2.5 py-1 shadow-none', alarm ? 'bg-rose-50 text-rose-600' : count !== null && count > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500')}>区域 {countText} 人</Badge>
                <span className="hidden rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-500 sm:inline">FPS {fps?.toFixed(1) ?? '--'}</span>
                <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold', frameConnected ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-500')}>{frameConnected && <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-70" /><span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" /></span>}{frameConnected ? 'LIVE' : '离线'}</span>
              </div>
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

              {alarm && <div className="pointer-events-none absolute left-3 right-3 top-3 flex flex-wrap gap-2"><GlassPill danger><AlertTriangle className="h-3.5 w-3.5" />逗留超时告警</GlassPill></div>}
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-black/15" />
              <div className="pointer-events-none absolute bottom-3 left-3 font-mono text-[10px] font-semibold sm:left-4 sm:text-base text-white/95 [text-shadow:0_1px_4px_rgba(0,0,0,0.85)]"><Clock3 className="mr-1 inline h-3 w-3 sm:mr-1.5 sm:h-4 sm:w-4" />{timestamp}</div>
              <span className="pointer-events-none absolute bottom-3 right-3 rounded-full sm:right-4 bg-black/45 px-2 py-1 font-mono text-[10px] text-white backdrop-blur-sm">实时画面</span>
            </div>
            <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-400 dark:border-slate-800">{message}</div>
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}
