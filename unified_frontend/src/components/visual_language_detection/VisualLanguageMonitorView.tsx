import type { ReactNode } from 'react'
import { Camera, Clock3, RefreshCw, Sparkles, Timer, Video } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatCard } from '@/components/feature_dashboard/FeatureDashboardMonitorView'
import { VideoQuestionChat } from './VideoQuestionChat'
import { useVisualLanguageMonitor } from './useVisualLanguageMonitor'

type Props = {
  department: DepartmentId
  cameras: AiVisionCamera[]
  selectedCamera: string
  loading: boolean
  message: string
  frameContent: ReactNode
  frameConnected: boolean
  onSelectCamera: (key: string) => void
  onRefreshCameras: () => void
}

export function VisualLanguageMonitorView({ department, cameras, selectedCamera, loading, message,
  frameContent, frameConnected, onSelectCamera, onRefreshCameras }: Props) {
  const { status, events, error, questionError, answer, asking, ask } = useVisualLanguageMonitor(selectedCamera, department)
  const cameraName = cameras.find((camera) => getAiVisionCameraKey(camera) === selectedCamera)?.name || '未选择摄像头'
  const latestResultAt = status?.latest_result_at ? new Date(status.latest_result_at) : null
  return <div className="space-y-6">
    <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatCard label="摄像头状态" value={!selectedCamera ? '未选择' : frameConnected ? '在线' : '离线'} detail={frameConnected ? `${cameraName} · 实时画面已连接` : '等待实时画面'} icon={Video} tone={frameConnected ? 'emerald' : 'slate'} ping={frameConnected} />
      <StatCard label="启用摄像头" value={`${cameras.length} 路`} detail="已启用指令驱动智慧安防" icon={Camera} tone="indigo" />
      <StatCard label="最近推理耗时" value={status?.latency_seconds == null ? '—' : `${status.latency_seconds.toFixed(2)} 秒`} detail="当前摄像头最近一次推理" icon={Timer} tone="amber" />
      <StatCard label="最近结果时间" value={latestResultAt ? latestResultAt.toLocaleTimeString('zh-CN', { hour12: false }) : '—'} detail={latestResultAt ? latestResultAt.toLocaleDateString('zh-CN') : '等待视觉理解结果'} icon={Clock3} tone="indigo" />
    </section>
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(22rem,1fr)]">
      <div className="min-w-0 space-y-6">
        <Card className="overflow-hidden dark:border-slate-800 dark:bg-slate-900">
          <CardHeader className="flex flex-col justify-between gap-4 border-b bg-slate-50 dark:border-slate-800 dark:bg-slate-900 lg:flex-row lg:items-center">
            <CardTitle className="flex items-center gap-2 text-lg"><Video className="h-5 w-5 text-blue-600" />实时画面</CardTitle>
            <div className="flex gap-2">
              <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || !cameras.length}>
                <SelectTrigger className="w-full sm:w-64" aria-label="监控摄像头"><SelectValue placeholder="选择摄像头" /></SelectTrigger>
                <SelectContent>{cameras.map((camera) => <SelectItem key={camera.camera_id} value={getAiVisionCameraKey(camera)}>{camera.name}</SelectItem>)}</SelectContent>
              </Select>
              <Button variant="outline" onClick={onRefreshCameras} disabled={loading}><RefreshCw className="h-4 w-4" />刷新</Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4 p-5">
            <div className="space-y-3">
              <div className="relative aspect-video overflow-hidden rounded-2xl bg-slate-950">{frameContent}</div>
              <p className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
            </div>
            {(error || status?.error) && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-300">{error || status?.error}</p>}
          </CardContent>
        </Card>
        <Card className="relative gap-4 overflow-hidden rounded-2xl border-blue-200 bg-gradient-to-br from-blue-50 via-white to-indigo-50 shadow-sm dark:border-blue-900 dark:from-blue-950/60 dark:via-slate-900 dark:to-indigo-950/40">
          <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-blue-500 to-indigo-500" />
          <CardHeader className="flex flex-row items-center gap-3 pb-0">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#1B3FA0] text-white shadow-sm dark:bg-blue-600"><Sparkles className="h-5 w-5" /></span>
            <div>
              <CardTitle className="text-lg font-bold text-[#132C72] dark:text-blue-100">最新视觉理解结果</CardTitle>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{cameraName}</p>
            </div>
          </CardHeader>
          <CardContent aria-live="polite" className="space-y-4">
            <p className="whitespace-pre-wrap break-words rounded-xl border border-white/80 bg-white/75 p-5 text-base font-medium leading-8 text-slate-800 dark:border-blue-900/50 dark:bg-slate-950/40 dark:text-slate-100">{status?.latest_result || '等待视觉理解结果'}</p>
            {latestResultAt && <p className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400"><Clock3 className="h-3.5 w-3.5" />{latestResultAt.toLocaleString('zh-CN')}</p>}
          </CardContent>
        </Card>
      </div>
      <div className="min-w-0 space-y-6">
        <VideoQuestionChat selectedCamera={selectedCamera} frameConnected={frameConnected} answer={answer} questionError={questionError} asking={asking} ask={ask} />
        <Card className="dark:border-slate-800 dark:bg-slate-900">
          <CardHeader><CardTitle className="text-lg">事件时间线</CardTitle></CardHeader>
          <CardContent><div className="max-h-[32rem] space-y-4 overflow-y-auto">
            {!events.length && <p className="text-sm text-slate-500">{selectedCamera ? '暂无事件，等待视频理解结果。' : '请先选择摄像头。'}</p>}
            {events.map((event) => <article key={event.id} className="border-l-2 border-blue-200 pl-4 dark:border-blue-900">
              <div className="flex flex-wrap gap-2 text-xs text-slate-500"><time>{new Date(event.captured_at).toLocaleString('zh-CN')}</time><span>{event.kind === 'question' ? '视频问答' : event.kind === 'error' ? '处理异常' : '视觉理解'}</span></div>
              {event.question && <p className="mt-2 text-sm font-semibold">{event.question}</p>}
              <p className={`mt-2 whitespace-pre-wrap break-words text-sm leading-6 ${event.kind === 'error' ? 'text-red-600 dark:text-red-300' : ''}`}>{event.text}</p>
            </article>)}
          </div></CardContent>
        </Card>
      </div>
    </div>
  </div>
}
