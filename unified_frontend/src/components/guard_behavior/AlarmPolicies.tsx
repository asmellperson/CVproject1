import { useState } from 'react'
import { Bell } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { WechatAlarmSettings } from '@/components/AlarmPushConfig'
import { HornAlarmBinding } from '@/components/horn/HornAlarmBinding'
import { HornDeviceManager } from '@/components/horn/HornDeviceManager'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { updateAlarmPolicy } from './api'
import type { AlarmPolicy, AlarmPolicyValues, GuardAlarmType } from './types'

const LABELS: Record<GuardAlarmType, string> = { 8: '离岗', 9: '手机使用', 10: '趴睡', 11: '车辆出厂检查异常' }

function AlarmPolicyCard({ policy, busy, onChange }: { policy: AlarmPolicy; busy: boolean; onChange: (operation: () => Promise<unknown>) => Promise<void> }) {
  const { isAdmin } = useAuth()
  const [changes, setChanges] = useState<Partial<AlarmPolicyValues>>({})
  const [hornError, setHornError] = useState<string | null>(null)
  const value = { ...policy, ...changes }
  const disabled = !isAdmin || busy
  return <section>
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Bell} tone="amber" title={LABELS[policy.violation_type]} description="此类报警独立设置间隔及推送方式。" />
      <DetectionConfigCardContent className="space-y-4">
        <div className="space-y-2"><Label htmlFor={`guard-alarm-${policy.violation_type}`}>报警间隔（秒）</Label><Input id={`guard-alarm-${policy.violation_type}`} type="number" min={.1} step={.1} disabled={disabled} value={value.alarm_interval}
          onChange={(event) => setChanges((previous) => ({ ...previous, alarm_interval: Number(event.target.value) }))} /></div>
        <label className="flex items-center justify-between rounded-xl border p-4 dark:border-slate-800">写入报警记录（SQL）<Switch aria-label={`${LABELS[policy.violation_type]}写入报警记录`} checked={value.sql_enable} disabled={disabled} onCheckedChange={(sql_enable) => setChanges((previous) => ({ ...previous, sql_enable }))} /></label>
        <WechatAlarmSettings disabled={disabled} value={{ enable: value.wechat_enable, parm: { user: value.wechat_user } }}
          onChange={(wechat) => setChanges((previous) => ({ ...previous, wechat_enable: wechat.enable, wechat_user: wechat.parm.user }))} />
        <HornAlarmBinding disabled={disabled} value={{ enable: value.horn_enable, parm: { horn_id: value.horn_id, horn_event_id: value.horn_event_id } }}
          onValidationChange={setHornError} onChange={(horn) => setChanges((previous) => ({ ...previous, horn_enable: horn.enable, horn_id: horn.parm.horn_id == null ? null : Number(horn.parm.horn_id), horn_event_id: horn.parm.horn_event_id == null ? null : Number(horn.parm.horn_event_id) }))} />
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={hornError || '仅保存当前报警类型的策略。'} saving={busy} disabled={disabled || !!hornError || value.alarm_interval <= 0 || !Number.isFinite(value.alarm_interval) || !Object.keys(changes).length}
      onSave={() => void onChange(async () => { await updateAlarmPolicy(policy.site_id, policy.violation_type, changes); setChanges({}) })} />
  </section>
}

export function AlarmPolicies({ policies, busy, onChange }: { policies: AlarmPolicy[]; busy: boolean; onChange: (operation: () => Promise<unknown>) => Promise<void> }) {
  const { isAdmin } = useAuth()
  return <div className="space-y-5">
    <div className="grid items-start gap-5 xl:grid-cols-2">{policies.map((policy) => <AlarmPolicyCard key={policy.violation_type} policy={policy} busy={busy} onChange={onChange} />)}</div>
    {isAdmin && <details className="rounded-2xl border bg-white p-5 dark:border-slate-800 dark:bg-slate-900"><summary className="cursor-pointer font-semibold">喇叭设备管理</summary><div className="mt-4"><HornDeviceManager /></div></details>}
  </div>
}
