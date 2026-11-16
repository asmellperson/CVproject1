import { Bell } from 'lucide-react'
import { useId, useState } from 'react'
import { HornAlarmBinding } from '@/components/horn/HornAlarmBinding'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  DETECTION_CONFIG_CARD_CLASS,
  DetectionConfigCardContent,
  DetectionConfigCardHeader,
  DetectionSaveBar,
} from '@/components/detection/DetectionConfigUi'
import { cn } from '@/lib/utils'
import { normalizeFeatureAlarmConfig, type FeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'

type AlarmPushConfigProps = {
  showSql?: boolean
  alarmInterval?: string
  onAlarmIntervalChange?: (value: string) => void
  alarm?: FeatureAlarmConfig
  disabled?: boolean
  saving?: boolean
  message?: string

  onChange: (alarm: FeatureAlarmConfig) => void

  onSave?: () => void
}

export function WechatAlarmSettings({ value, disabled, onChange }: {
  value: NormalizedFeatureAlarmConfig['wechat']
  disabled?: boolean
  onChange: (value: NormalizedFeatureAlarmConfig['wechat']) => void
}) {
  const fieldId = useId()
  return (
    <>
      <label
        htmlFor={`${fieldId}-wechat-enable`}
        className="flex min-h-16 items-center justify-between gap-4 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-950/40"
      >
        <span>
          <span className="block font-medium text-slate-900">启用企业微信推送</span>
        </span>
        <Switch
          id={`${fieldId}-wechat-enable`}
          checked={value.enable}
          onCheckedChange={(enable) => onChange({ ...value, enable })}
          disabled={disabled}
        />
      </label>

      <div className={cn('space-y-2 rounded-2xl border border-[#E8ECF5] bg-white p-4 transition-opacity dark:border-slate-800 dark:bg-slate-900/80', !value.enable && 'pointer-events-none opacity-45')}>
        <Label htmlFor={`${fieldId}-wechat-interval`}>企业微信推送间隔（秒）</Label>
        <Input id={`${fieldId}-wechat-interval`} type="number" min={0} step="any"
          value={Number.isFinite(value.interval) ? value.interval : ''} disabled={disabled || !value.enable}
          onChange={(event) => onChange({ ...value, interval: event.target.value === '' ? NaN : Number(event.target.value) })} />
        <Label htmlFor={`${fieldId}-wechat-user`}>企业微信成员账号</Label>
        <Input
          id={`${fieldId}-wechat-user`}
          className="font-mono"
          value={value.parm.user}
          onChange={(event) => onChange({ ...value, parm: { ...value.parm, user: event.target.value } })}
          placeholder="多个用户用 | 分隔，如 zhangsan|lisi"
          disabled={disabled || !value.enable}
        />
      </div>
    </>
  )
}

export function AlarmPushConfig({ alarm, showSql, alarmInterval, onAlarmIntervalChange, disabled, saving, message, onChange, onSave }: AlarmPushConfigProps) {
  const merged = normalizeFeatureAlarmConfig(alarm, alarmInterval === undefined ? undefined : Number(alarmInterval))
  const [hornError, setHornError] = useState<string | null>(null)
  const intervalId = useId()
  const intervalError = !Number.isFinite(merged.wechat.interval) || merged.wechat.interval < 0
    ? '企业微信推送间隔必须是非负秒数。' : null

  return (
    <>
      <Card className={DETECTION_CONFIG_CARD_CLASS}>
        <DetectionConfigCardHeader
          icon={Bell}
          tone="amber"
          title="报警推送"
        />
        <DetectionConfigCardContent className="space-y-4">
          {alarmInterval !== undefined && onAlarmIntervalChange ? <div className="space-y-2">
            <Label htmlFor={intervalId}>报警记录间隔（秒）</Label>
            <Input id={intervalId} type="number" min={0.1} step={0.1} value={alarmInterval}
              disabled={disabled} onChange={(event) => onAlarmIntervalChange(event.target.value)} />
          </div> : null}
          {showSql ? <label className="flex items-center justify-between gap-4 rounded-xl border p-4 dark:border-slate-800">
            <span>写入报警记录</span>
            <Switch checked={merged.sql.enable} disabled={disabled} aria-label="写入报警记录"
              onCheckedChange={(enable) => onChange({ ...merged, sql: { ...merged.sql, enable } })} />
          </label> : null}
          <HornAlarmBinding value={merged.horn} disabled={disabled}
            onChange={(horn) => onChange({ ...merged, horn })} onValidationChange={setHornError} />
          <WechatAlarmSettings value={merged.wechat} disabled={disabled}
            onChange={(wechat) => onChange({ ...merged, wechat })} />
          {intervalError ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{intervalError}</p> : null}
        </DetectionConfigCardContent>
      </Card>
      {onSave ? <DetectionSaveBar message={message} saving={saving} disabled={disabled || Boolean(hornError || intervalError)} onSave={() => { if (!hornError && !intervalError) onSave() }} /> : null}
    </>
  )
}
