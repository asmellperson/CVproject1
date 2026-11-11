import { useEffect, useState } from 'react'
import { MousePointer2 } from 'lucide-react'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { getRoi, updateRoi } from './api'
import { VehicleRoiEditor } from './VehicleRoiEditor'
import type { GuardMember, VehicleRoiPoint } from './types'

export function VehicleRoiSettings({ siteId, member, busy }: { siteId: number; member: GuardMember; busy: boolean }) {
  const canConfigure = useDepartmentConfigAccess(undefined, 'guard_behavior')
  const [roi, setRoi] = useState<VehicleRoiPoint[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [message, setMessage] = useState('正在读取 ROI…')
  useEffect(() => {
    const controller = new AbortController()
    getRoi(siteId, member.camera_id, controller.signal).then((value) => {
      if (!controller.signal.aborted) { setRoi(value.vehicle_roi_pos); setLoaded(true); setMessage('空 ROI 表示全画面；支持拖动矩形、点击多边形和拖动顶点。') }
    }).catch((error) => { if (!controller.signal.aborted) setMessage(String(error)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [siteId, member.camera_id])
  const save = async () => {
    if (!canConfigure || !loaded || saving || busy) return
    setSaving(true)
    try { setRoi((await updateRoi(siteId, member.camera_id, roi)).vehicle_roi_pos); setMessage('ROI 已保存。') }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setSaving(false) }
  }
  return <div className="rounded-xl border border-amber-100 bg-amber-50/40 p-4 dark:border-amber-900/50 dark:bg-amber-950/20 md:col-span-2">
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="min-w-0"><p className="text-sm font-semibold text-slate-800 dark:text-slate-100">车辆检测 ROI</p>
        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{member.name} · {loading ? '正在读取…' : !loaded ? message : roi.length ? `已绘制 ${roi.length} 个顶点` : '全画面检测'}</p>
      </div>
      <Dialog open={open} onOpenChange={(next) => { if (!saving) setOpen(next) }}>
        <DialogTrigger asChild><Button variant="outline" className="gap-2 bg-white dark:bg-slate-900" disabled={loading || !loaded || busy}><MousePointer2 className="h-4 w-4" />{canConfigure ? '绘制车辆 ROI' : '查看车辆 ROI'}</Button></DialogTrigger>
        <DialogContent className="max-h-[92dvh] max-w-[calc(100vw-1.5rem)] overflow-y-auto sm:max-w-6xl">
          <DialogHeader><DialogTitle>绘制车辆检测 ROI</DialogTitle><DialogDescription>使用 {member.name} 的单路画面绘制车辆检测区域，点击保存后生效。</DialogDescription></DialogHeader>
          <VehicleRoiEditor cameraId={member.camera_id} cameraLabel={member.name} roi={roi} fallbackSize={{ width: 1920, height: 1080 }}
            disabled={!canConfigure || loading || !loaded || saving || busy} saving={saving} message={message} onChange={setRoi} onSave={() => void save()} />
        </DialogContent>
      </Dialog>
    </div>
  </div>
}
