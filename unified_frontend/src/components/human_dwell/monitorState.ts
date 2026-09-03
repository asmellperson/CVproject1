// 文件说明：实现监控展示、状态管理的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { AlarmEvent } from '@/lib/api'

export type HumanDwellSample = {
  count: number | null
  durationSeconds: number | null
  alarm: boolean
}

export type HumanDwellMonitorEvent = {
  id: string
  tone: 'danger' | 'neutral'
  label: string
  occurredAt: string
}

/**
 * 功能：实现 `roundedSeconds` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（number | null | undefined）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/human_dwell/monitorState.ts` 的 `appendHumanDwellTransitionEvent` 调用本符号
 *   - 内部调用：`max`、`round`、`Number`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function roundedSeconds(value: number | null | undefined) {
  return Math.max(0, Math.round(Number(value) || 0))
}

/**
 * 功能：实现 `appendHumanDwellTransitionEvent` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 events, previous, next, occurredAt, new, Date, limit, events
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/human_dwell/useHumanDwellMonitor.ts` 的 `useHumanDwellMonitor` 调用本符号
 *   - 内部调用：`Date`、`roundedSeconds`、`getTime`、`toISOString`、`slice`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function appendHumanDwellTransitionEvent({
  events,
  previous,
  next,
  occurredAt = new Date(),
  limit = 8,
}: {
  events: HumanDwellMonitorEvent[]
  previous: HumanDwellSample | null
  next: HumanDwellSample
  occurredAt?: Date
  limit?: number
}) {
  let event: HumanDwellMonitorEvent | null = null

  if (next.alarm && previous && !previous.alarm) {
    const duration = roundedSeconds(next.durationSeconds)
    event = {
      id: `${occurredAt.getTime()}-loitering`,
      tone: 'danger',
      label: `人员在区域内逗留 ${duration} 秒，触发告警`,
      occurredAt: occurredAt.toISOString(),
    }
  } else if (previous && !previous.alarm && (previous.count ?? 0) > 0 && next.count === 0) {
    const count = previous.count ?? 0
    const duration = roundedSeconds(previous.durationSeconds)
    event = {
      id: `${occurredAt.getTime()}-left`,
      tone: 'neutral',
      label: `区域人数 ${count}，停留 ${duration} 秒后离开，未告警`,
      occurredAt: occurredAt.toISOString(),
    }
  }

  return event ? [event, ...events].slice(0, limit) : events
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
 * 功能：实现 `filterTodayHumanDwellAlarms` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarms`（AlarmEvent[]）：`alarms` 对应的业务输入值
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `cameraName`（string）：`cameraName` 对应的业务输入值
 *   - `feature`（未显式标注）：`feature` 对应的业务输入值；声明包含默认值 `'detect_human'`
 *   - `now`（未显式标注）：`now` 对应的业务输入值；声明包含默认值 `new Date()`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/human_dwell/useHumanDwellMonitor.ts` 的 `useHumanDwellMonitor` 调用本符号
 *   - 内部调用：`Date`、`filter`、`isSameLocalDay`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function filterTodayHumanDwellAlarms(
  alarms: AlarmEvent[],
  cameraKey: string,
  cameraName: string,
  feature = 'detect_human',
  now = new Date(),
) {
  return alarms.filter((alarm) =>
    (alarm.feature_name || alarm.event_type) === feature
    && (
      alarm.subject_type === 'camera'
        ? alarm.subject_name === cameraName || alarm.camera_no === cameraKey
        : alarm.camera_no === cameraKey || (!alarm.camera_no && alarm.camera_name === cameraName)
    )
    && isSameLocalDay(alarm.created_at, now),
  )
}
