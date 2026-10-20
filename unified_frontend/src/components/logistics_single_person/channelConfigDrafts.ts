import type { LogisticsChannelConfig, LogisticsChannelDetectionConfig, LogisticsChannelAlarmDraft } from './types'

export function splitChannelConfig({ alarm, alarm_interval, alarm_schedule, ...detection }: LogisticsChannelConfig): {
  detection: LogisticsChannelDetectionConfig
  alarm: LogisticsChannelAlarmDraft
} {
  return { detection, alarm: { alarm, alarm_interval, alarm_schedule } }
}
