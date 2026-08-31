// 文件说明：实现告警、配置相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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

/**
 * 功能：转换或规范化 `normalizeFeatureAlarmConfig` 对应的告警、配置逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarm?`（FeatureAlarmConfig）：`alarm` 对应的业务输入值
 * 返回：NormalizedFeatureAlarmConfig；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AlarmPushConfig.tsx` 的 `AlarmPushConfig`
 *         调用本符号；`unified_frontend/src/sections/DoorDetectionSection.tsx` 的 `DoorDetectionSection`
 *         调用本符号；`unified_frontend/src/sections/FaceDetectionSection.tsx` 的 `FaceDetectionSection`
 *         调用本符号；`unified_frontend/src/sections/IntrusionDetectionSection.tsx` 的 `IntrusionDetectionSection` 调用本符号；另有 2 处静态调用
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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
