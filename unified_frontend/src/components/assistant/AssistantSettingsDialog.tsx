import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getAssistantSettings, saveAssistantSettings } from './api'
import type { AssistantModelSettings } from './types'

export function AssistantSettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [draft, setDraft] = useState<AssistantModelSettings | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('正在读取设置…')
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void getAssistantSettings(controller.signal).then((value) => {
      if (!controller.signal.aborted) { setDraft(value); setMessage('保存后对后续任务生效。') }
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setMessage(reason instanceof Error ? reason.message : '读取失败') })
    return () => controller.abort()
  }, [open])
  return <Dialog open={open} onOpenChange={(value) => { if (!busy) onOpenChange(value) }}><DialogContent>
    <DialogHeader><DialogTitle>福达AI助手设置</DialogTitle><DialogDescription>未独立保存时使用安检的模型连接。普通聊天直接回复，配置操作由工具校验执行。</DialogDescription></DialogHeader>
    <form className="space-y-4" onSubmit={(event) => {
      event.preventDefault()
      if (!draft || busy) return
      setBusy(true)
      void saveAssistantSettings(draft).then(() => { setMessage('模型设置已保存。') }).catch((reason: unknown) => setMessage(reason instanceof Error ? reason.message : '保存失败')).finally(() => setBusy(false))
    }}>
      {draft && <>
        <div className="space-y-2"><Label htmlFor="assistant-base">模型服务地址</Label><Input id="assistant-base" value={draft.base_url} disabled={busy} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} required /></div>
        <div className="space-y-2"><Label htmlFor="assistant-model">模型名称</Label><Input id="assistant-model" value={draft.model} disabled={busy} onChange={(event) => setDraft({ ...draft, model: event.target.value })} required /></div>
        <div className="grid grid-cols-3 gap-3">{([
          ['max_tokens', '输出 Token', 128, 16384, 1], ['temperature', '采样温度', 0, 2, 0.1], ['api_timeout_sec', '请求超时（秒）', 1, 180, 1],
        ] as const).map(([key, label, min, max, step]) => <div className="space-y-2" key={key}><Label htmlFor={`assistant-${key}`}>{label}</Label><Input id={`assistant-${key}`} type="number" min={min} max={max} step={step} value={draft[key]} disabled={busy} required onChange={(event) => setDraft({ ...draft, [key]: Number(event.target.value) })} /></div>)}</div>
      </>}
      <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
      <DialogFooter><Button type="submit" disabled={busy || !draft}>{busy ? '保存中…' : '保存设置'}</Button></DialogFooter>
    </form>
  </DialogContent></Dialog>
}
