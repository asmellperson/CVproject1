import type { FeatureAlarmConfig } from '@/lib/alarm-config'
import type { HornDevice } from '@/lib/horns'

export type HornBinding = NonNullable<FeatureAlarmConfig['horn']>
export const MAX_HORN_ID = 2147483647

export function validateHornBinding(binding: HornBinding, devices?: HornDevice[] | null): string | null {
  const { horn_id: id, horn_event_id: task } = binding.parm
  if (binding.enable && (id == null || task == null)) return '启用喇叭告警时必须选择设备并填写语音任务 ID。'
  for (const [label, value] of [['喇叭设备 ID', id], ['语音任务 ID', task]] as const) {
    if (value != null && (typeof value !== 'number' || !Number.isInteger(value) || value <= 0 || value > MAX_HORN_ID)) {
      return `${label} 必须是 1 到 ${MAX_HORN_ID} 之间的整数。`
    }
  }
  if (id == null || devices === undefined) return null
  if (devices === null) return '设备列表尚未读取成功，暂时无法确认喇叭绑定。'
  const device = devices.find((item) => item.id === id)
  if (!device) return `已绑定的喇叭设备 #${id} 不存在，请重新选择或清除绑定。`
  if (binding.enable && !device.enable) return '已绑定的喇叭设备已停用，请选择已启用设备或关闭喇叭告警。'
  return null
}
