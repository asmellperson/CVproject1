import { useState } from 'react'
import { Car, Moon, Settings2, Shield, Smartphone, UserRound } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { updatePolicy } from './api'
import { hasInvalidPolicyNumber, POLICY_GROUPS } from './policyFields'
import { PolicyAdvancedFields, PolicyRuleGroup, PolicySliderField } from './PolicyControls'
import { VehicleRoiSettings } from './VehicleRoiSettings'
import type { GuardMember, SitePolicy, SitePolicyValues } from './types'

const GROUP_ICONS = [UserRound, Smartphone, Moon, Car, Settings2]

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
      <DetectionConfigCardHeader icon={Shield} tone="violet" title="检测参数" description="调整离岗、手机使用、趴睡和车辆检查规则；报警间隔在报警推送中设置。" />
      <DetectionConfigCardContent className="space-y-6">
        {POLICY_GROUPS.map((group, index) => {
          const renderField = (field: typeof group.fields[number]) => <PolicySliderField key={field.key} field={field} value={value[field.key]} tone={group.tone} disabled={disabled}
            onChange={(number) => setChanges((previous) => ({ ...previous, [field.key]: number }))} />
          return <PolicyRuleGroup key={group.title} title={group.title} tone={group.tone} icon={GROUP_ICONS[index]}>
            {group.title === '车辆出厂检查' && <>
              <label className="flex items-center justify-between gap-4 rounded-xl bg-slate-50 p-4 dark:bg-slate-950/40 md:col-span-2"><span className="text-sm font-medium">启用车辆出厂检查</span><Switch aria-label="启用车辆出厂检查" disabled={disabled} checked={value.vehicle_inspection_enabled}
                onCheckedChange={(enabled) => setChanges((previous) => ({ ...previous, vehicle_inspection_enabled: enabled, vehicle_camera_id: enabled ? value.vehicle_camera_id : null }))} /></label>
              <div className="space-y-2"><Label>车辆检查摄像头</Label><Select value={value.vehicle_camera_id === null ? 'none' : String(value.vehicle_camera_id)} disabled={disabled || !value.vehicle_inspection_enabled}
                onValueChange={(id) => setChanges((previous) => ({ ...previous, vehicle_camera_id: id === 'none' ? null : Number(id) }))}>
                <SelectTrigger aria-label="车辆检查摄像头"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">请选择已启用成员</SelectItem>
                  {members.map((member) => <SelectItem key={member.camera_id} value={String(member.camera_id)} disabled={!member.member_enabled}>{member.name}{member.member_enabled ? '' : '（成员已停用）'}</SelectItem>)}
                </SelectContent></Select></div>
              <div className="space-y-2"><Label>离场方向</Label><Select disabled={disabled} value={value.vehicle_exit_direction} onValueChange={(direction) => setChanges((previous) => ({ ...previous, vehicle_exit_direction: direction as SitePolicyValues['vehicle_exit_direction'] }))}>
                <SelectTrigger aria-label="离场方向"><SelectValue /></SelectTrigger><SelectContent>{(['any', 'left', 'right', 'up', 'down'] as const).map((direction, index) => <SelectItem key={direction} value={direction}>{['任意', '向左', '向右', '向上', '向下'][index]}</SelectItem>)}</SelectContent>
              </Select></div>
              {value.vehicle_inspection_enabled && (!selected || !selected.member_enabled) && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300 md:col-span-2">启用车辆检查前，请先绑定并选择已启用的摄像头。</p>}
            </>}
            {group.fields.filter((field) => !field.advanced).map(renderField)}
            {group.title === '车辆出厂检查' && selected && <VehicleRoiSettings key={selected.camera_id} siteId={policy.site_id} member={selected} busy={busy} />}
            {group.fields.some((field) => field.advanced) && <PolicyAdvancedFields tone={group.tone}>{group.fields.filter((field) => field.advanced).map(renderField)}</PolicyAdvancedFields>}
          </PolicyRuleGroup>
        })}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={invalid ? '请检查参数范围及车辆摄像头选择。' : '检测策略与 ROI 分别保存。'} saving={busy} disabled={disabled || invalid || !Object.keys(changes).length}
      onSave={() => void onChange(async () => { await updatePolicy(policy.site_id, changes); setChanges({}) })} />
  </>
}
