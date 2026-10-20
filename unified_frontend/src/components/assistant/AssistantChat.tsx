import { useEffect, useRef, useState } from 'react'
import { Bot, Loader2, MessageSquareText, Plus, Send, Square, UserRound } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { AssistantActionCard } from './AssistantActionCard'
import { useAssistant } from './useAssistant'
import { isTurnActive } from './types'

export function AssistantChat({ department, isAdmin }: { department: DepartmentId | null; isAdmin: boolean }) {
  const state = useAssistant(department)
  const [draft, setDraft] = useState('')
  const messages = useRef<HTMLDivElement>(null)
  const turns = state.conversation?.turns ?? []
  const contentSignature = turns.map((turn) => `${turn.id}:${turn.status}:${turn.actions.length}:${turn.answer.length}`).join('|')
  useEffect(() => { if (messages.current) messages.current.scrollTop = messages.current.scrollHeight }, [contentSignature])

  return <div className="grid grid-cols-1 gap-5 xl:grid-cols-[240px_minmax(0,1fr)]">
    <Card className="min-w-0 gap-0 self-start dark:border-slate-800 dark:bg-slate-900"><CardHeader className="pb-4"><CardTitle className="text-base">我的对话</CardTitle></CardHeader>
      <CardContent className="space-y-3"><Button variant="outline" className="w-full gap-2" disabled={state.loading || state.sending} onClick={() => void state.newSession()}><Plus className="h-4 w-4" />新建对话</Button>
        <div className="max-h-80 space-y-1 overflow-y-auto" aria-label="历史对话">
          {state.sessions.map((session) => <button key={session.id} disabled={state.sending} onClick={() => { setDraft(''); state.selectSession(session.id) }}
            className={`w-full rounded-lg px-3 py-2 text-left text-sm ${state.sessionId === session.id ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300' : 'text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
            <span className="block truncate">{session.title}</span><span className="mt-1 block text-xs opacity-60">{new Date(session.updated_at).toLocaleString('zh-CN')}</span>
          </button>)}
          {!state.sessions.length && <p className="py-3 text-xs text-slate-400">{state.loading ? '正在读取对话…' : '发送消息即可开始对话'}</p>}
        </div>
      </CardContent>
    </Card>
    <Card className="min-w-0 gap-0 overflow-hidden rounded-2xl dark:border-slate-800 dark:bg-slate-900">
      <CardHeader className="border-b border-slate-100 pb-5 dark:border-slate-800"><CardTitle className="flex items-center gap-2 text-base"><MessageSquareText className="h-5 w-5 text-blue-600 dark:text-blue-400" />平台助手</CardTitle><p className="text-xs text-slate-500 dark:text-slate-400">{isAdmin ? '用自然语言查询和修改配置，操作结果保留记录。' : '当前账号可查询已授权部门配置，修改需要管理员权限。'}</p></CardHeader>
      <CardContent className="p-0">
        <div ref={messages} role="log" aria-label="平台助手对话" aria-live="polite" className="h-[min(58vh,38rem)] min-h-80 space-y-6 overflow-y-auto bg-slate-50/70 p-4 dark:bg-slate-950/30 sm:p-5">
          {!turns.length && <div className="flex h-full flex-col items-center justify-center gap-3 text-center"><Bot className="h-9 w-9 text-blue-600 dark:text-blue-400" /><p className="text-sm font-medium">告诉我你想处理什么</p><p className="max-w-md text-xs leading-6 text-slate-500 dark:text-slate-400">例如：把二厂物流出口摄像头重命名为“物流出口东侧”，FPS 改成 8。<br />也可以查询参数、调整检测阈值，或设置物流通道周末不报警。</p></div>}
          {!!state.conversation?.hidden_turns && <p className="text-center text-xs text-amber-700 dark:text-amber-400">部分历史记录因账号权限变化已隐藏。</p>}
          {turns.map((turn) => <div key={turn.id} className="space-y-4">
            <div className="flex justify-end gap-2"><p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-tr-sm bg-[#1B3FA0] px-4 py-3 text-sm leading-6 text-white dark:bg-blue-700">{turn.question}</p><UserRound className="mt-2 h-6 w-6 shrink-0 text-blue-600 dark:text-blue-400" /></div>
            <div className="flex items-start gap-2"><Bot className="mt-2 h-6 w-6 shrink-0 text-indigo-500" /><div className="min-w-0 flex-1 space-y-3 rounded-2xl rounded-tl-sm border border-slate-200/70 bg-white p-4 text-sm leading-6 text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {turn.actions.map((action) => <AssistantActionCard key={action.id} action={action} />)}
              {isTurnActive(turn) ? <p className="flex items-center gap-2 text-slate-500 dark:text-slate-400"><Loader2 className="h-4 w-4 shrink-0 animate-spin" />{turn.progress || '正在处理…'}</p>
                : <p className={`whitespace-pre-wrap break-words ${turn.status === 'failed' || turn.status === 'interrupted' ? 'text-amber-700 dark:text-amber-400' : ''}`}>{turn.answer}</p>}
            </div></div>
          </div>)}
        </div>
        <form className="space-y-3 border-t border-slate-100 p-4 dark:border-slate-800" onSubmit={(event) => { event.preventDefault(); void state.send(draft).then((sent) => { if (sent) setDraft('') }) }}>
          {state.error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{state.error}</p>}
          <Label htmlFor="assistant-message" className="sr-only">给平台助手的指令</Label>
          <Textarea id="assistant-message" value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={4000} rows={3} disabled={state.sending || !!state.activeTurn || state.loading} placeholder="请写明部门、摄像头或通道，以及希望修改的内容…" className="resize-none rounded-xl bg-slate-50 dark:bg-slate-950/50" />
          <div className="flex items-center justify-between gap-3"><p className="text-xs leading-5 text-slate-500 dark:text-slate-400">账号、密码请注明字段名；连接信息仅暂存服务器内存，引用闲置 30 分钟失效。</p>
            {state.activeTurn ? <Button type="button" variant="outline" className="shrink-0 gap-2" onClick={() => void state.cancel()}><Square className="h-4 w-4" />停止任务</Button>
              : <Button type="submit" className="shrink-0 gap-2 rounded-xl" disabled={!draft.trim() || state.sending || state.loading}><Send className="h-4 w-4" />{state.sending ? '发送中…' : '发送指令'}</Button>}
          </div>
        </form>
      </CardContent>
    </Card>
  </div>
}
