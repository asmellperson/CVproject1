import type { ReactNode } from 'react'
import { Activity, Camera, ShieldAlert, UsersRound, Video } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { MonitorCameraToolbar } from '@/components/monitor/MonitorCameraToolbar'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { AiVisionCamera } from '@/lib/aivision'
import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import { TAILGATING_FEATURE } from './config'
import { useTailgatingStatus } from './useTailgatingStatus'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'
const STATES = { disabled: '未启用', offline: '视频离线', waiting: '等待检测', stale: '结果过期', error: '检测异常', ready: '检测中' }

export function TailgatingMonitorView({ department, cameras, selectedCamera, loading, message, frameConnected, frameContent, onSelectCamera, onRefreshCameras }: {
  department: DepartmentId
  cameras: AiVisionCamera[]
  selectedCamera: string
  loading: boolean
  message: string
  frameConnected: boolean
  frameContent: ReactNode
  onSelectCamera: (key: string) => void
  onRefreshCameras: () => void
}) {
  const featureCameras = getEnabledFeatureCameras(cameras, TAILGATING_FEATURE, department)
  const result = useTailgatingStatus(selectedCamera)
  const status = result?.value
  return <div className="space-y-5">
    <ResizableMonitorLayout id="tailgating" summary={
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="非法闯闸实时状态">
        <StatCard
          label="功能摄像头"
          value={String(featureCameras.length)}
          detail="当前事业部"
          icon={Camera}
          tone="indigo" />
        <StatCard
          label="ROI 内人数"
          value={status?.count == null ? '—' : String(status.count)}
          detail={status ? STATES[status.state] : '等待检测结果'}
          icon={UsersRound}
          tone="emerald" />
        <StatCard
          label="通行判定"
          value={status?.state !== 'ready' ? '等待有效结果' : status.alarm ? '非法闯闸' : '未发现尾随'}
          detail="共同出现且同向过线"
          icon={ShieldAlert}
          tone={status?.alarm ? 'rose' : 'slate'} />
        <StatCard
          label="实际检测间隔"
          value={status?.sample_interval_seconds == null ? '—' : `${status.sample_interval_seconds.toFixed(2)} 秒`}
          detail={status?.updated_at ? new Date(status.updated_at).toLocaleTimeString() : '等待更新'}
          icon={Activity}
          tone="amber" />
      </section>
    }>
      <div className="space-y-5">
        <Card className={CARD_CLASS}>
          <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3">
            <CardTitle className="text-base">通行状态</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 p-4 pt-0 sm:p-5 sm:pt-0">
            {status?.reason === 'unconfigured' && <p className="text-sm text-amber-700 dark:text-amber-400">请在配置管理中绘制并保存 ROI 和过闸判定线。</p>}
            {status?.events.map((event) => <div
              key={event.id}
              className="rounded-xl border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950/30">
              <Badge variant="destructive">同向通行异常</Badge>
              <p className="mt-2 text-sm">人员 #{event.track_ids.join('、#')} 共同出现 {event.overlap_seconds.toFixed(2)} 秒</p>
            </div>)}
            {!status?.events.length && <p className="text-sm text-slate-500 dark:text-slate-400">分别跟踪人员，仅在共同出现与同向过线同时成立时报警。</p>}
            {(status?.error || result?.error) && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{status?.error || result?.error}</p>}
          </CardContent>
        </Card>
      </div>
      <Card className={`${CARD_CLASS} gap-0 overflow-hidden py-0`}>
        <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3">
          <CardTitle className="flex items-center justify-between gap-3 text-base">
            <span className="flex items-center gap-2">
              <Video className="h-4 w-4" />非法闯闸监控</span>
            <span className="text-sm font-normal text-slate-500 dark:text-slate-400">{frameConnected ? '实时画面' : '等待连接'}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <MonitorCameraToolbar
            cameras={featureCameras}
            selectedCamera={selectedCamera}
            loading={loading}
            onSelectCamera={onSelectCamera}
            onRefreshCameras={onRefreshCameras}
          />
          <div className="relative aspect-video overflow-hidden bg-slate-950">{frameContent}</div>
          {message && <p className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{message}</p>}
        </CardContent>
      </Card>
    </ResizableMonitorLayout>
  </div>
}
