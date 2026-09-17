import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Camera, Link, Unlink } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader } from '@/components/detection/DetectionConfigUi'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'
import { addCamera, removeCamera, reorderCameras, setCameraEnabled } from './api'
import type { GuardMember, GuardSite } from './types'

export function CameraMembership({ site, members, busy, onChange }: {
  site: GuardSite; members: GuardMember[]; busy: boolean; onChange: (operation: () => Promise<unknown>) => Promise<void>
}) {
  const { isAdmin } = useAuth()
  const [inventory, setInventory] = useState<AiVisionCamera[]>([])
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    getAiVisionCameras(site.department).then((response) => { if (current) setInventory(response) })
      .catch((cause) => { if (current) setError(cause instanceof Error ? cause.message : String(cause)) })
    return () => { current = false }
  }, [site.department])
  const available = inventory.filter((camera) => !members.some((member) => member.camera_id === camera.camera_id))
  const move = (index: number, offset: number) => {
    const ids = members.map((member) => member.camera_id)
    ;[ids[index], ids[index + offset]] = [ids[index + offset], ids[index]]
    void onChange(() => reorderCameras(site.id, ids))
  }
  return <Card className={DETECTION_CONFIG_CARD_CLASS}>
    <DetectionConfigCardHeader icon={Camera} tone="emerald" title={`摄像头 · ${members.length}/9`} description="从当前事业部的平台设备中绑定。成员开关只控制当前保安室的联合检测。" />
    <DetectionConfigCardContent className="space-y-4">
      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
      {isAdmin && <div className="flex flex-col gap-3 sm:flex-row">
        <Select value={selected} disabled={busy || members.length >= 9} onValueChange={setSelected}>
          <SelectTrigger className="flex-1" aria-label="平台摄像头"><SelectValue placeholder="选择已有平台摄像头" /></SelectTrigger>
          <SelectContent>{available.map((camera) => <SelectItem key={camera.camera_id} value={String(camera.camera_id)}>{camera.name}{camera.enabled ? '' : '（物理设备已停用）'}</SelectItem>)}</SelectContent>
        </Select>
        <Button disabled={busy || !selected || members.length >= 9 || !available.some((camera) => String(camera.camera_id) === selected)} onClick={() => void onChange(() => addCamera(site.id, Number(selected)))}><Link className="h-4 w-4" />绑定摄像头</Button>
      </div>}
      {!members.length && <p className="text-sm text-slate-500">尚未绑定摄像头。请先在平台摄像头管理中添加设备。</p>}
      {members.map((member, index) => <div key={member.camera_id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border p-4 dark:border-slate-800">
        <div><p className="font-semibold">{index + 1}. {member.name}</p><p className="mt-1 text-xs text-slate-500">{member.shm_name} · {member.physical_enabled ? '物理设备已启用' : '物理设备已停用'}</p></div>
        <div className="flex items-center gap-2"><Switch aria-label={`参与联合检测：${member.name}`} checked={member.member_enabled} disabled={!isAdmin || busy} onCheckedChange={(enabled) => void onChange(() => setCameraEnabled(site.id, member.camera_id, enabled))} />
          {isAdmin && <><Button size="icon" variant="outline" aria-label={`上移 ${member.name}`} disabled={busy || index === 0} onClick={() => move(index, -1)}><ArrowUp className="h-4 w-4" /></Button>
            <Button size="icon" variant="outline" aria-label={`下移 ${member.name}`} disabled={busy || index === members.length - 1} onClick={() => move(index, 1)}><ArrowDown className="h-4 w-4" /></Button>
            <Button variant="outline" disabled={busy} onClick={() => void onChange(() => removeCamera(site.id, member.camera_id))}><Unlink className="h-4 w-4" />解除绑定</Button></>}
        </div>
      </div>)}
    </DetectionConfigCardContent>
  </Card>
}
