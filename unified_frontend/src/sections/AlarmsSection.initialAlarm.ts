// 文件说明：实现告警的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

type AlarmWithSource = {
  id: string
  source?: string
  source_id?: string | number | null
}

/**
 * 功能：读取或查询 `findInitialAlarm` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarms`（readonly T[]）：`alarms` 对应的业务输入值
 *   - `initialAlarmId`（string）：`initialAlarmId` 对应业务对象的唯一标识
 * 返回：T | undefined；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AlarmsSection.tsx` 的 `AlarmsSection` 调用本符号
 *   - 内部调用：`find`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function findInitialAlarm<T extends AlarmWithSource>(
  alarms: readonly T[],
  initialAlarmId: string,
): T | undefined {
  if (!initialAlarmId) return undefined

  return alarms.find((item) => {
    const sourceId = item.source_id || item.id
    return item.id === initialAlarmId || `${item.source || 'aivision'}:${sourceId}` === initialAlarmId
  })
}

/**
 * 功能：删除或清理 `removeAlarmIdFromSearch` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `search`（string）：`search` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AlarmsSection.initialAlarm.ts` 的 `buildUrlWithoutAlarmId` 调用本符号
 *   - 内部调用：`URLSearchParams`、`delete`、`toString`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function removeAlarmIdFromSearch(search: string) {
  const params = new URLSearchParams(search)
  params.delete('alarmId')
  const nextSearch = params.toString()
  return nextSearch ? `?${nextSearch}` : ''
}

/**
 * 功能：创建或构建 `buildUrlWithoutAlarmId` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `location`（Pick<Location, 'pathname' | 'search' | 'hash'>）：`location` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AlarmsSection.tsx` 的 `AlarmsSection` 调用本符号
 *   - 内部调用：`removeAlarmIdFromSearch`、`Location`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function buildUrlWithoutAlarmId(location: Pick<Location, 'pathname' | 'search' | 'hash'>) {
  return `${location.pathname}${removeAlarmIdFromSearch(location.search)}${location.hash}`
}
