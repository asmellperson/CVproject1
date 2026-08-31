// 文件说明：实现告警、配置的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { Bell } from 'lucide-react'
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
  /**
   * 功能：处理 `onChange` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `alarm`（FeatureAlarmConfig）：`alarm` 对应的业务输入值
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onChange: (alarm: FeatureAlarmConfig) => void
  /**
   * 功能：更新或保存 `onSave` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onSave?: () => void
}

/**
 * 功能：渲染 `AlarmPushConfig` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（AlarmPushConfigProps）：React 组件属性对象；解构字段包括 alarm, disabled, saving, message, onChange, onSave
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`normalizeFeatureAlarmConfig`、`onChange`、`return`、`updateWechat`、`cn`、`Card`、`DetectionConfigCardHeader`、`DetectionConfigCardContent`、`Switch`、`Label`
 *          等共 12 个调用。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
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
    <>
      <Card className={DETECTION_CONFIG_CARD_CLASS}>
        <DetectionConfigCardHeader
          icon={Bell}
          tone="amber"
          title="报警推送"
          description="维护报警总开关及企业微信接收成员，原有提交格式保持不变。"
        />
        <DetectionConfigCardContent className="space-y-4">
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
      {onSave ? <DetectionSaveBar message={message || '修改报警推送后需要保存配置才会生效。'} saving={saving} disabled={disabled} onSave={onSave} /> : null}
    </>
  )
}
