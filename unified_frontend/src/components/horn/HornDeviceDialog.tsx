import { useState } from 'react'
import { PlugZap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { HornConnectionInput, HornConnectionResult, HornDevice, HornWrite } from '@/lib/horns'
import { DEFAULT_HORN_SIP, hornConnectionPayload, hornDraft, hornWritePayload, validateHornDraft } from './hornDeviceForm'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'

type Props = {
  device: HornDevice | null
  department: DepartmentId
  busy: boolean
  error: string
  onClose: () => void
  onSave: (payload: HornWrite) => Promise<boolean>
  onTest: (payload: HornConnectionInput) => Promise<HornConnectionResult | undefined>
}

export function HornDeviceDialog({ device, department, busy, error, onClose, onSave, onTest }: Props) {
  const [draft, setDraft] = useState(() => hornDraft(device, department))
  const [validationError, setValidationError] = useState('')
  const [testResult, setTestResult] = useState<HornConnectionResult | undefined>()
  const [operation, setOperation] = useState<'save' | 'test' | null>(null)
  const disabled = busy || operation !== null
  const change = (patch: Partial<typeof draft>) => {
    setDraft((current) => ({ ...current, ...patch }))
    setValidationError('')
    setTestResult(undefined)
  }

  const submit = async () => {
    if (disabled) return
    const problem = validateHornDraft(draft, device !== null, false, device?.sip?.password_set)
    setValidationError(problem ?? '')
    if (problem) return
    setOperation('save')
    try {
      if (await onSave(hornWritePayload(draft))) onClose()
    } finally {
      setOperation(null)
    }
  }

  const testConnection = async () => {
    if (disabled) return
    const problem = validateHornDraft(draft, device !== null, true)
    setValidationError(problem ?? '')
    if (problem) return
    setOperation('test')
    setTestResult(undefined)
    try {
      setTestResult(await onTest(hornConnectionPayload(draft, device?.id)))
    } finally {
      setOperation(null)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !disabled) onClose() }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl" showCloseButton={!disabled}>
        <DialogHeader>
          <DialogTitle>{device ? '编辑喇叭设备' : '新增喇叭设备'}</DialogTitle>
          <DialogDescription>归属 {DEPARTMENT_LABELS[draft.department]}，供本事业部的检测配置使用。测试连接不会播放声音或保存修改。</DialogDescription>
        </DialogHeader>
        <form id="horn-device-form" className="space-y-4" onSubmit={(event) => { event.preventDefault(); void submit() }}>
          <div className="space-y-2">
            <Label htmlFor="horn-name">名称</Label>
            <Input id="horn-name" value={draft.name} maxLength={100} disabled={disabled} autoFocus
              onChange={(event) => change({ name: event.target.value })} placeholder="例如：一号厂房喇叭" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="horn-mode">播放方式</Label>
            <Select value={draft.sip ? 'sip' : 'device'} disabled={disabled}
              onValueChange={(value) => change({ sip: value === 'sip' ? { ...DEFAULT_HORN_SIP } : null })}>
              <SelectTrigger id="horn-mode" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="sip">服务器音频（SIP）</SelectItem><SelectItem value="device">设备已有音频（ISAPI）</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="horn-url">设备地址</Label>
            <Input id="horn-url" value={draft.url} maxLength={500} disabled={disabled} autoComplete="off"
              onChange={(event) => change({ url: event.target.value })} placeholder="http://192.168.1.100" />
          </div>
          {draft.sip ? <div className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <p className="text-sm font-medium text-slate-900 dark:text-slate-100">这台喇叭的 SIP 配置</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2"><Label htmlFor="horn-sip-user">SIP 账户</Label>
                <Input id="horn-sip-user" value={draft.sip.username} maxLength={64} disabled={disabled} autoComplete="off"
                  onChange={(event) => change({ sip: { ...draft.sip!, username: event.target.value } })} /></div>
              <div className="space-y-2"><Label htmlFor="horn-sip-auth">SIP 认证 ID</Label>
                <Input id="horn-sip-auth" value={draft.sip.auth_id} maxLength={64} disabled={disabled} autoComplete="off"
                  onChange={(event) => change({ sip: { ...draft.sip!, auth_id: event.target.value } })} /></div>
              <div className="space-y-2"><Label htmlFor="horn-sip-port">喇叭本地 SIP 端口</Label>
                <Input id="horn-sip-port" type="number" min={1} max={65535} value={draft.sip.port} disabled={disabled}
                  onChange={(event) => change({ sip: { ...draft.sip!, port: Number(event.target.value) } })} /></div>
              <div className="space-y-2"><Label htmlFor="horn-sip-password">SIP 注册密码</Label>
                <Input id="horn-sip-password" type="password" value={draft.sip.password ?? ''} maxLength={128} disabled={disabled} autoComplete="new-password"
                  placeholder={device?.sip?.password_set ? '留空保留已保存的 SIP 密码' : '请输入 SIP 密码'}
                  onChange={(event) => change({ sip: { ...draft.sip!, password: event.target.value } })} /></div>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">SIP 服务地址和监听端口在“喇叭配置”的 SIP 服务中统一设置。保存并启用设备后，平台自动将这些参数同步到喇叭；按设备地址和 SIP 账户定位。</p>
          </div> : null}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="horn-username">用户名</Label>
              <Input id="horn-username" value={draft.username} maxLength={100} disabled={disabled} autoComplete="off"
                onChange={(event) => change({ username: event.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="horn-password">密码{device ? '' : '（必填）'}</Label>
              <Input id="horn-password" type="password" value={draft.password} maxLength={200} disabled={disabled}
                autoComplete="new-password" aria-describedby="horn-password-hint"
                onChange={(event) => change({ password: event.target.value })}
                placeholder={device ? '留空保留原密码' : '请输入设备密码'} />
              <p id="horn-password-hint" className="text-xs text-slate-500 dark:text-slate-400">
                {device ? `${device.password_set ? '已设置密码' : '尚未设置密码'}；留空表示保留原密码。` : '请输入现场设备的密码。'}
              </p>
            </div>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800">
            <Label htmlFor="horn-enable">启用状态</Label>
            <Switch id="horn-enable" checked={draft.enable} disabled={disabled} onCheckedChange={(enable) => change({ enable })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="horn-description">备注</Label>
            <Textarea id="horn-description" value={draft.description ?? ''} maxLength={10000} rows={3} disabled={disabled}
              onChange={(event) => change({ description: event.target.value })} placeholder="设备位置或其他说明" />
          </div>
          {validationError || error ? <p role="alert" className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">{validationError || error}</p> : null}
          {testResult ? (
            <p role="status" className={`rounded-xl px-4 py-3 text-sm ${testResult.success ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200' : 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200'}`}>
              {testResult.success ? '连接成功，未播放声音。' : `连接失败：${testResult.runtime.last_error || '设备暂不可用，请检查地址和账号密码。'}`}
            </p>
          ) : null}
        </form>
        <DialogFooter className="gap-2 sm:justify-between">
          <Button type="button" variant="outline" onClick={() => void testConnection()} disabled={disabled}>
            <PlugZap className="h-4 w-4" />{operation === 'test' ? '测试中...' : '测试连接'}
          </Button>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={disabled}>取消</Button>
            <Button type="submit" form="horn-device-form" disabled={disabled}>{operation === 'save' ? '保存中...' : '保存设备'}</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
