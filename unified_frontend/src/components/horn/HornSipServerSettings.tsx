import { Radio } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useHornSipSettings } from './useHornSipSettings'

export function HornSipServerSettings() {
  const state = useHornSipSettings()
  const { draft, server } = state
  return <div className="space-y-4 rounded-xl border border-[#E8ECF5] bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-slate-100"><Radio className="h-4 w-4 text-violet-500" />平台 SIP 服务</h3>
      <Badge variant="outline">{server?.running ? '正在监听' : server?.enabled ? '未启动' : '已停用'}</Badge>
    </div>
    {draft ? <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void state.save() }}>
      <label className="flex items-center justify-between gap-4 text-sm"><span>启用平台 SIP 服务</span>
        <Switch checked={draft.enabled} disabled={state.saving} onCheckedChange={(enabled) => state.setDraft({ ...draft, enabled })} /></label>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="sip-server-address">服务器局域网 IP</Label>
          <Input id="sip-server-address" value={draft.address} disabled={state.saving} placeholder="填写实际运行后端的服务器 IP"
            onChange={(event) => state.setDraft({ ...draft, address: event.target.value })} /></div>
        <div className="space-y-2"><Label htmlFor="sip-server-port">SIP 监听端口（UDP）</Label>
          <Input id="sip-server-port" type="number" min={1024} max={65535} value={draft.port} disabled={state.saving}
            onChange={(event) => state.setDraft({ ...draft, port: Number(event.target.value) })} /></div>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400">所有喇叭共用这项服务。地址填写本机可被喇叭访问的 IP；此端口用于 SIP，项目网页和 HTTP API 端口保持各自配置。服务器与喇叭之间需要允许 UDP 控制和音频通信。</p>
      <div className="flex justify-end"><Button type="submit" disabled={state.saving}>{state.saving ? '保存中...' : '保存 SIP 服务'}</Button></div>
    </form> : <p role="status" className="text-sm text-slate-500">正在读取 SIP 服务配置...</p>}
    {state.error || server?.last_error ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{state.error || server?.last_error}</p> : null}
    {state.message ? <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">{state.message}</p> : null}
  </div>
}
