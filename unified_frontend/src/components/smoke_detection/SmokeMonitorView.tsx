import type { ReactNode } from 'react'
import { Activity, BellRing, Camera, Video } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { MonitorCameraToolbar } from '@/components/monitor/MonitorCameraToolbar'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { AiVisionCamera } from '@/lib/aivision'
import { SMOKE_FEATURE } from './config'
import { useSmokeStatus } from './useSmokeStatus'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'
const CONNECTION_LABELS: Record<string, string> = {
  connected: '接收中', connecting: '正在连接', disconnected: '连接断开', error: '接收异常', disabled: '未启用', unknown: '等待连接状态',
}

export function SmokeMonitorView({ department, cameras, selectedCamera, loading, message, frameConnected, frameContent, onSelectCamera, onRefreshCameras }: {
  department: DepartmentId; cameras: AiVisionCamera[]; selectedCamera: string; loading: boolean; message: string
  frameConnected: boolean; frameContent: ReactNode; onSelectCamera: (key: string) => void; onRefreshCameras: () => void
}) {
  const result = useSmokeStatus(selectedCamera, department)
  const status = result?.value
  const connected = status?.connection_state === 'connected'
  const alarmLabel = !connected ? '等待设备状态' : status.alarm_state === 'active' ? '设备烟雾报警' : status.alarm_state === 'inactive' ? '设备已上报报警解除' : '等待设备报警事件'
  return <ResizableMonitorLayout id={SMOKE_FEATURE} summary={
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="烟雾监控状态">
      <StatCard label="功能摄像头" value={String(cameras.length)} detail="当前事业部" icon={Camera} tone="indigo" />
      <StatCard label="视频画面" value={frameConnected ? '已连接' : '等待连接'} detail="摄像头监控画面" icon={Video} tone={frameConnected ? 'emerald' : 'slate'} />
      <StatCard label="设备报警接收" value={CONNECTION_LABELS[status?.connection_state ?? 'unknown'] ?? '等待连接状态'} detail={status ? `事件通道 ${status.event_channel_id}` : '等待后台连接设备'} icon={Activity} tone={connected ? 'emerald' : 'amber'} />
      <StatCard label="烟雾报警" value={alarmLabel} detail="由摄像头检测并上报" icon={BellRing} tone={status?.alarm && connected ? 'rose' : 'slate'} />
    </section>
  }>
    <div className="space-y-5"><Card className={CARD_CLASS}>
      <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="text-base">摄像头报警状态</CardTitle></CardHeader>
      <CardContent className="space-y-4 p-4 pt-0 text-sm sm:p-5 sm:pt-0">
        <p className={status?.alarm && connected ? 'font-semibold text-red-600 dark:text-red-400' : 'text-slate-600 dark:text-slate-300'}>{alarmLabel}</p>
        {status?.last_event_at && <p className="text-slate-500 dark:text-slate-400">最近设备事件：{new Date(status.last_event_at).toLocaleString('zh-CN')}</p>}
        {status?.message && <p role={status.reason === 'unsupported_event' ? 'alert' : 'status'} className="text-amber-700 dark:text-amber-300">{status.message}</p>}
        {(result?.error || status?.reason === 'error') && <p role="alert" className="text-red-600 dark:text-red-400">{result?.error || '设备报警连接异常，请核对设备连接配置。'}</p>}
        <p className="text-slate-500 dark:text-slate-400">接收摄像头自身的烟雾报警，并按配置推送企业微信和喇叭；报警记录可在数据中心查看。</p>
      </CardContent>
    </Card></div>
    <Card className={`${CARD_CLASS} gap-0 overflow-hidden py-0`}>
      <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="flex items-center justify-between gap-3 text-base"><span className="flex items-center gap-2"><Video className="h-4 w-4" />烟雾监控</span><span className="text-sm font-normal text-slate-500 dark:text-slate-400">{frameConnected ? '实时画面' : '等待连接'}</span></CardTitle></CardHeader>
      <CardContent className="p-0">
        <MonitorCameraToolbar cameras={cameras} selectedCamera={selectedCamera} loading={loading} onSelectCamera={onSelectCamera} onRefreshCameras={onRefreshCameras} />
        <div className="relative aspect-video overflow-hidden bg-slate-950">{frameContent}</div>
        {message && <p className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{message}</p>}
      </CardContent>
    </Card>
  </ResizableMonitorLayout>
}
