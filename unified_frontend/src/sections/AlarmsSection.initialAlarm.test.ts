import { findInitialAlarm, removeAlarmIdFromSearch } from './AlarmsSection.initialAlarm'

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
