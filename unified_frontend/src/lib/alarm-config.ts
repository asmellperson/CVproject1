export type FeatureAlarmConfig = {
  horn?: { enable: boolean; interval?: number | null; parm: Record<string, unknown> }
  sql?: { enable: boolean; parm: Record<string, unknown> }
  wechat?: { enable: boolean; interval?: number | null; parm: { user?: string } }
}

export type NormalizedFeatureAlarmConfig = {
  horn: { enable: boolean; interval: number; parm: Record<string, unknown> }
  sql: { enable: boolean; parm: Record<string, unknown> }
  wechat: { enable: boolean; interval: number; parm: { user: string } }
}

const defaultAlarm: NormalizedFeatureAlarmConfig = {
  horn: { enable: false, interval: 5, parm: {} },
  sql: { enable: false, parm: {} },
  wechat: { enable: false, interval: 5, parm: { user: '' } },
}

export function normalizeFeatureAlarmConfig(alarm?: FeatureAlarmConfig, fallbackInterval = 5): NormalizedFeatureAlarmConfig {
  return {
    horn: { ...(alarm?.horn || defaultAlarm.horn), interval: alarm?.horn?.interval ?? fallbackInterval },
    sql: alarm?.sql || defaultAlarm.sql,
    wechat: {
      enable: alarm?.wechat?.enable ?? defaultAlarm.wechat.enable,
      interval: alarm?.wechat?.interval ?? fallbackInterval,
      parm: {
        user: alarm?.wechat?.parm?.user || '',
      },
    },
  }
}
