import { CameraLivePreview } from '@/components/monitor/CameraLivePreview'
import type { AiVisionCamera } from '@/lib/aivision'
import { useDepartmentCatalog } from '@/hooks/use-department-catalog'
import type { LucideIcon } from 'lucide-react'
import { Activity, AlertTriangle, BellRing, Camera, Info, RefreshCw, Users, Video } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'

import {
  type LogisticsChannelStatusEvent,
} from './monitorPresentation'
import type {
  LogisticsChannel,
  LogisticsChannelDetail,
  LogisticsFeatureName,
  LogisticsChannelReason,
  LogisticsChannelRuntimeStatus,
} from './types'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

const reasonPresentation: Record<LogisticsChannelReason, { label: string; className: string; tone: StatTone }> = {
  normal: { label: '正常', className: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300', tone: 'emerald' },
  empty: { label: '无人异常', className: 'bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300', tone: 'rose' },
  multiple: { label: '多人异常', className: 'bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300', tone: 'rose' },
  unknown: { label: '未知', className: 'bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300', tone: 'amber' },
  inactive: { label: '检测未运行', className: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300', tone: 'slate' },
  unconfigured: { label: '未配置', className: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300', tone: 'slate' },
}

type StatTone = 'emerald' | 'indigo' | 'amber' | 'rose' | 'slate'

function StatCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = 'indigo',
}: {
  label: string
  value: string
  detail: string
  icon: LucideIcon
  tone?: StatTone
}) {
  const tones: Record<StatTone, string> = {
    emerald: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-300',
    indigo: 'bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-950/60 dark:text-amber-300',
    rose: 'bg-rose-50 text-rose-600 dark:bg-rose-950/60 dark:text-rose-300',
    slate: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300',
  }

  return (
    <article className={cn(CARD_CLASS, 'min-w-0 p-3 sm:p-4')}>
      <span className={cn('hidden h-9 w-9 items-center justify-center rounded-xl sm:flex', tones[tone])}>
        <Icon className="h-[18px] w-[18px]" />
      </span>
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400 sm:mt-4">{label}</p>
      <p className="mt-1 break-words text-xl font-bold leading-tight text-slate-950 dark:text-slate-100 sm:truncate sm:text-[22px]" title={value}>{value}</p>
      <p className="mt-1.5 text-[11px] leading-4 text-slate-500 dark:text-slate-400 sm:truncate sm:text-xs" title={detail}>{detail}</p>
    </article>
  )
}

function unknownReason(reason: string | null) {
  if (!reason) return '等待检测结果'
  if (reason === 'offline') return '摄像头离线'
  if (reason === 'stale') return '结果过期'
  if (reason === 'waiting' || reason === 'no_result') return '等待检测结果'
  if (reason === 'detection_inactive') return '当前不在检测时间段或通道未启用'
  return reason
}

function formatCameraUpdatedAt(value: number | null) {
  if (value === null || !Number.isFinite(value) || value <= 0) return '暂无更新时间'
  const timestampMs = value < 1_000_000_000_000 ? value * 1000 : value
  const date = new Date(timestampMs)
  if (Number.isNaN(date.getTime())) return '暂无更新时间'
  return `更新于 ${date.toLocaleString('zh-CN', { hour12: false })}`
}

function formatClock(value: string | null) {
  if (!value) return '--'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '--'
    : parsed.toLocaleTimeString('zh-CN', { hour12: false })
}

function eventPresentation(reason: LogisticsChannelStatusEvent['reason']) {
  if (reason === 'empty') return { label: '所有摄像头明确无人，触发通道告警', danger: true }
  if (reason === 'multiple') return { label: '单路摄像头出现多人，触发通道告警', danger: true }
  return { label: '通道恢复为单人检测正常状态', danger: false }
}

export type LogisticsChannelMonitorViewProps = {
  feature: LogisticsFeatureName
  title: string
  channels: LogisticsChannel[]
  selectedChannelId: number | null
  selectedChannel: LogisticsChannel | null
  selectedChannelDetail: LogisticsChannelDetail | null
  status: LogisticsChannelRuntimeStatus | null
  cameras: AiVisionCamera[]
  todayAlarmCount: number
  latestAlarmAt: string | null
  events: LogisticsChannelStatusEvent[]
  loading: boolean
  error: string | null
  onSelectChannel: (channelId: number) => void
  onRefresh: () => void
}

export function LogisticsChannelMonitorView({
  feature,
  title,
  channels,
  selectedChannelId,
  selectedChannel,
  selectedChannelDetail,
  status,
  cameras,
  todayAlarmCount,
  latestAlarmAt,
  events,
  loading,
  error,
  onSelectChannel,
  onRefresh,
}: LogisticsChannelMonitorViewProps) {
  const { labels: departmentLabels } = useDepartmentCatalog()
  const reason = status?.reason ?? selectedChannelDetail?.status?.reason ?? 'unknown'
  const presentation = reasonPresentation[reason]
  const cameraStates = status
    ? status.camera_ids
      .map((cameraId) => status.camera_states[String(cameraId)])
      .filter((camera): camera is NonNullable<typeof camera> => Boolean(camera))
    : []
  const onlineCount = cameraStates.filter((camera) => camera.online).length
  const offlineCount = cameraStates.filter((camera) => !camera.online).length
  const memberCount = selectedChannelDetail?.members.filter((member) => member.enabled).length
    ?? status?.camera_ids.length
    ?? 0
  const routeCounts = cameraStates.length
    ? cameraStates.map((camera) => camera.count ?? '--').join(' / ')
    : '--'
  const members = selectedChannelDetail?.members.filter((member) => member.enabled) ?? []

  return (
    <div className="min-w-0 space-y-3 sm:space-y-5">
      {error ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-300">{error}</div> : null}

      {loading && !selectedChannel ? (
        <div className="rounded-2xl border border-slate-200/70 bg-white px-6 py-12 text-center text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">正在读取物流通道与实时状态…</div>
      ) : null}

      {!loading && channels.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">暂无物流通道，请由管理员先新增通道并绑定摄像头。</div>
      ) : null}

      {selectedChannel ? (
          <ResizableMonitorLayout id={`logistics-channel-${feature}`} summary={<section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="通道状态" value={presentation.label} detail={selectedChannel.enabled ? selectedChannel.name : '通道已停用'} icon={Video} tone={presentation.tone} />
            <StatCard label="摄像头状态" value={status ? `${onlineCount} 在线 / ${offlineCount} 离线` : '--'} detail={`已配置 ${memberCount} 路，最多 9 路`} icon={Camera} tone={status && offlineCount === 0 ? 'emerald' : offlineCount > 0 ? 'amber' : 'slate'} />
            <StatCard label="各路人数" value={routeCounts} detail="按启用成员顺序展示" icon={Users} tone={reason === 'multiple' ? 'rose' : 'indigo'} />
            <StatCard label="今日通道告警" value={`${todayAlarmCount} 次`} detail={todayAlarmCount ? `最近一次 ${formatClock(latestAlarmAt)}` : '今日暂无通道告警'} icon={BellRing} tone={todayAlarmCount ? 'rose' : 'emerald'} />
          </section>}>
            <div className="space-y-3 sm:space-y-5">
              <Card className={CARD_CLASS}>
                <CardHeader className="p-5 pb-3">
                  <CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Info className="h-4 w-4" /></span>
                    通道检测详情
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4 px-5 pb-5 text-sm">
                  <details>
                    <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium text-slate-600 dark:text-slate-300">查看联合判定规则</summary>
                    <div className="space-y-3 pt-2">
                  <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">多人告警</span><span className="text-slate-700 dark:text-slate-300">任一路摄像头出现 2 人及以上</span></div>
                  <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">无人告警</span><span className="text-slate-700 dark:text-slate-300">所有启用摄像头都明确为 0 人</span></div>
                  <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">正常状态</span><span className="text-slate-700 dark:text-slate-300">至少一路为 1 人且没有多人</span></div>
                  <div className="grid grid-cols-[76px_1fr] gap-2"><span className="text-slate-400">未知结果</span><span className="text-slate-700 dark:text-slate-300">离线、过期或未知不当作 0 人</span></div>
                    </div>
                  </details>

                  {cameraStates.length ? (
                    <div className="space-y-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                      <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">逐路状态</p>
                      {cameraStates.map((camera) => {
                        const cameraPresentation = reasonPresentation[camera.status]
                        return (
                          <div key={camera.camera_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                            <div className="flex items-center justify-between gap-2">
                              <span className="min-w-0 break-words text-sm font-semibold text-slate-700 dark:text-slate-200">{camera.camera_name}</span>
                              <Badge className={cn('shrink-0 border-0', cameraPresentation.className)}>{cameraPresentation.label}</Badge>
                            </div>
                            <div className="mt-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                              <span>{camera.count === null ? '--' : `${camera.count} 人`}</span>
                              <span>{camera.online ? '在线' : '离线'}</span>
                            </div>
                            <p className="mt-1 text-right text-[11px] text-slate-400">{formatCameraUpdatedAt(camera.updated_at)}</p>
                            {camera.status === 'unknown' ? <p className="mt-2 flex items-center gap-1 text-xs text-amber-700 dark:text-amber-300"><AlertTriangle className="h-3.5 w-3.5" />{unknownReason(camera.stale_reason)}</p> : null}
                          </div>
                        )
                      })}
                    </div>
                  ) : null}
                </CardContent>
              </Card>

              <Card className={CARD_CLASS}>
                <CardHeader className="p-5 pb-3">
                  <CardTitle className="flex items-center justify-between text-base font-bold text-slate-950 dark:text-slate-100"><span>实时事件</span><Activity className="h-4 w-4 text-slate-300 dark:text-slate-600" /></CardTitle>
                </CardHeader>
                <CardContent className="px-5 pb-5">
                  {events.length ? (
                    <div className="relative space-y-4 pl-5 before:absolute before:bottom-1 before:left-[5px] before:top-1 before:w-px before:bg-slate-200 dark:before:bg-slate-700">
                      {events.map((event) => {
                        const eventStyle = eventPresentation(event.reason)
                        return (
                          <div key={event.id} className="relative">
                            <span className={cn('absolute -left-5 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white dark:border-slate-900', eventStyle.danger ? 'bg-rose-500' : 'bg-emerald-500')} />
                            <p className={cn('text-sm font-medium', eventStyle.danger ? 'text-rose-600 dark:text-rose-300' : 'text-slate-600 dark:text-slate-300')}>{eventStyle.label}</p>
                            <p className="mt-1 font-mono text-[11px] text-slate-400">{formatClock(event.occurredAt)}</p>
                          </div>
                        )
                      })}
                    </div>
                  ) : <p className="text-sm text-slate-400">等待物流通道状态事件</p>}
                </CardContent>
              </Card>
            </div>

            <Card className={cn(CARD_CLASS, 'gap-0 overflow-hidden py-0 lg:col-span-2')}>
              <CardHeader className="min-w-0 grid-cols-[minmax(0,1fr)] space-y-3 border-b border-slate-100 p-3 [.border-b]:pb-3 dark:border-slate-800 sm:p-4 sm:px-5 sm:[.border-b]:pb-4">
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="logistics-channel-monitor-select" className="text-xs text-slate-500 dark:text-slate-400">物流通道</Label>
                  <div className="flex min-w-0 items-center gap-2">
                    <Select value={selectedChannelId === null ? '' : String(selectedChannelId)} onValueChange={(value) => onSelectChannel(Number(value))} disabled={loading || channels.length === 0}>
                      <SelectTrigger id="logistics-channel-monitor-select" className="h-11 min-h-11 min-w-0 flex-1 rounded-xl border-slate-200 bg-slate-50/60 text-left [&>span]:min-w-0 [&>span]:flex-1 [&>span]:truncate dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-200"><SelectValue placeholder={loading ? '正在读取物流通道' : '请选择物流通道'} /></SelectTrigger>
                      <SelectContent position="popper" className="w-[var(--radix-select-trigger-width)] max-w-[calc(100vw-1.5rem)]">
                        {channels.map((channel) => <SelectItem key={channel.id} value={String(channel.id)} className="min-h-11 whitespace-normal py-2.5"><span className="break-words">{departmentLabels[channel.department] ?? channel.department} · {channel.name}</span></SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Button type="button" variant="outline" className="h-11 w-11 shrink-0 rounded-xl border-slate-200 p-0 text-slate-600 active:[&>svg]:animate-spin dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300" onClick={onRefresh} disabled={loading} title="刷新状态" aria-label="刷新物流通道和监控状态"><RefreshCw className="h-4 w-4" /></Button>
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="hidden min-w-0 items-center gap-3 sm:flex">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white dark:bg-blue-700"><Video className="h-5 w-5" /></span>
                    <div className="min-w-0">
                      <CardTitle className="truncate text-base font-bold text-slate-950 dark:text-slate-100">物流通道实时监控</CardTitle>
                      <p className="mt-0.5 truncate text-xs text-slate-400">{title} · {selectedChannel.name}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={cn('rounded-full border-0 px-2.5 py-1 shadow-none', presentation.className)}>{presentation.label}</Badge>
                    {status?.alarm_suppressed && <Badge variant="outline">检测与报警未启用</Badge>}

                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <div className={cn('grid gap-1 bg-slate-950', members.length > 1 && 'sm:grid-cols-2', members.length > 4 && 'xl:grid-cols-3')}>
                  {members.map((member) => {
                    const camera = cameras.find((item) => item.camera_id === member.camera_id)
                    return <div key={member.id} className="min-w-0">
                      <p className="px-3 py-2 text-xs text-slate-200">{camera?.name || `摄像头 ${member.camera_id}`}</p>
                      <div className="aspect-video">{camera ? <CameraLivePreview cameraKey={camera.shm_name} feature={feature}
                        department={selectedChannel.department} enabled={camera.enabled} fps={camera.fps} />
                        : <p className="flex h-full items-center justify-center text-sm text-slate-300">等待摄像头信息</p>}</div>
                    </div>
                  })}
                  {!members.length && <p className="flex min-h-56 items-center justify-center text-sm text-slate-300">通道未配置启用的摄像头</p>}
                </div>
              </CardContent>
            </Card>
          </ResizableMonitorLayout>
      ) : null}
    </div>
  )
}
