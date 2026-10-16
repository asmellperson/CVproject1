import type { FeatureAlarmConfig } from '@/lib/alarm-config'
import type { HornDevice, HornAudio } from '@/lib/horns'

export type HornBinding = NonNullable<FeatureAlarmConfig['horn']>
export const MAX_HORN_ID = 2147483647

export function validateHornBinding(binding: HornBinding, devices?: HornDevice[] | null, audio?: HornAudio[] | null): string | null {
  const { horn_id: id, horn_event_id: task } = binding.parm
  if (binding.enable && (id == null || task == null)) return '启用喇叭告警时必须选择设备和报警音频。'
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
  if (binding.enable && device.sip && audio !== undefined) {
    if (audio === null) return '音频库尚未读取成功，暂时无法确认音频绑定。'
    if (!audio.some((item) => item.id === task)) return '已绑定的服务器音频不存在，请重新上传或选择。'
  }
  return null
}
