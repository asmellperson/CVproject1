import { Bell } from 'lucide-react'
import { useState } from 'react'
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
import { normalizeFeatureAlarmConfig, type FeatureAlarmConfig } from '@/lib/alarm-config'

type AlarmPushConfigProps = {
  alarm?: FeatureAlarmConfig
  disabled?: boolean
  saving?: boolean
  message?: string

  onChange: (alarm: FeatureAlarmConfig) => void

  onSave?: () => void
}

export function AlarmPushConfig({ alarm, disabled, saving, message, onChange, onSave }: AlarmPushConfigProps) {
  const merged = normalizeFeatureAlarmConfig(alarm)
  const [hornError, setHornError] = useState<string | null>(null)

  const updateWechat = (patch: Partial<{ enable: boolean; user: string }>) => {
    onChange({
      ...merged,
      wechat: {
        enable: patch.enable ?? merged.wechat.enable,
        parm: {
          ...merged.wechat.parm,
          user: patch.user ?? merged.wechat.parm.user,
        },
      },
    })
  }

  return (
    <>
      <Card className={DETECTION_CONFIG_CARD_CLASS}>
        <DetectionConfigCardHeader
          icon={Bell}
          tone="amber"
          title="报警推送"
          description="维护当前检测配置的企业微信推送与喇叭告警。"
        />
        <DetectionConfigCardContent className="space-y-4">
          <HornAlarmBinding value={merged.horn} disabled={disabled}
            onChange={(horn) => onChange({ ...merged, horn })} onValidationChange={setHornError} />
          <label
            htmlFor="feature-wechat-enable"
            className="flex min-h-16 items-center justify-between gap-4 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-950/40"
          >
            <span>
              <span className="block font-medium text-slate-900">启用企业微信推送</span>
              <span className="block text-xs text-slate-500">开启后当前功能报警会推送到指定企业微信用户</span>
            </span>
            <Switch
              id="feature-wechat-enable"
              checked={merged.wechat.enable}
              onCheckedChange={(checked) => updateWechat({ enable: checked })}
              disabled={disabled}
            />
          </label>

          <div className={cn('space-y-2 rounded-2xl border border-[#E8ECF5] bg-white p-4 transition-opacity dark:border-slate-800 dark:bg-slate-900/80', !merged.wechat.enable && 'pointer-events-none opacity-45')}>
            <Label htmlFor="feature-wechat-user">接收报警的用户</Label>
            <Input
              id="feature-wechat-user"
              className="font-mono"
              value={merged.wechat.parm.user}
              onChange={(event) => updateWechat({ user: event.target.value })}
              placeholder="多个用户用 | 分隔，如 zhangsan|lisi"
              disabled={disabled || !merged.wechat.enable}
            />
            <p className="text-xs text-orange-700">填写企业微信成员账号；修改后点击“保存配置”生效。</p>
          </div>
        </DetectionConfigCardContent>
      </Card>
      {onSave ? <DetectionSaveBar message={message || '修改报警推送后需要保存配置才会生效。'} saving={saving} disabled={disabled || Boolean(hornError)} onSave={() => { if (!hornError) onSave() }} /> : null}
    </>
  )
}
