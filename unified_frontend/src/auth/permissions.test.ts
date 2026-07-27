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

const electricalComponentsUser = {
  employee_id: 'u2',
  name: '电气部件用户',
  role: 'viewer',
  department: 'electrical_components',
}

const preciousMetalRecyclingUser = {
  employee_id: 'u3',
  name: '贵金属回收用户',
  role: 'viewer',
  department: 'precious_metal_recycling',
}

if (getUserDepartment(electricalComponentsUser) !== 'electrical_components') {
  throw new Error('expected electrical_components department to normalize')
}

if (getUserDepartment(preciousMetalRecyclingUser) !== 'precious_metal_recycling') {
  throw new Error('expected precious_metal_recycling department to normalize')
}

if (!hasPageAccess(electricalComponentsUser, 'logistics-single-person-electrical-components-detection')) {
  throw new Error('expected electrical components department to access its logistics single person page')
}

if (!hasPageAccess(preciousMetalRecyclingUser, 'logistics-single-person-precious-metal-recycling-detection')) {
  throw new Error('expected precious metal recycling department to access its logistics single person page')
}

if (hasPageAccess(electricalComponentsUser, 'logistics-single-person-precious-metal-recycling-detection')) {
  throw new Error('expected electrical components department to be isolated from precious metal recycling page')
}

if (hasPageAccess(preciousMetalRecyclingUser, 'logistics-single-person-electrical-components-detection')) {
  throw new Error('expected precious metal recycling department to be isolated from electrical components page')
}

if (alarmEventTypesByPage['logistics-single-person-electrical-components-detection']?.join(',') !== 'detect_logistics_single_person_electrical_components') {
  throw new Error('expected electrical components logistics page to map to its alarm event type')
}

if (alarmEventTypesByPage['logistics-single-person-precious-metal-recycling-detection']?.join(',') !== 'detect_logistics_single_person_precious_metal_recycling') {
  throw new Error('expected precious metal recycling logistics page to map to its alarm event type')
}
