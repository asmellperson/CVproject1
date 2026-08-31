// 文件说明：包含告警的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { findInitialAlarm, removeAlarmIdFromSearch } from './AlarmsSection.initialAlarm'

/**
 * 功能：实现 `assertEqual` 对应的告警逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（unknown）：`actual` 对应的业务输入值
 *   - `expected`（unknown）：`expected` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Error`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertEqual(actual: unknown, expected: unknown) {
  if (actual !== expected) {
    throw new Error(`expected ${expected}, got ${actual}`)
  }
}

const alarms = [
  { id: '101', source: 'aivision', source_id: '101' },
  { id: 'security-7', source: 'security_vlm', source_id: '7' },
]

assertEqual(findInitialAlarm(alarms, 'aivision:101')?.id, '101')
assertEqual(findInitialAlarm(alarms, 'security_vlm:7')?.id, 'security-7')
assertEqual(findInitialAlarm(alarms, 'missing'), undefined)

assertEqual(removeAlarmIdFromSearch('?page=alarms&alarmId=aivision%3A101'), '?page=alarms')
assertEqual(removeAlarmIdFromSearch('?page=alarms&alarmId=aivision%3A101&from=wechat'), '?page=alarms&from=wechat')
assertEqual(removeAlarmIdFromSearch('?alarmId=aivision%3A101'), '')
