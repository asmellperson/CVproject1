import { normalizeFeatureAlarmConfig, type FeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
import type { LogisticsChannelAlarmConfig } from './types'

export function toFeatureAlarm(alarm: LogisticsChannelAlarmConfig): NormalizedFeatureAlarmConfig {
  return {
    sql: { enable: alarm.sql_enable, parm: {} },
    horn: { enable: alarm.horn.enabled, parm: { horn_id: alarm.horn.horn_id, horn_event_id: alarm.horn.horn_event_id } },
    wechat: { enable: alarm.wechat.enabled, parm: { user: alarm.wechat.user } },
  }
}

export function toLogisticsAlarm(alarm: FeatureAlarmConfig): LogisticsChannelAlarmConfig {
  const normalized = normalizeFeatureAlarmConfig(alarm)
  return {
    sql_enable: normalized.sql.enable,
    horn: { enabled: normalized.horn.enable,
      horn_id: (normalized.horn.parm.horn_id as number | null) ?? null,
      horn_event_id: (normalized.horn.parm.horn_event_id as number | null) ?? null },
    wechat: { enabled: normalized.wechat.enable, user: normalized.wechat.parm.user },
  }
}
