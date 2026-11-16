import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Camera, Link, Unlink } from 'lucide-react'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { CameraZoomButton } from '@/components/camera/CameraZoomButton'
import { CameraSelectContent } from '@/components/camera/CameraSelectContent'
import { Select, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader } from '@/components/detection/DetectionConfigUi'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'
import { addCamera, removeCamera, reorderCameras, setCameraEnabled } from './api'
import type { GuardMember, GuardSite } from './types'

export function CameraMembership({ site, members, busy, onChange }: {
  site: GuardSite; members: GuardMember[]; busy: boolean; onChange: (operation: () => Promise<unknown>) => Promise<void>
}) {
  const canConfigure = useDepartmentConfigAccess(site.department, 'guard_behavior')
  const [inventory, setInventory] = useState<AiVisionCamera[]>([])
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    getAiVisionCameras(site.department).then((response) => { if (current) setInventory(response) })
      .catch((cause) => { if (current) setError(cause instanceof Error ? cause.message : String(cause)) })
    return () => { current = false }
  }, [site.department])
  const enabledMembers = members.filter((member) => member.member_enabled)
  const available = inventory.filter((camera) => camera.department === site.department && !enabledMembers.some((member) => member.camera_id === camera.camera_id)
    && (members.length < 9 || members.some((member) => member.camera_id === camera.camera_id)))
  const cameraToAdd = available.find((camera) => String(camera.camera_id) === selected)
  const addSelected = () => {
    if (!cameraToAdd) return
    void onChange(async () => {
      if (members.some((member) => member.camera_id === cameraToAdd.camera_id)) {
        await setCameraEnabled(site.id, cameraToAdd.camera_id, true)
      } else {
        await addCamera(site.id, cameraToAdd.camera_id)
      }
      setSelected('')
    })
  }
  const move = (index: number, offset: number) => {
    const ids = members.map((member) => member.camera_id)
    const from = members.indexOf(enabledMembers[index])
    const to = members.indexOf(enabledMembers[index + offset])
    ;[ids[from], ids[to]] = [ids[to], ids[from]]
    void onChange(() => reorderCameras(site.id, ids))
  }
  return <Card className={DETECTION_CONFIG_CARD_CLASS}>
    <DetectionConfigCardHeader icon={Camera} tone="emerald" title={`摄像头 · 已启用 ${enabledMembers.length} 路`} />
    <DetectionConfigCardContent className="space-y-4">
      {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
      {canConfigure && <div className="flex flex-col gap-3 sm:flex-row">
        <Select value={cameraToAdd ? selected : ''} disabled={busy || !available.length} onValueChange={setSelected}>
          <SelectTrigger className="flex-1" aria-label="添加已有摄像头"><SelectValue placeholder="选择已有摄像头加入当前保安室" /></SelectTrigger>
          <CameraSelectContent>{available.map((camera) => <SelectItem key={camera.camera_id} value={String(camera.camera_id)}>{camera.name}{camera.enabled ? '' : '（物理设备已停用）'}</SelectItem>)}</CameraSelectContent>
        </Select>
        <Button disabled={busy || !cameraToAdd} onClick={addSelected}><Link className="h-4 w-4" />添加到当前功能</Button>
      </div>}
      {!enabledMembers.length && <p className="text-sm text-slate-500">暂无已启用摄像头</p>}
      {members.length >= 9 && <p className="text-sm text-slate-500">已达到 9 路摄像头绑定上限。</p>}
      {enabledMembers.map((member, index) => <div key={member.camera_id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border p-4 dark:border-slate-800">
        <div><p className="font-semibold">{index + 1}. {member.name}</p><p className="mt-1 text-xs text-slate-500">{member.shm_name} · {member.physical_enabled ? '物理设备已启用' : '物理设备已停用'}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <CameraZoomButton camera={{ shm_name: member.shm_name, name: member.name, department: site.department, enabled: member.physical_enabled }} feature="guard_behavior" disabled={!canConfigure || busy} />
          <Button variant="outline" aria-label={`停用 ${member.name}`} disabled={!canConfigure || busy} onClick={() => void onChange(() => setCameraEnabled(site.id, member.camera_id, false))}>停用</Button>
          {canConfigure && <><Button size="icon" variant="outline" aria-label={`上移 ${member.name}`} disabled={busy || index === 0} onClick={() => move(index, -1)}><ArrowUp className="h-4 w-4" /></Button>
            <Button size="icon" variant="outline" aria-label={`下移 ${member.name}`} disabled={busy || index === enabledMembers.length - 1} onClick={() => move(index, 1)}><ArrowDown className="h-4 w-4" /></Button>
            <Button variant="outline" disabled={busy} onClick={() => void onChange(() => removeCamera(site.id, member.camera_id))}><Unlink className="h-4 w-4" />解除绑定</Button></>}
        </div>
      </div>)}
    </DetectionConfigCardContent>
  </Card>
}
