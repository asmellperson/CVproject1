import { useEffect, useId } from 'react'
import { Volume2 } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { HORN_STATE_LABELS } from './hornDeviceForm'
import { MAX_HORN_ID, validateHornBinding, type HornBinding } from '@/lib/horn-alarm-binding'
import { useHornCatalog } from './useHornCatalog'
import { useHornAudioCatalog } from './useHornAudioCatalog'
import { HornPlaybackControl } from './HornPlaybackControl'

type Props = {
  value: HornBinding
  disabled?: boolean
  onChange: (value: HornBinding) => void
  onValidationChange: (error: string | null) => void
}

export function HornAlarmBinding({ value, disabled, onChange, onValidationChange }: Props) {
  const { isAdmin } = useAuth()
  const fieldId = useId()
  const { devices, error: loadError } = useHornCatalog(isAdmin)
  const audio = useHornAudioCatalog(isAdmin)
  const selectedId = value.parm.horn_id
  const selected = devices?.find((device) => device.id === selectedId)
  const validation = validateHornBinding(value, isAdmin ? (loadError ? null : devices) : undefined,
    isAdmin ? (audio.loadError ? null : audio.files) : undefined)
  const readOnly = disabled || !isAdmin
  const warning = validation || (selected && !selected.enable ? '已绑定设备已停用，原绑定已保留；关闭喇叭告警后可保存。' : '')
  const state = selected ? (!selected.enable ? 'disabled' : selected.runtime.state) : null

  useEffect(() => { onValidationChange(validation) }, [validation, onValidationChange])

  return <div className="space-y-4 rounded-2xl border border-[#E8ECF5] bg-white p-4 dark:border-slate-800 dark:bg-slate-900/80">
    <label htmlFor={`${fieldId}-enable`} className="flex min-h-12 items-center justify-between gap-4">
      <span>
        <span className="flex items-center gap-2 text-sm font-medium text-slate-900 dark:text-slate-100"><Volume2 className="h-4 w-4 text-violet-500" />启用喇叭告警</span>
        <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">仅控制当前检测配置；关闭后保留设备和语音任务。</span>
      </span>
      <Switch id={`${fieldId}-enable`} checked={value.enable} disabled={readOnly}
        onCheckedChange={(enable) => onChange({ ...value, enable })} />
    </label>
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <Label htmlFor={`${fieldId}-device`}>喇叭设备</Label>
        <Select value={selectedId == null ? 'none' : String(selectedId)} disabled={readOnly}
          onValueChange={(id) => {
            if (id !== 'none' && !devices?.some((device) => device.id === Number(id) && device.enable)) return
            onChange({ ...value, parm: { ...value.parm, horn_id: id === 'none' ? null : Number(id), horn_event_id: null } })
          }}>
          <SelectTrigger id={`${fieldId}-device`} className="w-full"><SelectValue placeholder="请选择已启用的设备" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">未选择（清除设备绑定）</SelectItem>
            {selectedId != null && !selected ? <SelectItem value={String(selectedId)} disabled>设备 #{String(selectedId)}（{isAdmin && devices && !loadError ? '不存在' : '状态待确认'}）</SelectItem> : null}
            {devices?.filter((device) => device.enable || device.id === selectedId).map((device) =>
              <SelectItem key={device.id} value={String(device.id)} disabled={!device.enable}>
                {device.name}（{HORN_STATE_LABELS[device.enable ? device.runtime.state : 'disabled']}）
              </SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${fieldId}-task`}>{selected?.sip ? '报警音频' : '设备音频 ID'}</Label>
        {selected?.sip ? <Select value={value.parm.horn_event_id == null ? 'none' : String(value.parm.horn_event_id)} disabled={readOnly}
          onValueChange={(id) => onChange({ ...value, parm: { ...value.parm, horn_event_id: id === 'none' ? null : Number(id) } })}>
          <SelectTrigger id={`${fieldId}-task`} className="w-full"><SelectValue placeholder="请选择已上传的 AAC 音频" /></SelectTrigger>
          <SelectContent><SelectItem value="none">未选择音频</SelectItem>
            {value.parm.horn_event_id != null && !audio.files?.some((file) => file.id === value.parm.horn_event_id)
              ? <SelectItem value={String(value.parm.horn_event_id)} disabled>音频 #{String(value.parm.horn_event_id)}（待确认）</SelectItem> : null}
            {audio.files?.map((file) => <SelectItem key={file.id} value={String(file.id)}>{file.name}（{file.duration.toFixed(1)} 秒）</SelectItem>)}
          </SelectContent>
        </Select> : <Input id={`${fieldId}-task`} type="number" min={1} max={MAX_HORN_ID} step={1}
          value={value.parm.horn_event_id == null ? '' : String(value.parm.horn_event_id)} disabled={readOnly}
          onChange={(event) => onChange({ ...value, parm: { ...value.parm,
            horn_event_id: event.target.value === '' ? null : Number(event.target.value),
          } })} placeholder="填写设备素材库中的音频文件 ID" />}
      </div>
    </div>
    {value.interval !== undefined ? <div className="space-y-2">
      <Label htmlFor={`${fieldId}-interval`}>喇叭报警间隔（秒）</Label>
      <Input id={`${fieldId}-interval`} type="number" min={0} step="any" disabled={readOnly}
        value={value.interval != null && Number.isFinite(value.interval) ? value.interval : ''}
        onChange={(event) => onChange({ ...value, interval: event.target.value === '' ? NaN : Number(event.target.value) })} />
      <p className="text-xs text-slate-500 dark:text-slate-400">0 秒表示不额外等待；同台喇叭串行播放，避免声音重叠。设备内置音频仍受设备播放保护间隔限制。</p>
    </div> : null}
    {state ? <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">设备状态
      <Badge variant="outline" className={state === 'online'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200'
        : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200'}>{HORN_STATE_LABELS[state]}</Badge>
      {selected?.enable && state !== 'online' ? <span>设备当前未在线；告警能否播放取决于设备连接恢复情况。</span> : null}
    </div> : null}
    {!isAdmin ? <p className="text-xs text-slate-500 dark:text-slate-400">设备列表与实时状态仅管理员可查询，当前显示已保存的绑定。</p>
      : loadError ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{loadError}</p>
        : devices === null ? <p role="status" className="text-xs text-slate-500">正在读取喇叭设备...</p>
          : !devices.some((device) => device.enable) ? <p className="text-xs text-slate-500 dark:text-slate-400">暂无已启用设备，请在“喇叭设备”中添加并启用。</p> : null}
    {warning ? <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">{warning}</p> : null}
    {selected && isAdmin ? <HornPlaybackControl device={selected}
      audioId={typeof value.parm.horn_event_id === 'number' ? value.parm.horn_event_id : null}
      duration={audio.files?.find((file) => file.id === value.parm.horn_event_id)?.duration} disabled={readOnly || Boolean(validation)} /> : null}
    <p className="text-xs text-slate-500 dark:text-slate-400">{selected?.sip
      ? '在“喇叭设备”的音频库上传 AAC 后选择报警音频，异常检测会由服务器通过 SIP 发送给所选喇叭。'
      : '设备已有音频使用素材库中的文件 ID。'}修改后保存当前检测配置生效；试播会实际播放声音。</p>
  </div>
}
