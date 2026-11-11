import { useState } from 'react'
import { Building2, Plus, Trash2 } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { createSite, deleteSite, updateSite } from './api'
import type { GuardSite } from './types'

export function SiteSettings({ site, department, onChanged }: {
  site: GuardSite | null; department: DepartmentId; onChanged: (preferredId?: number) => Promise<void>
}) {
  const canConfigure = useDepartmentConfigAccess(department, 'guard_behavior')
  const [name, setName] = useState(site?.name ?? '')
  const [enabled, setEnabled] = useState(site?.enabled ?? true)
  const [sortOrder, setSortOrder] = useState(site?.sort_order ?? 0)
  const [newName, setNewName] = useState('')
  const [dialog, setDialog] = useState<'create' | 'delete' | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('摄像头通过平台设备绑定，保安室只维护名称、启用状态和排序。')
  const save = async (operation: 'create' | 'update' | 'delete') => {
    if (!canConfigure || saving) return
    setSaving(true)
    try {
      let preferredId: number | undefined
      if (operation === 'create') preferredId = (await createSite({ name: newName.trim(), department })).id
      else if (site && operation === 'delete') { await deleteSite(site.id); preferredId = undefined }
      else if (site) await updateSite(site.id, { name: name.trim(), enabled, sort_order: sortOrder })
      setDialog(null)
      setNewName('')
      setMessage('保安室配置已保存。')
      await onChanged(preferredId)
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setSaving(false) }
  }
  return <>
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Building2} tone="blue" title="保安室管理" actions={canConfigure && <>
        <Button disabled={saving} onClick={() => setDialog('create')}><Plus className="h-4 w-4" />新建保安室</Button>
        <Button variant="outline" disabled={!site || saving} onClick={() => setDialog('delete')}><Trash2 className="h-4 w-4" />删除保安室</Button>
      </>} />
      <DetectionConfigCardContent>
        {site ? <div className="grid gap-5 sm:grid-cols-2">
          <div className="space-y-2"><Label htmlFor="guard-site-name">名称</Label><Input id="guard-site-name" value={name} maxLength={100} disabled={!canConfigure || saving} onChange={(event) => setName(event.target.value)} /></div>
          <div className="space-y-2"><Label htmlFor="guard-site-order">排序（从小到大）</Label><Input id="guard-site-order" type="number" min={0} step={1} value={sortOrder} disabled={!canConfigure || saving} onChange={(event) => setSortOrder(Number(event.target.value))} /></div>
          <label className="flex items-center justify-between gap-4">启用当前保安室<Switch aria-label="启用当前保安室" checked={enabled} disabled={!canConfigure || saving} onCheckedChange={setEnabled} /></label>
        </div> : <p className="text-sm text-slate-500">当前事业部尚无保安室{canConfigure ? '，请先新建。' : '，请联系管理员配置。'}</p>}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={message} saving={saving} disabled={!canConfigure || !site || !name.trim() || !Number.isInteger(sortOrder) || sortOrder < 0} onSave={() => void save('update')} />
    <Dialog open={dialog !== null} onOpenChange={(open) => { if (!open && !saving) setDialog(null) }}>
      <DialogContent><DialogHeader><DialogTitle>{dialog === 'create' ? '新建保安室' : '删除保安室'}</DialogTitle>
        <DialogDescription>{dialog === 'create' ? '在当前事业部创建保安室，创建后可绑定平台摄像头。' : `删除“${site?.name}”及其策略和成员绑定，物理摄像头与 ROI 配置会保留。`}</DialogDescription></DialogHeader>
        {dialog === 'create' && <Input aria-label="新保安室名称" placeholder="保安室名称" maxLength={100} value={newName} disabled={saving} onChange={(event) => setNewName(event.target.value)} />}
        <p role="status" className="text-sm text-slate-500">{message}</p>
        <DialogFooter><Button variant="outline" disabled={saving} onClick={() => setDialog(null)}>取消</Button><Button disabled={saving || (dialog === 'create' && !newName.trim())} variant={dialog === 'delete' ? 'destructive' : 'default'} onClick={() => void save(dialog === 'create' ? 'create' : 'delete')}>{saving ? '处理中' : '确认'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}
