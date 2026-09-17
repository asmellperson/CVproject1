import { useEffect, useState } from 'react'
import { Settings2 } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionFormSection, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { getRoi, updatePolicy, updateRoi } from './api'
import { hasInvalidPolicyNumber, POLICY_GROUPS } from './policyFields'
import { VehicleRoiEditor } from './VehicleRoiEditor'
import type { GuardMember, SitePolicy, SitePolicyValues, VehicleRoiPoint } from './types'

function VehicleRoiSettings({ siteId, member }: { siteId: number; member: GuardMember }) {
  const { isAdmin } = useAuth()
  const [roi, setRoi] = useState<VehicleRoiPoint[]>([])
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
    setSaving(true)
    try { setRoi((await updateRoi(siteId, member.camera_id, roi)).vehicle_roi_pos); setMessage('ROI 已保存。') }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setSaving(false) }
  }
  return <VehicleRoiEditor cameraId={member.camera_id} cameraLabel={member.name} roi={roi}
    fallbackSize={{ width: 1920, height: 1080 }} disabled={!isAdmin || loading || !loaded || saving}
    saving={saving} message={message} onChange={setRoi} onSave={() => void save()} />
}

export function PolicySettings({ policy, members, busy, onChange }: {
  policy: SitePolicy; members: GuardMember[]; busy: boolean; onChange: (operation: () => Promise<unknown>) => Promise<void>
}) {
  const { isAdmin } = useAuth()
  const [changes, setChanges] = useState<Partial<SitePolicyValues>>({})
  const value = { ...policy, ...changes }
  const disabled = !isAdmin || busy
  const selected = members.find((member) => member.camera_id === value.vehicle_camera_id)
  const invalid = hasInvalidPolicyNumber(value) || (value.vehicle_inspection_enabled && (!selected || !selected.member_enabled))
  return <>
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Settings2} tone="violet" title="检测参数" description="策略由当前保安室共享；车辆 ROI 只作用于指定摄像头的车辆检测。" />
      <DetectionConfigCardContent className="space-y-8">
        {POLICY_GROUPS.map((group) => <DetectionFormSection key={group.title} title={group.title}>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">{group.fields.map((field) => <div key={field.key} className="space-y-3">
            <Label htmlFor={`guard-policy-${field.key}`}>{field.label}</Label>
            <Input id={`guard-policy-${field.key}`} type="number" value={Number.isFinite(value[field.key]) ? value[field.key] : ''} min={field.min} max={field.max} step={field.step} disabled={disabled}
              onChange={(event) => setChanges((previous) => ({ ...previous, [field.key]: event.target.value === '' ? NaN : Number(event.target.value) }))} />
            {field.max === 1 && <Slider aria-label={field.label} min={0} max={1} step={field.step} value={[Number.isFinite(value[field.key]) ? value[field.key] : 0]} disabled={disabled}
              onValueChange={([number]) => setChanges((previous) => ({ ...previous, [field.key]: number }))} />}
          </div>)}</div>
        </DetectionFormSection>)}
        <DetectionFormSection title="车辆检查摄像头">
          <label className="flex items-center justify-between gap-4">启用车辆出厂检查<Switch aria-label="启用车辆出厂检查" disabled={disabled} checked={value.vehicle_inspection_enabled}
            onCheckedChange={(enabled) => setChanges((previous) => ({ ...previous, vehicle_inspection_enabled: enabled, vehicle_camera_id: enabled ? value.vehicle_camera_id : null }))} /></label>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2"><Label>车辆检查摄像头</Label><Select value={value.vehicle_camera_id === null ? 'none' : String(value.vehicle_camera_id)} disabled={disabled || !value.vehicle_inspection_enabled}
              onValueChange={(id) => setChanges((previous) => ({ ...previous, vehicle_camera_id: id === 'none' ? null : Number(id) }))}>
              <SelectTrigger aria-label="车辆检查摄像头"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">请选择已启用成员</SelectItem>
                {members.map((member) => <SelectItem key={member.camera_id} value={String(member.camera_id)} disabled={!member.member_enabled}>{member.name}{member.member_enabled ? '' : '（成员已停用）'}</SelectItem>)}
              </SelectContent></Select></div>
            <div className="space-y-2"><Label>离场方向</Label><Select disabled={disabled} value={value.vehicle_exit_direction} onValueChange={(direction) => setChanges((previous) => ({ ...previous, vehicle_exit_direction: direction as SitePolicyValues['vehicle_exit_direction'] }))}>
              <SelectTrigger aria-label="离场方向"><SelectValue /></SelectTrigger><SelectContent>{(['any', 'left', 'right', 'up', 'down'] as const).map((direction, index) => <SelectItem key={direction} value={direction}>{['任意', '向左', '向右', '向上', '向下'][index]}</SelectItem>)}</SelectContent>
            </Select></div>
          </div>
          {value.vehicle_inspection_enabled && !selected && <p role="alert" className="text-sm text-amber-700">启用车辆检查前，请先绑定并选择摄像头。</p>}
          {selected && <VehicleRoiSettings key={selected.camera_id} siteId={policy.site_id} member={selected} />}
        </DetectionFormSection>
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={invalid ? '请检查参数范围及车辆摄像头选择。' : '检测策略与 ROI 分别保存。'} saving={busy} disabled={disabled || invalid || !Object.keys(changes).length}
      onSave={() => void onChange(async () => { await updatePolicy(policy.site_id, changes); setChanges({}) })} />
  </>
}
