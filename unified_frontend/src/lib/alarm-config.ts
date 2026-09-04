export type FeatureAlarmConfig = {
  horn?: { enable: boolean; parm: Record<string, unknown> }
  sql?: { enable: boolean; parm: Record<string, unknown> }
  wechat?: { enable: boolean; parm: { user?: string } }
}

export type NormalizedFeatureAlarmConfig = {
  horn: { enable: boolean; parm: Record<string, unknown> }
  sql: { enable: boolean; parm: Record<string, unknown> }
  wechat: { enable: boolean; parm: { user: string } }
}

const defaultAlarm: NormalizedFeatureAlarmConfig = {
  horn: { enable: false, parm: {} },
  sql: { enable: false, parm: {} },
  wechat: { enable: false, parm: { user: '' } },
}

export function normalizeFeatureAlarmConfig(alarm?: FeatureAlarmConfig): NormalizedFeatureAlarmConfig {
  return {
    horn: alarm?.horn || defaultAlarm.horn,
    sql: alarm?.sql || defaultAlarm.sql,
    wechat: {
      enable: alarm?.wechat?.enable ?? defaultAlarm.wechat.enable,
      parm: {
        user: alarm?.wechat?.parm?.user || '',
      },
    },
  }
}
