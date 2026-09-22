import { useState, type ReactNode } from 'react'
import { MessageSquareText, RefreshCw, Video } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
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
  const [question, setQuestion] = useState('')
  return <div className="space-y-6">
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
      <CardContent className="grid gap-5 p-5 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
        <div className="space-y-3">
          <div className="relative aspect-video overflow-hidden rounded-2xl bg-slate-950">{frameContent}</div>
          <p className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
        </div>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl border bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/40"><p className="text-xs text-slate-500">最近推理耗时</p><p className="mt-2 text-2xl font-bold">{status?.latency_seconds == null ? '—' : `${status.latency_seconds.toFixed(2)} 秒`}</p></div>
            <div className="rounded-xl border bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/40"><p className="text-xs text-slate-500">累计处理帧数</p><p className="mt-2 text-2xl font-bold">{status?.processed_frames ?? 0}</p></div>
          </div>
          <div className="rounded-xl border p-4 dark:border-slate-800">
            <h3 className="font-semibold">最近视觉理解结果</h3>
            <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">{status?.latest_result || '等待视觉理解结果'}</p>
            {status?.latest_result_at && <p className="mt-3 text-xs text-slate-500">{new Date(status.latest_result_at).toLocaleString('zh-CN')}</p>}
          </div>
          {(error || status?.error) && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-300">{error || status?.error}</p>}
        </div>
      </CardContent>
    </Card>
    <div className="grid items-start gap-6 xl:grid-cols-2">
      <Card className="dark:border-slate-800 dark:bg-slate-900">
        <CardHeader><CardTitle className="flex items-center gap-2 text-lg"><MessageSquareText className="h-5 w-5 text-blue-600" />向当前视频提问</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); void ask(question) }}>
            <Label htmlFor="visual-language-question">问题</Label>
            <Textarea id="visual-language-question" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={2000} rows={4}
              placeholder="例如：刚才这个人在做什么？" disabled={!selectedCamera || asking} />
            <Button type="submit" disabled={!selectedCamera || !frameConnected || !question.trim() || asking}>{asking ? '正在理解视频…' : '发送问题'}</Button>
          </form>
          {questionError && <p role="alert" className="text-sm text-red-600 dark:text-red-300">{questionError}</p>}
          {answer && <div role="status" className="whitespace-pre-wrap break-words rounded-xl bg-blue-50 p-4 text-sm leading-6 dark:bg-blue-950/30">{answer.text || '本次未产生回答，请补充问题后再试。'}</div>}
        </CardContent>
      </Card>
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
}
