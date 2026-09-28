import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  AlertTriangle,
  BellRing,
  Camera,
  Info,
  RefreshCw,
  Users,
  Video,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { getAiVisionCameraKey, type AiVisionCamera, type AiVisionLogisticsSinglePersonStatus } from '@/lib/aivision'
import { classifyLogisticsCount, type LogisticsMonitorEvent } from './monitorState'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

function StatCard({
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
    <article className={cn(CARD_CLASS, 'relative p-4')}>
      <span className={cn('flex h-9 w-9 items-center justify-center rounded-xl', tones[tone])}>
        <Icon className="h-[18px] w-[18px]" />
      </span>
      {ping && (
        <span className="absolute right-4 top-4 flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
        </span>
      )}
      <p className="mt-4 text-xs font-medium text-slate-400">{label}</p>
      <p className="mt-1 text-[22px] font-bold leading-tight text-slate-950 dark:text-slate-100">{value}</p>
      <p className="mt-1.5 truncate text-xs text-slate-400" title={detail}>{detail}</p>
    </article>
  )
}

function GlassPill({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 rounded-full bg-black/45 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-sm',
      danger && 'bg-rose-500/90 text-white',
    )}>
      {children}
    </span>
  )
}

export type LogisticsSinglePersonMonitorViewProps = {
  title: string
  cameras: AiVisionCamera[]
  selectedCamera: string
  selectedCameraInfo?: AiVisionCamera
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  featureValue: Record<string, unknown> | null
  status: AiVisionLogisticsSinglePersonStatus | null
  events: LogisticsMonitorEvent[]
  todayAlarmCount: number
  onSelectCamera: (cameraKey: string) => void
  onRefreshCameras: () => void
}

export function LogisticsSinglePersonMonitorView({
  title,
  cameras,
  selectedCamera,
  selectedCameraInfo,
  loading,
  message,
  frameConnected,
  frameContent,
  featureValue,
  status,
  events,
  todayAlarmCount,
  onSelectCamera,
  onRefreshCameras,
}: LogisticsSinglePersonMonitorViewProps) {
  const count = status?.count ?? null
  const countState = classifyLogisticsCount(count)
  const abnormal = countState === 'empty' || countState === 'multiple'
  const countText = count === null ? '--' : String(count)
  const cameraKey = selectedCameraInfo ? getAiVisionCameraKey(selectedCameraInfo) : selectedCamera
  const cameraName = selectedCameraInfo?.name || '未选择摄像头'
  const fps = selectedCameraInfo?.fps
  const emptyGrace = Number(featureValue?.empty_grace_seconds ?? 2)
  const multiGrace = Number(featureValue?.multi_grace_seconds ?? 1)

  return (
    <div className="space-y-5">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="摄像头状态"
          value={frameConnected ? '在线' : '离线'}
          detail={frameConnected ? `${cameraKey || 'cam'} · 实时画面已连接` : '等待实时画面'}
          icon={Video}
          tone={frameConnected ? 'emerald' : 'rose'}
          ping={frameConnected}
        />
        <StatCard
          label="当前画面人数"
          value={`${countText} 人`}
          detail={countState === 'normal' ? 'ROI 内人数正常' : abnormal ? 'ROI 内人数异常' : '等待检测结果'}
          icon={Users}
          tone={countState === 'normal' ? 'emerald' : abnormal ? 'rose' : 'slate'}
        />
        <StatCard
          label="摄像头数量"
          value={`${cameras.length} 路`}
          detail="已启用物流单人检测"
          icon={Camera}
          tone="indigo"
        />
        <StatCard
          label="今日告警次数"
          value={`${todayAlarmCount} 次`}
          detail={todayAlarmCount > 0 ? '无人或多人异常记录' : '今日暂无人数告警'}
          icon={BellRing}
          tone={todayAlarmCount > 0 ? 'rose' : 'emerald'}
        />
      </section>

      <ResizableMonitorLayout id="logistics-single-person">
        <div className="space-y-5">
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3">
              <CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300">
                  <Camera className="h-4 w-4" />
                </span>
                监控对象
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 px-5 pb-5">
              <div className="space-y-2">
                <Label htmlFor="logistics-monitor-camera" className="text-xs text-slate-500">摄像头</Label>
                <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || cameras.length === 0}>
                  <SelectTrigger id="logistics-monitor-camera" className="w-full rounded-xl border-slate-200 bg-slate-50/60 px-3.5 py-2.5 focus:border-[#1B3FA0] focus:ring-2 focus:ring-[#1B3FA0]/15 dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-200">
                    <SelectValue placeholder={loading ? '正在读取摄像头' : '选择摄像头'} />
                  </SelectTrigger>
                  <SelectContent>
                    {cameras.map((camera) => {
                      const key = getAiVisionCameraKey(camera)
                      return <SelectItem key={key} value={key}>{camera.name}</SelectItem>
                    })}
                  </SelectContent>
                </Select>
              </div>
              <Button type="button" variant="outline" className="w-full gap-2 rounded-xl border-slate-200 text-slate-600 active:[&>svg]:animate-spin dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300" onClick={onRefreshCameras} disabled={loading}>
                <RefreshCw className="h-4 w-4" />
                {loading ? '读取中' : '刷新状态'}
              </Button>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3">
              <CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300">
                  <Info className="h-4 w-4" />
                </span>
                判定说明
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 px-5 pb-5 text-sm">
              <div className="flex items-center justify-between rounded-xl bg-emerald-50 px-3 py-2.5 text-emerald-700"><span>ROI 内 1 人</span><strong>人数正常</strong></div>
              <div className="flex items-center justify-between rounded-xl bg-rose-50 px-3 py-2.5 text-rose-700"><span>ROI 内 0 人</span><strong>无人异常</strong></div>
              <div className="flex items-center justify-between rounded-xl bg-rose-50 px-3 py-2.5 text-rose-700"><span>ROI 内 ≥ 2 人</span><strong>多人异常</strong></div>
              <p className="text-xs leading-5 text-slate-400">无人持续 {emptyGrace} 秒、多人持续 {multiGrace} 秒后，按现有规则产生正式报警。</p>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3">
              <CardTitle className="flex items-center justify-between text-base font-bold text-slate-950 dark:text-slate-100">
                <span>实时事件</span>
                <Activity className="h-4 w-4 text-slate-300" />
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-5">
              {events.length > 0 ? (
                <div className="relative space-y-4 pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-slate-200">
                  {events.map((event) => {
                    const danger = event.state !== 'normal'
                    return (
                      <div key={event.id} className="relative">
                        <span className={cn('absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white', danger ? 'bg-rose-500' : 'bg-slate-300')} />
                        <p className={cn('text-sm font-medium', danger ? 'text-rose-600' : 'text-slate-600')}>{event.label}</p>
                        <p className="mt-1 font-mono text-[11px] text-slate-400">{new Date(event.occurredAt).toLocaleTimeString('zh-CN', { hour12: false })}</p>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-sm text-slate-400">等待 ROI 人数状态变化</p>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className={cn(CARD_CLASS, 'overflow-hidden lg:col-span-2')}>
          <CardHeader className="border-b border-slate-100 p-4 dark:border-slate-800 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white"><Video className="h-5 w-5" /></span>
                <div className="min-w-0">
                  <CardTitle className="truncate text-base font-bold text-slate-950 dark:text-slate-100">{title}</CardTitle>
                  <p className="mt-0.5 truncate text-xs text-slate-400">{cameraKey || 'cam'} · {cameraName}</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={cn('rounded-full border-0 px-2.5 py-1 shadow-none', countState === 'normal' ? 'bg-emerald-50 text-emerald-600' : abnormal ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-500')}>
                  当前 {countText} 人
                </Badge>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-500">FPS {fps?.toFixed(1) ?? '--'}</span>
                <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold', frameConnected ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-500')}>
                  {frameConnected && <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-70" /><span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" /></span>}
                  {frameConnected ? 'LIVE' : '离线'}
                </span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="relative overflow-hidden bg-slate-950">
              <div className="relative aspect-video w-full">{frameContent}</div>
              <div className="pointer-events-none absolute left-3 right-3 top-3 flex flex-wrap gap-2">
                {abnormal && <GlassPill danger><AlertTriangle className="h-3.5 w-3.5" />人员异常告警</GlassPill>}
              </div>
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-black/15" />
            </div>
            <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-400 dark:border-slate-800">{message}</div>
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}
