import { Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { HornDevice } from '@/lib/horns'
import { useHornDeletion } from './useHornDeletion'

const RESOURCE_LABELS = { camera: '摄像头', logistics_channel: '物流通道', guard_site: '保安室' }

export function HornDeleteDialog({ device, onClose, onDeleted }: {
  device: HornDevice; onClose: () => void; onDeleted: () => void
}) {
  const state = useHornDeletion(device, onDeleted)
  const references = state.usage?.references ?? []
  const mustDisable = Boolean(state.usage?.device_enabled && references.length > 0)
  return <Dialog open onOpenChange={(open) => { if (!open && !state.busy) onClose() }}>
    <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-2xl" showCloseButton={!state.busy}>
      <DialogHeader>
        <DialogTitle>删除喇叭“{device.name}”</DialogTitle>
        <DialogDescription>先核对设备引用；停用设备或关闭告警会保留原绑定。</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 space-y-4 overflow-y-auto">
        {state.loading ? <p role="status" className="py-6 text-center text-sm text-slate-500">正在查找所有检测配置中的引用...</p>
          : state.usage ? references.length ? <>
            <p className="text-sm text-slate-600 dark:text-slate-300">共 {references.length} 处绑定，包含已关闭的告警和已停用的检测。</p>
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 px-4 dark:divide-slate-800 dark:border-slate-700">
              {references.map((item) => <li key={item.key} className="space-y-2 py-3">
                <p className="text-xs text-slate-500 dark:text-slate-400">{item.department_label} · {item.feature_label}{item.alarm_label ? ` · ${item.alarm_label}` : ''}</p>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="break-all text-sm font-medium text-slate-900 dark:text-slate-100">{RESOURCE_LABELS[item.kind]}：{item.resource_name}</span>
                  <span className="flex flex-wrap gap-1"><Badge variant="outline">{item.horn_enabled ? '喇叭告警已开启' : '喇叭告警已关闭'}</Badge>
                    {!item.detection_enabled ? <Badge variant="secondary">检测已停用</Badge> : null}</span>
                </div>
              </li>)}
            </ul>
            <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
              {mustDisable ? '设备仍启用，请先关闭设备开关，再返回这里删除。'
                : '确认后将关闭以上配置的喇叭告警，清除设备与音频绑定，并删除此设备。检测参数、企业微信和报警记录会保留。'}
            </p>
          </> : <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-950/40 dark:text-slate-300">该设备没有检测配置引用，可以直接删除。</p> : null}
        {state.error ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{state.error}</p> : null}
      </div>
      <DialogFooter className="gap-2">
        <Button variant="outline" onClick={onClose} disabled={state.busy}>取消</Button>
        {state.error ? <Button variant="outline" onClick={state.reload} disabled={state.busy || state.loading}>重新读取引用</Button> : null}
        <Button variant="destructive" onClick={() => { void state.remove() }} disabled={state.busy || state.loading || !state.usage || mustDisable}>
          <Trash2 className="h-4 w-4" />{state.busy ? '删除中...' : references.length ? '解除绑定并删除' : '删除设备'}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
