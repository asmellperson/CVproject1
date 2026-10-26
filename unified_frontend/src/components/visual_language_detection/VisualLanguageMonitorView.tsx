import type { ReactNode } from 'react'
import { Camera, Clock3, Sparkles, Timer, Video } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { MonitorCameraToolbar } from '@/components/monitor/MonitorCameraToolbar'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
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
  return <div className="space-y-5">
    <ResizableMonitorLayout id="visual-language" summary={
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="摄像头状态" value={!selectedCamera ? '未选择' : frameConnected ? '在线' : '离线'} detail={frameConnected ? `${cameraName} · 实时画面已连接` : '等待实时画面'} icon={Video} tone={frameConnected ? 'emerald' : 'slate'} ping={frameConnected} />
        <StatCard label="启用摄像头" value={`${cameras.length} 路`} detail="已启用指令驱动智慧安防" icon={Camera} tone="indigo" />
        <StatCard label="最近推理耗时" value={status?.latency_seconds == null ? '—' : `${status.latency_seconds.toFixed(2)} 秒`} detail="当前摄像头最近一次推理" icon={Timer} tone="amber" />
        <StatCard label="最近结果时间" value={latestResultAt ? latestResultAt.toLocaleTimeString('zh-CN', { hour12: false }) : '—'} detail={latestResultAt ? latestResultAt.toLocaleDateString('zh-CN') : '等待视觉理解结果'} icon={Clock3} tone="indigo" />
      </section>
    }>
      <div className="min-w-0 space-y-5">
        <Card className="relative gap-4 overflow-hidden rounded-2xl border-blue-200 bg-gradient-to-br from-blue-50 via-white to-indigo-50 shadow-sm dark:border-blue-900 dark:from-blue-950/60 dark:via-slate-900 dark:to-indigo-950/40">
          <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-blue-500 to-indigo-500" />
          <CardHeader className="flex flex-row items-center gap-3 p-4 pb-0 sm:p-5 sm:pb-0">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#1B3FA0] text-white shadow-sm dark:bg-blue-600"><Sparkles className="h-4 w-4" /></span>
            <div className="min-w-0">
              <CardTitle className="text-base font-bold text-[#132C72] dark:text-blue-100">最新视觉理解结果</CardTitle>
              <p className="mt-1 break-words text-xs text-slate-500 dark:text-slate-400">{cameraName}</p>
            </div>
          </CardHeader>
          <CardContent aria-live="polite" className="space-y-3 p-4 pt-0 sm:p-5 sm:pt-0">
            <p className="whitespace-pre-wrap break-words rounded-xl border border-white/80 bg-white/75 p-3 text-sm font-medium leading-7 text-slate-800 dark:border-blue-900/50 dark:bg-slate-950/40 dark:text-slate-100">{status?.latest_result || '等待视觉理解结果'}</p>
            {latestResultAt && <p className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400"><Clock3 className="h-3.5 w-3.5" />{latestResultAt.toLocaleString('zh-CN')}</p>}
          </CardContent>
        </Card>
        <VideoQuestionChat selectedCamera={selectedCamera} frameConnected={frameConnected} answer={answer} questionError={questionError} asking={asking} ask={ask} />
        <Card className="dark:border-slate-800 dark:bg-slate-900">
          <CardHeader className="p-4 pb-3 sm:p-5 sm:pb-3"><CardTitle className="text-base">事件时间线</CardTitle></CardHeader>
          <CardContent className="px-4 pb-4 sm:px-5 sm:pb-5"><div className="max-h-[32rem] space-y-4 overflow-y-auto">
            {!events.length && <p className="text-sm text-slate-500">{selectedCamera ? '暂无事件，等待视频理解结果。' : '请先选择摄像头。'}</p>}
            {events.map((event) => <article key={event.id} className="border-l-2 border-blue-200 pl-4 dark:border-blue-900">
              <div className="flex flex-wrap gap-2 text-xs text-slate-500"><time>{new Date(event.captured_at).toLocaleString('zh-CN')}</time><span>{event.kind === 'question' ? '视频问答' : event.kind === 'error' ? '处理异常' : '视觉理解'}</span></div>
              {event.question && <p className="mt-2 text-sm font-semibold">{event.question}</p>}
              <p className={`mt-2 whitespace-pre-wrap break-words text-sm leading-6 ${event.kind === 'error' ? 'text-red-600 dark:text-red-300' : ''}`}>{event.text}</p>
            </article>)}
          </div></CardContent>
        </Card>
      </div>
      <Card className="gap-0 overflow-hidden rounded-2xl py-0 dark:border-slate-800 dark:bg-slate-900">
        <CardHeader className="gap-0 border-b border-slate-100 p-3 [.border-b]:pb-3 dark:border-slate-800 sm:p-4 sm:px-5 sm:[.border-b]:pb-4">
          <CardTitle className="flex items-center justify-between gap-3 text-base">
            <span className="flex items-center gap-2"><Video className="h-4 w-4 text-blue-600" />实时画面</span>
            <span className="text-sm font-normal text-slate-500 dark:text-slate-400">{frameConnected ? '实时画面' : '等待连接'}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <MonitorCameraToolbar cameras={cameras} selectedCamera={selectedCamera} loading={loading} onSelectCamera={onSelectCamera} onRefreshCameras={onRefreshCameras} />
          <div className="relative aspect-video overflow-hidden bg-slate-950">{frameContent}</div>
          <p className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{message}</p>
          {(error || status?.error) && <p role="alert" className="mx-4 mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-300">{error || status?.error}</p>}
        </CardContent>
      </Card>
    </ResizableMonitorLayout>
  </div>
}
