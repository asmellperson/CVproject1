import { AlertTriangle, BellRing, Camera, RefreshCw, Users, Video } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'

import type {
  LogisticsChannel,
  LogisticsChannelDetail,
  LogisticsChannelReason,
  LogisticsChannelRuntimeStatus,
} from './types'

const reasonPresentation: Record<LogisticsChannelReason, { label: string; className: string }> = {
  normal: { label: '正常', className: 'bg-emerald-50 text-emerald-700' },
  empty: { label: '无人异常', className: 'bg-rose-50 text-rose-700' },
  multiple: { label: '多人异常', className: 'bg-rose-50 text-rose-700' },
  unknown: { label: '未知', className: 'bg-amber-50 text-amber-700' },
  inactive: { label: '未启用', className: 'bg-slate-100 text-slate-600' },
  unconfigured: { label: '未配置', className: 'bg-slate-100 text-slate-600' },
}

function unknownReason(reason: string | null) {
  if (!reason) return '等待检测结果'
  if (reason === 'offline') return '摄像头离线'
  if (reason === 'stale') return '结果过期'
  if (reason === 'waiting' || reason === 'no_result') return '等待检测结果'
  return reason
}

export type LogisticsChannelMonitorViewProps = {
  title: string
  channels: LogisticsChannel[]
  selectedChannelId: number | null
  selectedChannel: LogisticsChannel | null
  selectedChannelDetail: LogisticsChannelDetail | null
  status: LogisticsChannelRuntimeStatus | null
  frameUrl: string | null
  todayAlarmCount: number
  loading: boolean
  error: string | null
  frameError: string | null
  onSelectChannel: (channelId: number) => void
  onRefresh: () => void
}

export function LogisticsChannelMonitorView({
  title,
  channels,
  selectedChannelId,
  selectedChannel,
  selectedChannelDetail,
  status,
  frameUrl,
  todayAlarmCount,
  loading,
  error,
  frameError,
  onSelectChannel,
  onRefresh,
}: LogisticsChannelMonitorViewProps) {
  const reason = status?.reason ?? selectedChannelDetail?.status?.reason ?? 'unknown'
  const presentation = reasonPresentation[reason]
  const cameraStates = status
    ? status.camera_ids
      .map((cameraId) => status.camera_states[String(cameraId)])
      .filter((camera): camera is NonNullable<typeof camera> => Boolean(camera))
    : []
  const onlineCount = cameraStates.filter((camera) => camera.online).length
  const memberCount = selectedChannelDetail?.members.filter((member) => member.enabled).length ?? status?.camera_ids.length ?? 0
  const offlineCount = cameraStates.filter((camera) => !camera.online).length

  return (
    <div className="space-y-5">
      <Card className="border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1 space-y-2">
            <label htmlFor="logistics-channel-monitor-select" className="text-xs font-medium text-slate-500">物流通道</label>
            <Select
              value={selectedChannelId === null ? '' : String(selectedChannelId)}
              onValueChange={(value) => onSelectChannel(Number(value))}
              disabled={loading || channels.length === 0}
            >
              <SelectTrigger id="logistics-channel-monitor-select" className="w-full sm:max-w-sm">
                <SelectValue placeholder={loading ? '正在读取物流通道' : '请选择物流通道'} />
              </SelectTrigger>
              <SelectContent>
                {channels.map((channel) => <SelectItem key={channel.id} value={String(channel.id)}>{channel.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <Button type="button" variant="outline" className="gap-2" onClick={onRefresh} disabled={loading}>
            <RefreshCw className="h-4 w-4" />刷新状态
          </Button>
        </CardContent>
      </Card>

      {error ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}
      {!loading && channels.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-500">暂无物流通道，请由管理员先新增通道并绑定摄像头。</div>
      ) : null}

      {selectedChannel ? (
        <>
          <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <SummaryCard label="通道状态" value={presentation.label} detail={selectedChannel.enabled ? selectedChannel.name : '通道已停用'} icon={Video} className={presentation.className} />
            <SummaryCard label="摄像头状态" value={status ? `${onlineCount} 在线 / ${offlineCount} 离线` : '--'} detail={`已配置 ${memberCount} 路，最多 9 路`} icon={Camera} />
            <SummaryCard label="各路人数" value={cameraStates.length ? cameraStates.map((item) => item.count ?? '--').join(' / ') : '--'} detail="按通道成员顺序展示" icon={Users} />
            <SummaryCard label="今日通道告警" value={`${todayAlarmCount} 次`} detail="无人或多人通道告警" icon={BellRing} />
          </section>

          <section className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
            <Card className="overflow-hidden border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <CardHeader className="border-b border-slate-100 dark:border-slate-800">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <CardTitle>{title}</CardTitle>
                    <p className="mt-1 text-xs text-slate-500">{selectedChannel.name} · 后端实时拼接画面</p>
                  </div>
                  <Badge className={cn('border-0', presentation.className)}>{presentation.label}</Badge>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <div className="flex aspect-video items-center justify-center bg-slate-950">
                  {frameUrl ? <img src={frameUrl} alt={`${selectedChannel.name}拼接监控画面`} className="h-full w-full object-contain" /> : (
                    <div className="px-6 text-center text-sm text-slate-300">{frameError || (memberCount === 0 ? '通道未配置摄像头' : '等待拼接画面')}</div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <CardHeader><CardTitle className="text-base">成员摄像头状态</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {cameraStates.length === 0 ? <p className="text-sm text-slate-500">等待检测结果</p> : cameraStates.map((camera) => {
                  const cameraPresentation = reasonPresentation[camera.status]
                  return (
                    <div key={camera.camera_id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold">{camera.camera_name}</span>
                        <Badge className={cn('shrink-0 border-0', cameraPresentation.className)}>{cameraPresentation.label}</Badge>
                      </div>
                      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                        <span>{camera.count === null ? '--' : `${camera.count} 人`}</span>
                        <span>{camera.online ? '在线' : '离线'}</span>
                      </div>
                      {camera.status === 'unknown' ? (
                        <p className="mt-2 flex items-center gap-1 text-xs text-amber-700"><AlertTriangle className="h-3.5 w-3.5" />{unknownReason(camera.stale_reason)}</p>
                      ) : null}
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          </section>
        </>
      ) : null}
    </div>
  )
}

function SummaryCard({ label, value, detail, icon: Icon, className }: { label: string; value: string; detail: string; icon: typeof Camera; className?: string }) {
  return (
    <Card className="border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <CardContent className="p-4">
        <span className={cn('flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-700', className)}><Icon className="h-4 w-4" /></span>
        <p className="mt-4 text-xs text-slate-500">{label}</p>
        <p className="mt-1 truncate text-xl font-bold" title={value}>{value}</p>
        <p className="mt-1 truncate text-xs text-slate-400" title={detail}>{detail}</p>
      </CardContent>
    </Card>
  )
}
