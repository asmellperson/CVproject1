import { Bell, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
    <Card className="border-slate-200 bg-white/95">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <Bell className="h-5 w-5 text-orange-600" />
          报警推送
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <label
          htmlFor="feature-wechat-enable"
          className="flex min-h-11 items-center justify-between gap-4 rounded-md border border-input bg-background px-3 text-sm"
        >
          <span>
            <span className="block font-medium text-slate-900">启用企业微信推送</span>
            <span className="block text-xs text-slate-500">开启后当前功能报警会推送到指定企业微信用户</span>
          </span>
          <input
            id="feature-wechat-enable"
            type="checkbox"
            checked={merged.wechat.enable}
            onChange={(event) => updateWechat({ enable: event.target.checked })}
            disabled={disabled}
            className="h-4 w-4 accent-slate-900"
          />
        </label>

        {merged.wechat.enable ? (
          <div className="space-y-2 rounded-lg border border-orange-100 bg-orange-50 p-4">
            <Label htmlFor="feature-wechat-user">接收报警的用户</Label>
            <Input
              id="feature-wechat-user"
              value={merged.wechat.parm.user}
              onChange={(event) => updateWechat({ user: event.target.value })}
              placeholder="多个用户用 | 分隔，如 zhangsan|lisi"
              disabled={disabled}
            />
            <p className="text-xs text-orange-700">填写企业微信成员账号；修改后点击“保存配置”生效。</p>
          </div>
        ) : null}

        {onSave ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="text-sm text-slate-600">{message || '修改报警推送后需要保存配置才会生效。'}</div>
            <Button className="gap-2" onClick={onSave} disabled={disabled || saving}>
              <Save className="h-4 w-4" />
              {saving ? '保存中' : '保存配置'}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
