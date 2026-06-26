import {
  alarmEventTypesByPage,
  departmentPermissions,
  getUserDepartment,
  hasPageAccess,
} from './permissions'

const electronicsUser = {
  employee_id: 'u1',
  name: '电子电工用户',
  role: 'viewer',
  department: 'electronics_electrician',
}

if (getUserDepartment(electronicsUser) !== 'electronics_electrician') {
  throw new Error('expected electronics_electrician department to normalize')
}

if (!hasPageAccess(electronicsUser, 'guard-behavior-electronics-electrician')) {
  throw new Error('expected electronics department to access its guard behavior page')
}

if (hasPageAccess(electronicsUser, 'guard-behavior-general-electric')) {
  throw new Error('expected electronics department to be isolated from general electric guard behavior page')
}

if (!departmentPermissions.electronics_electrician.pages.includes('guard-behavior-electronics-electrician')) {
  throw new Error('expected electronics department permissions to include its guard behavior page')
}

if (alarmEventTypesByPage['guard-behavior-electronics-electrician']?.join(',') !== 'guard_absent,guard_phone_use,guard_prone_sleep') {
  throw new Error('expected electronics guard page to map to guard alarm event types')
}
