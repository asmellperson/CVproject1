import type { ReactNode } from 'react'
import { Activity, Camera, RefreshCw, ScanFace, ShieldAlert, UserCheck, UsersRound, Video } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import { FENCE_FEATURE } from './api'
import { useFenceStatus } from './useFenceStatus'

const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'
const STATES = { disabled: '未启用', offline: '视频离线', waiting: '等待检测', stale: '结果过期', error: '检测异常', ready: '检测中' }
const IDENTITIES = { pending: '身份待核验', allowed: '白名单', unauthorized: '非白名单' }
const REASONS: Record<string, string> = { forbidden_time: '异常时间出没', unauthorized: '异常人员出没', unknown_face: '异常人员出没（未知人员）' }

export function FenceMonitorView({
  department, cameras, selectedCamera, loading, message, frameConnected, frameContent, onSelectCamera, onRefreshCameras,
}: {
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
  const featureCameras = getEnabledFeatureCameras(cameras, FENCE_FEATURE, department)
  const result = useFenceStatus(selectedCamera)
  const status = result?.value
  const persons = status?.persons ?? []

  return (
    <div className="space-y-5">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="警戒围栏实时状态">
        <StatCard label="检测状态" value={status ? STATES[status.state] : '等待检测'} detail={status?.error || result?.error || '读取当前检测结果'} icon={Activity} tone={status?.state === 'ready' ? 'emerald' : 'amber'} />
        <StatCard label="当前规则" value={status ? status.mode === 'forbidden' ? '禁止任何人出现' : '仅允许白名单' : '—'} detail={status?.timezone || '按每日时段执行'} icon={ShieldAlert} tone="indigo" />
        <StatCard label="区域人数" value={status?.count == null ? '—' : String(status.count)} detail={status?.alarm ? '区域内存在违规人员' : status?.state === 'ready' ? '当前未触发报警' : '尚无有效判定'} icon={UsersRound} tone={status?.alarm ? 'rose' : 'slate'} />
        <StatCard label="待核验人数" value={status?.pending_count == null ? '—' : String(status.pending_count)} detail="看不清人脸不会按超时报警" icon={UserCheck} tone="amber" />
      </section>
      <ResizableMonitorLayout id="security-fence">
        <div className="space-y-5">
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><Camera className="h-4 w-4" />监控对象</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5">
              <Label htmlFor="fence-monitor-camera">摄像头</Label>
              <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || !featureCameras.length}>
                <SelectTrigger id="fence-monitor-camera" className="w-full rounded-xl border-slate-200 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-950/60"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
                <SelectContent>{featureCameras.map((camera) => <SelectItem key={camera.id} value={getAiVisionCameraKey(camera)}>{camera.name}{!camera.enabled ? '（摄像头已停用）' : ''}</SelectItem>)}</SelectContent>
              </Select>
              <Button variant="outline" className="w-full gap-2 rounded-xl border-slate-200 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300" disabled={loading} onClick={onRefreshCameras}><RefreshCw className="h-4 w-4" />刷新状态</Button>
            </CardContent>
          </Card>
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><ScanFace className="h-4 w-4" />当前识别结果</CardTitle></CardHeader>
            <CardContent className="space-y-3 px-5 pb-5">
              <p className="text-sm text-slate-500 dark:text-slate-400">区域内 {status?.count ?? '—'} 人 · 待核验 {status?.pending_count ?? '—'} 人</p>
              {status?.alarm && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700 dark:border-red-900 dark:bg-red-950/40">报警：警戒区域内存在{status.mode === 'forbidden' ? '禁入时段出没人员' : '非白名单或未知人员'}。</p>}
              {persons.map((person) => (
                <div key={person.track_id} className={`rounded-xl border p-3 ${person.alarm ? 'border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40' : person.identity === 'pending' ? 'border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40' : 'border-slate-200 dark:border-slate-700'}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="break-words font-medium text-slate-950 dark:text-slate-100">{person.person_name || `人员 ${person.track_id}`}</p>
                      <Badge variant="outline" className={`mt-1 ${person.alarm ? 'border-red-300 text-red-700 dark:border-red-800 dark:text-red-400' : person.identity === 'pending' ? 'border-amber-300 text-amber-700 dark:border-amber-800 dark:text-amber-400' : person.identity === 'allowed' ? 'border-emerald-300 text-emerald-700 dark:border-emerald-800 dark:text-emerald-400' : 'border-orange-300 text-orange-700 dark:border-orange-800 dark:text-orange-400'}`}>{person.identity === 'unauthorized' && person.person_id == null ? '未知人员' : IDENTITIES[person.identity]}</Badge>
                    </div>
                    <span className="shrink-0 font-mono text-sm text-slate-600 dark:text-slate-300" aria-label="相似度">{person.similarity == null ? '—' : `${(person.similarity * 100).toFixed(1)}%`}</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{person.in_roi ? '警戒区域内' : '警戒区域外'}</p>
                  {person.alarm && person.reason && <p className="mt-1 text-xs font-medium text-red-700 dark:text-red-400">{REASONS[person.reason]}</p>}
                </div>
              ))}
              {!persons.length && <p className="text-sm text-slate-500 dark:text-slate-400">{status?.state === 'ready' ? '当前画面未检测到人员' : '等待有效识别结果'}</p>}
              {(status?.error || result?.error) && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{status?.error || result?.error}</p>}
            </CardContent>
          </Card>
        </div>
        <Card className={`${CARD_CLASS} overflow-hidden`}>
          <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center justify-between gap-3 text-base font-bold text-slate-950 dark:text-slate-100"><span className="flex items-center gap-2"><Video className="h-4 w-4" />警戒围栏监控</span><span className="text-sm font-normal text-slate-500 dark:text-slate-400">{frameConnected ? '实时画面' : '等待连接'}</span></CardTitle></CardHeader>
          <CardContent className="p-0">
            <div className="relative aspect-video overflow-hidden bg-slate-950">{frameContent}</div>
            <p className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{message}</p>
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}
