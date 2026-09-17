import type { LogisticsChannelConfig, LogisticsChannelDetectionConfig, LogisticsChannelAlarmDraft } from './types'

export function splitChannelConfig({ alarm, alarm_interval, ...detection }: LogisticsChannelConfig): {
  detection: LogisticsChannelDetectionConfig
  alarm: LogisticsChannelAlarmDraft
} {
  return { detection, alarm: { alarm, alarm_interval } }
}
