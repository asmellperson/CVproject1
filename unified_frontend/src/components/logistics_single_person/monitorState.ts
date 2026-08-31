// 文件说明：实现监控展示、状态管理的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { AlarmEvent } from '@/lib/api'

export type LogisticsCountState = 'unknown' | 'normal' | 'empty' | 'multiple'

export type LogisticsMonitorEvent = {
  id: string
  state: Exclude<LogisticsCountState, 'unknown'>
  label: string
  occurredAt: string
}

/**
 * 功能：实现 `classifyLogisticsCount` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `count`（number | null | undefined）：`count` 对应的数量或大小
 * 返回：LogisticsCountState；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/monitorState.ts` 的 `appendLogisticsTransitionEvent`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/LogisticsSinglePersonMonitorView.tsx` 的
 *         `LogisticsSinglePersonMonitorView` 调用本符号
 *   - 内部调用：`isFinite`、`Number`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function classifyLogisticsCount(count: number | null | undefined): LogisticsCountState {
  if (!Number.isFinite(count)) return 'unknown'
  if (count === 1) return 'normal'
  if (count === 0) return 'empty'
  return Number(count) >= 2 ? 'multiple' : 'unknown'
}

/**
 * 功能：实现 `logisticsEventLabel` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `state`（LogisticsCountState）：`state` 对应的业务输入值
 *   - `count`（number | null | undefined）：`count` 对应的数量或大小
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/monitorState.ts` 的 `appendLogisticsTransitionEvent` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function logisticsEventLabel(state: LogisticsCountState, count: number | null | undefined) {
  if (state === 'normal') return 'ROI 内人数恢复正常：1 人'
  if (state === 'empty') return 'ROI 内无人异常：0 人'
  if (state === 'multiple') return `ROI 内多人异常：${count} 人`
  return ''
}

/**
 * 功能：实现 `appendLogisticsTransitionEvent` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 events, previousState, count, occurredAt, new, Date, limit, events
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts` 的
 *         `useLogisticsSinglePersonMonitor` 调用本符号
 *   - 内部调用：`Date`、`classifyLogisticsCount`、`getTime`、`logisticsEventLabel`、`toISOString`、`slice`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function appendLogisticsTransitionEvent({
  events,
  previousState,
  count,
  occurredAt = new Date(),
  limit = 8,
}: {
  events: LogisticsMonitorEvent[]
  previousState: LogisticsCountState
  count: number | null | undefined
  occurredAt?: Date
  limit?: number
}) {
  const nextState = classifyLogisticsCount(count)
  if (nextState === 'unknown' || nextState === previousState) {
    return { events, state: nextState === 'unknown' ? previousState : nextState }
  }
  const nextEvent: LogisticsMonitorEvent = {
    id: `${occurredAt.getTime()}-${nextState}`,
    state: nextState,
    label: logisticsEventLabel(nextState, count),
    occurredAt: occurredAt.toISOString(),
  }
  return {
    events: [nextEvent, ...events].slice(0, limit),
    state: nextState,
  }
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
 * 功能：实现 `filterTodayLogisticsAlarms` 对应的监控展示、状态管理逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarms`（AlarmEvent[]）：`alarms` 对应的业务输入值
 *   - `feature`（string）：`feature` 对应的业务输入值
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `cameraName`（string）：`cameraName` 对应的业务输入值
 *   - `now`（未显式标注）：`now` 对应的业务输入值；声明包含默认值 `new Date()`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts` 的
 *         `useLogisticsSinglePersonMonitor` 调用本符号
 *   - 内部调用：`Date`、`filter`、`isSameLocalDay`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function filterTodayLogisticsAlarms(
  alarms: AlarmEvent[],
  feature: string,
  cameraKey: string,
  cameraName: string,
  now = new Date(),
) {
  return alarms.filter((alarm) =>
    alarm.event_type === feature
    && (alarm.camera_no === cameraKey || (!alarm.camera_no && alarm.camera_name === cameraName))
    && isSameLocalDay(alarm.created_at, now),
  )
}
