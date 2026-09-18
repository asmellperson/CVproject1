import { useCallback, useState } from 'react'
import { Bell } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { WechatAlarmSettings } from '@/components/AlarmPushConfig'
import { HornAlarmBinding } from '@/components/horn/HornAlarmBinding'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { updateAlarmPolicy } from './api'
import type { AlarmPolicy, AlarmPolicyValues, GuardAlarmType } from './types'

const LABELS: Record<GuardAlarmType, string> = { 8: '离岗', 9: '手机使用', 10: '趴睡', 11: '车辆出厂检查异常' }
type Changes = Partial<Record<GuardAlarmType, Partial<AlarmPolicyValues>>>

function AlarmPolicyFields({ policy, disabled, onChange, onValidation }: {
  policy: AlarmPolicy; disabled: boolean
  onChange: (type: GuardAlarmType, changes: Partial<AlarmPolicyValues>) => void
  onValidation: (type: GuardAlarmType, error: string | null) => void
}) {
  const reportValidation = useCallback((error: string | null) => onValidation(policy.violation_type, error), [onValidation, policy.violation_type])
  const change = (value: Partial<AlarmPolicyValues>) => onChange(policy.violation_type, value)
  return <section className="space-y-5 rounded-2xl border border-amber-100 bg-white p-4 dark:border-amber-900/50 dark:bg-slate-900 sm:p-5">
    <div className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-500 text-white shadow-sm"><Bell className="h-4 w-4" /></span><h3 className="text-base font-bold text-amber-800 dark:text-amber-300">{LABELS[policy.violation_type]}</h3></div>
    <div className="grid items-start gap-5 md:grid-cols-2">
      <div className="space-y-2"><Label htmlFor={`guard-alarm-${policy.violation_type}`}>重复报警间隔（秒）</Label><Input id={`guard-alarm-${policy.violation_type}`} type="number" min={.1} step="any" disabled={disabled} value={Number.isFinite(policy.alarm_interval) ? policy.alarm_interval : ''}
        onChange={(event) => change({ alarm_interval: event.target.value === '' ? NaN : Number(event.target.value) })} /><p className="text-xs text-slate-500 dark:text-slate-400">同类报警再次推送前至少等待的时间。</p></div>
      <label className="flex min-h-16 items-center justify-between gap-4 rounded-xl bg-slate-50 p-4 dark:bg-slate-950/40"><span><span className="block text-sm font-medium">写入报警记录</span><span className="text-xs text-slate-500">保存到报警记录，便于后续查看。</span></span><Switch aria-label={`${LABELS[policy.violation_type]}写入报警记录`} checked={policy.sql_enable} disabled={disabled} onCheckedChange={(sql_enable) => change({ sql_enable })} /></label>
    </div>
    <div className="space-y-4 rounded-xl border border-orange-100 bg-orange-50/50 p-4 dark:border-orange-900/50 dark:bg-orange-950/20">
      <WechatAlarmSettings disabled={disabled} value={{ enable: policy.wechat_enable, parm: { user: policy.wechat_user } }}
        onChange={(wechat) => change({ wechat_enable: wechat.enable, wechat_user: wechat.parm.user })} />
    </div>
    <HornAlarmBinding disabled={disabled} value={{ enable: policy.horn_enable, parm: { horn_id: policy.horn_id, horn_event_id: policy.horn_event_id } }}
      onValidationChange={reportValidation} onChange={(horn) => change({ horn_enable: horn.enable, horn_id: horn.parm.horn_id == null ? null : Number(horn.parm.horn_id), horn_event_id: horn.parm.horn_event_id == null ? null : Number(horn.parm.horn_event_id) })} />
  </section>
}

export function AlarmPolicies({ policies, busy, onChange }: { policies: AlarmPolicy[]; busy: boolean; onChange: (operation: () => Promise<unknown>) => Promise<void> }) {
  const { isAdmin } = useAuth()
  const [changes, setChanges] = useState<Changes>({})
  const [errors, setErrors] = useState<Partial<Record<GuardAlarmType, string | null>>>({})
  const onValidation = useCallback((type: GuardAlarmType, error: string | null) => {
    setErrors((previous) => previous[type] === error ? previous : { ...previous, [type]: error })
  }, [])
  const values = policies.map((policy) => ({ ...policy, ...changes[policy.violation_type] }))
  const pending = values.filter((policy) => Object.keys(changes[policy.violation_type] ?? {}).length)
  const invalid = pending.some((policy) => !Number.isFinite(policy.alarm_interval) || policy.alarm_interval <= 0 || errors[policy.violation_type])
  const save = async () => {
    if (!isAdmin || busy || invalid || !pending.length) return
    await onChange(async () => {
      let saved = 0
      try {
        for (const policy of pending) {
          await updateAlarmPolicy(policy.site_id, policy.violation_type, changes[policy.violation_type]!)
          saved += 1
        }
        setChanges({})
      } catch (cause) {
        const reason = cause instanceof Error ? cause.message : String(cause)
        throw new Error(`已保存 ${saved}/${pending.length} 类报警配置，草稿已保留，请重试。${reason}`)
      }
    })
  }
  return <>
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Bell} tone="amber" title="企业微信报警推送" description="配置报警消息的接收用户与推送方式，四类报警分别生效。喇叭设备在“喇叭配置”中管理。" />
      <DetectionConfigCardContent className="space-y-6">
        {values.map((policy) => <AlarmPolicyFields key={policy.violation_type} policy={policy} disabled={!isAdmin || busy} onValidation={onValidation}
          onChange={(type, value) => setChanges((previous) => ({ ...previous, [type]: { ...previous[type], ...value } }))} />)}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={invalid ? '请检查报警间隔及喇叭设备绑定。' : '修改后保存配置；各类报警的接收人、间隔和推送开关独立生效。'} saving={busy} disabled={!isAdmin || busy || !pending.length || invalid} onSave={() => void save()} />
  </>
}
