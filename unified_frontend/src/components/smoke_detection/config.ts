import { normalizeFeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'

export const SMOKE_FEATURE = 'smoke_detection'

export const CONNECTION_FIELDS = [
  ['device_port', '设备 HTTP/HTTPS 端口', 1, 65535],
  ['event_channel_id', '报警事件通道', 1, 65535],
  ['thermal_channel_id', '设备参数通道', 1, 65535],
] as const
type ConnectionField = typeof CONNECTION_FIELDS[number][0]

export type SmokeConfig = {
  enable: boolean
  value: Record<ConnectionField, number> & {
    device_scheme: 'http' | 'https'
    alarm_interval: number
  }
  alarm: NormalizedFeatureAlarmConfig
}

export type SmokeDraft = {
  config: SmokeConfig
  numbers: Record<ConnectionField | 'alarm_interval', string>
}

export function createSmokeDraft(config: SmokeConfig): SmokeDraft {
  return {
    config: { ...config, alarm: normalizeFeatureAlarmConfig(config.alarm, config.value.alarm_interval) },
    numbers: {
      device_port: String(config.value.device_port),
      event_channel_id: String(config.value.event_channel_id),
      thermal_channel_id: String(config.value.thermal_channel_id),
      alarm_interval: String(config.value.alarm_interval),
    },
  }
}

export function buildSmokeConfig(draft: SmokeDraft): SmokeConfig {
  const value = { ...draft.config.value }
  for (const [field, label, min, max] of CONNECTION_FIELDS) {
    const parsed = Number(draft.numbers[field])
    if (!draft.numbers[field].trim() || !Number.isInteger(parsed) || parsed < min || parsed > max) {
      throw new Error(`${label}必须是 ${min}～${max} 的整数`)
    }
    value[field] = parsed
  }
  const interval = Number(draft.numbers.alarm_interval)
  if (!draft.numbers.alarm_interval.trim() || !Number.isFinite(interval) || interval <= 0) {
    throw new Error('报警记录间隔必须大于零')
  }
  value.alarm_interval = interval
  return { ...draft.config, value }
}
