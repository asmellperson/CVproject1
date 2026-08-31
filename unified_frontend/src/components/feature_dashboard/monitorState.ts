// 文件说明：实现监控展示、状态管理的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { AlarmEvent } from '@/lib/api'

export type FeatureDashboardKey = 'blocks' | 'detect_face' | 'detect_phone' | 'detect_door'

export type FeatureDashboardProfile = {
  pageTitle: string
  pageSubtitle: string
  videoTitle: string
  metricLabel: string
  eventLabel: string
  overlayLabel: string
  statusSubject: string
}

export const FEATURE_DASHBOARD_PROFILES: Record<FeatureDashboardKey, FeatureDashboardProfile> = {
  blocks: {
    pageTitle: '区域入侵检测监控与配置',
    pageSubtitle: '警戒区域实时监控面板',
    videoTitle: '区域入侵检测监控',
    metricLabel: '警戒方向',
    eventLabel: '入侵告警',
    overlayLabel: 'alarm_line',
    statusSubject: '警戒线',
  },
  detect_face: {
    pageTitle: '人脸检测监控与配置',
    pageSubtitle: '人脸识别实时监控面板',
    videoTitle: '人脸检测监控',
    metricLabel: '人脸置信度阈值',
    eventLabel: '人脸告警',
    overlayLabel: 'face_roi',
    statusSubject: '人脸区域',
  },
  detect_phone: {
    pageTitle: '手机识别检测监控与配置',
    pageSubtitle: '手机使用识别监控面板',
    videoTitle: '手机识别检测监控',
    metricLabel: '确认持续时间',
    eventLabel: '手机告警',
    overlayLabel: 'phone_roi',
    statusSubject: '手机区域',
  },
  detect_door: {
    pageTitle: '大门开关检测监控与配置',
    pageSubtitle: '大门状态异常监控面板',
    videoTitle: '大门开关检测监控',
    metricLabel: '首次告警时间',
    eventLabel: '大门告警',
    overlayLabel: 'door_roi',
    statusSubject: '大门区域',
  },
}

/**
 * 功能：检查或判断 `isFeatureDashboardKey` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（string）：待转换、校验或写入的值
 * 返回：value is FeatureDashboardKey；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`hasOwn`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function isFeatureDashboardKey(value: string): value is FeatureDashboardKey {
  return Object.hasOwn(FEATURE_DASHBOARD_PROFILES, value)
}

export type CameraFeatureValueState = {
  cameraKey: string
  value: Record<string, unknown>
}

/**
 * 功能：计算或解析 `resolveCameraFeatureValue` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `state`（CameraFeatureValueState | null）：`state` 对应的业务输入值
 *   - `selectedCamera`（string）：`selectedCamera` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function resolveCameraFeatureValue(
  state: CameraFeatureValueState | null,
  selectedCamera: string,
) {
  return state?.cameraKey === selectedCamera ? state.value : null
}

/**
 * 功能：检查或判断 `isFeatureOverlayConfigured` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（FeatureDashboardKey）：`feature` 对应的业务输入值
 *   - `roiCount`（number）：`roiCount` 对应的数量或大小
 *   - `alarmLineCount`（number）：`alarmLineCount` 对应的数量或大小
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/feature_dashboard/FeatureDashboardMonitorView.tsx` 的 `FeatureDashboardMonitorView` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function isFeatureOverlayConfigured(
  feature: FeatureDashboardKey,
  roiCount: number,
  alarmLineCount: number,
) {
  return feature === 'blocks' ? alarmLineCount > 0 : roiCount > 0
}

/**
 * 功能：检查或判断 `isSameLocalDay` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（string | undefined）：待转换、校验或写入的值
 *   - `now`（Date）：`now` 对应的业务输入值
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Date`、`isNaN`、`getTime`、`getFullYear`、`getMonth`、`getDate`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function isSameLocalDay(value: string | undefined, now: Date) {
  if (!value) return false
  const parsed = new Date(value)
  return !Number.isNaN(parsed.getTime())
    && parsed.getFullYear() === now.getFullYear()
    && parsed.getMonth() === now.getMonth()
    && parsed.getDate() === now.getDate()
}

/**
 * 功能：创建或构建 `buildFeatureAlarmSummary` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarms`（AlarmEvent[]）：`alarms` 对应的业务输入值
 *   - `feature`（FeatureDashboardKey）：`feature` 对应的业务输入值
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `cameraName`（string）：`cameraName` 对应的业务输入值
 *   - `now`（未显式标注）：`now` 对应的业务输入值；声明包含默认值 `new Date()`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Date`、`filter`、`isSameLocalDay`、`sort`、`getTime`、`slice`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function buildFeatureAlarmSummary(
  alarms: AlarmEvent[],
  feature: FeatureDashboardKey,
  cameraKey: string,
  cameraName: string,
  now = new Date(),
) {
  const today = alarms
    .filter((alarm) => alarm.event_type === feature)
    .filter((alarm) => alarm.camera_no === cameraKey || (!alarm.camera_no && alarm.camera_name === cameraName))
    .filter((alarm) => isSameLocalDay(alarm.created_at, now))
    .sort((left, right) => new Date(right.created_at || 0).getTime() - new Date(left.created_at || 0).getTime())

  return { todayCount: today.length, recent: today.slice(0, 5) }
}
