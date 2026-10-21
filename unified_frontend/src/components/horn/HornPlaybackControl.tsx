import { useId, useState } from 'react'
import { Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { HornAudio, HornDevice } from '@/lib/horns'
import { useHornPlayback } from './useHornPlayback'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

export function HornPlaybackControl({ device, audioId, duration, disabled }: {
  device: HornDevice; audioId: number | null; duration?: number; disabled?: boolean
}) {
  const state = useHornPlayback(device.id, audioId, device.department ?? 'unassigned')
  return <div className="space-y-2">
    <Button type="button" size="sm" variant="outline" disabled={disabled || !device.enable || !audioId || state.busy}
      onClick={() => { void state.play(duration) }}>
      <Play className="h-4 w-4" />{state.busy ? '正在试播...' : '试播音频'}
    </Button>
    {state.error || state.result ? <p role={state.error || !state.result?.success ? 'alert' : 'status'} className={`text-xs ${state.error || !state.result?.success ? 'text-rose-600 dark:text-rose-300' : 'text-emerald-700 dark:text-emerald-300'}`}>
      {state.error || state.result?.message}
    </p> : null}
  </div>
}

export function HornDevicePlayback({ device, files, disabled }: { device: HornDevice; files: HornAudio[]; disabled?: boolean }) {
  const fieldId = useId()
  const [selection, setSelection] = useState<number | null>(null)
  const audioId = device.sip ? (selection ?? files[0]?.id ?? null) : selection
  const selected = files.find((file) => file.id === audioId)
  return <div className="space-y-3 border-t border-slate-100 pt-3 dark:border-slate-800">
    <div className="space-y-2">
      <Label htmlFor={fieldId}>{device.sip ? '试播服务器音频' : '试播设备音频 ID'}</Label>
      {device.sip ? <Select value={selected ? String(selected.id) : 'none'} disabled={disabled}
        onValueChange={(id) => setSelection(id === 'none' ? null : Number(id))}>
        <SelectTrigger id={fieldId} className="w-full"><SelectValue placeholder="请选择音频" /></SelectTrigger>
        <SelectContent><SelectItem value="none">请选择音频</SelectItem>{files.map((file) => <SelectItem key={file.id} value={String(file.id)}>{file.name}（{file.duration.toFixed(1)} 秒）</SelectItem>)}</SelectContent>
      </Select> : <Input id={fieldId} type="number" min={1} max={2147483647} value={selection ?? ''} disabled={disabled}
        onChange={(event) => setSelection(event.target.value ? Number(event.target.value) : null)} placeholder="设备素材库的音频 ID" />}
    </div>
    <HornPlaybackControl device={device} audioId={device.sip && !selected ? null : audioId} duration={selected?.duration} disabled={disabled} />
    <p className="text-xs text-slate-500 dark:text-slate-400">点击会让“{device.name}”实际播放一遍，用于现场确认声音内容。</p>
  </div>
}

export function HornPlaybackDialog({ device, files, error, onClose }: {
  device: HornDevice; files: HornAudio[] | null; error: string; onClose: () => void
}) {
  return <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
    <DialogContent className="sm:max-w-lg">
      <DialogHeader><DialogTitle>试播 · {device.name}</DialogTitle>
        <DialogDescription>选择音频后播放到这台喇叭，用于现场核对声音内容{device.sip ? `和已保存的响度（${device.sip.volume_percent}%${device.sip.volume_percent === 0 ? '，静音' : ''}）` : ''}。</DialogDescription></DialogHeader>
      {error ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{error}</p> : null}
      {device.sip && files === null && !error ? <p role="status" className="text-sm text-slate-500">正在读取音频库...</p> : null}
      <HornDevicePlayback device={device} files={files ?? []} disabled={Boolean(error) || Boolean(device.sip && files === null)} />
    </DialogContent>
  </Dialog>
}
