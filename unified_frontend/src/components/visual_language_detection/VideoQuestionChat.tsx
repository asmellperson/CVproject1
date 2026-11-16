import { useEffect, useRef, useState } from 'react'
import { Bot, Loader2, MessageSquareText, Send, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { VideoAnswer } from '@/lib/visual-language-detection'

type Exchange = { question: string; answer: VideoAnswer | null; error: string }
type Props = {
  selectedCamera: string
  frameConnected: boolean
  answer: VideoAnswer | null
  questionError: string
  asking: boolean
  ask: (question: string) => Promise<void>
}

export function VideoQuestionChat({ selectedCamera, frameConnected, answer, questionError, asking, ask }: Props) {
  const [question, setQuestion] = useState('')
  const [submittedQuestion, setSubmittedQuestion] = useState('')
  const [history, setHistory] = useState<Exchange[]>([])
  const messagesRef = useRef<HTMLDivElement>(null)
  const exchanges = submittedQuestion ? [...history, { question: submittedQuestion, answer, error: questionError }] : history

  useEffect(() => {
    const messages = messagesRef.current
    if (messages) messages.scrollTop = messages.scrollHeight
  }, [submittedQuestion, answer, questionError, asking])

  return <Card className="gap-0 overflow-hidden rounded-2xl dark:border-slate-800 dark:bg-slate-900">
    <CardHeader className="border-b border-slate-100 pb-5 dark:border-slate-800">
      <CardTitle className="flex items-center gap-2 text-base"><MessageSquareText className="h-5 w-5 text-blue-600 dark:text-blue-400" />向当前视频提问</CardTitle>
    </CardHeader>
    <CardContent className="p-0">
      <div ref={messagesRef} role="log" aria-label="视频问答记录" aria-live="polite" className="h-[26rem] space-y-6 overflow-y-auto bg-slate-50/70 p-4 dark:bg-slate-950/30 sm:p-5">
        {!exchanges.length && <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
          <span className="rounded-2xl bg-blue-50 p-4 text-blue-600 dark:bg-blue-950/50 dark:text-blue-300"><MessageSquareText className="h-7 w-7" /></span>
          <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{selectedCamera ? '从当前画面开始一段对话' : '请先选择摄像头'}</p>
        </div>}
        {exchanges.map((exchange, index) => <div key={index} className="space-y-4">
          <div className="flex justify-end gap-2">
            <div className="min-w-0 max-w-[85%]">
              <p className="mb-1.5 text-right text-xs text-slate-500 dark:text-slate-400">我的提问</p>
              <p className="whitespace-pre-wrap break-words rounded-2xl rounded-tr-sm bg-[#1B3FA0] px-4 py-3 text-sm leading-6 text-white dark:bg-blue-700">{exchange.question}</p>
            </div>
            <span className="mt-5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"><UserRound className="h-4 w-4" /></span>
          </div>
          <div className="flex items-start gap-2">
            <span className="mt-5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600 dark:bg-indigo-950 dark:text-indigo-300"><Bot className="h-4 w-4" /></span>
            <div className="min-w-0 max-w-[85%]">
              <p className="mb-1.5 text-xs text-slate-500 dark:text-slate-400">模型回答</p>
              <div className="rounded-2xl rounded-tl-sm border border-slate-200/70 bg-white px-4 py-3 text-sm leading-6 text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
                {asking && index === exchanges.length - 1 ? <span className="flex items-center gap-2 text-slate-500 dark:text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />正在理解视频…</span>
                  : exchange.error ? <p role="alert" className="whitespace-pre-wrap break-words text-red-600 dark:text-red-300">{exchange.error}</p>
                    : <p className="whitespace-pre-wrap break-words">{exchange.answer?.text || '本次未产生回答，请补充问题后再试。'}</p>}
              </div>
            </div>
          </div>
        </div>)}
      </div>
      <form className="space-y-3 border-t border-slate-100 p-4 dark:border-slate-800" onSubmit={(event) => {
        event.preventDefault()
        if (!selectedCamera || !frameConnected || !question.trim() || asking) return
        // 已完成的问答仅保存在当前页面，切换摄像头时随监控组件一起清空。
        if (submittedQuestion) setHistory([...history, { question: submittedQuestion, answer, error: questionError }])
        setSubmittedQuestion(question.trim())
        setQuestion('')
        void ask(question)
      }}>
        <Label htmlFor="visual-language-question" className="sr-only">向当前视频提问</Label>
        <Textarea id="visual-language-question" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={2000} rows={3}
          className="resize-none rounded-xl bg-slate-50 dark:bg-slate-950/50" placeholder="例如：刚才这个人在做什么？" disabled={!selectedCamera || asking} />
        <div className="flex items-center justify-between gap-3">
          {(!selectedCamera || !frameConnected) && <p className="text-xs text-slate-500 dark:text-slate-400">{!selectedCamera ? '请选择摄像头' : '画面未连接'}</p>}
          <Button type="submit" className="ml-auto shrink-0 gap-2 rounded-xl" disabled={!selectedCamera || !frameConnected || !question.trim() || asking}><Send className="h-4 w-4" />{asking ? '回答中…' : '发送问题'}</Button>
        </div>
      </form>
    </CardContent>
  </Card>
}
