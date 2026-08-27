import {
  alarmEventTypesByPage,
  departmentPermissions,
  getUserDepartment,
  hasPageAccess,
  type PageId,
} from './permissions'

const userManagementPage: PageId = 'user-management'
const adminUser = {
  employee_id: 'admin',
  name: '管理员',
  role: 'admin',
  department: 'all',
}

const ownerUser = {
  ...adminUser,
  capabilities: { view_access_audit: true },
}

if (!hasPageAccess(adminUser, userManagementPage)) {
  throw new Error('expected administrators to access user management')
}

if (hasPageAccess(adminUser, 'access-audit')) {
  throw new Error('expected ordinary administrators to be isolated from access audit')
}

if (!hasPageAccess(ownerUser, 'access-audit')) {
  throw new Error('expected platform owner capability to grant access audit')
}

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

if (hasPageAccess(electronicsUser, userManagementPage)) {
  throw new Error('expected viewers to be isolated from user management')
}

if (!departmentPermissions.electronics_electrician.pages.includes('guard-behavior-electronics-electrician')) {
  throw new Error('expected electronics department permissions to include its guard behavior page')
}

if (!hasPageAccess(electronicsUser, 'security-vlm-electronics-electrician')) {
  throw new Error('expected electronics department to access its security VLM page')
}

if (hasPageAccess(electronicsUser, 'security-vlm-general-electric')) {
  throw new Error('expected electronics department to be isolated from general electric security VLM page')
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
  name: '伟达公司用户',
  role: 'viewer',
  department: 'precious_metal_recycling',
}

const weidaAliasUser = {
  employee_id: 'u4',
  name: '伟达公司别名用户',
  role: 'viewer',
  department: '伟达公司',
}

if (getUserDepartment(electricalComponentsUser) !== 'electrical_components') {
  throw new Error('expected electrical_components department to normalize')
}

if (getUserDepartment(preciousMetalRecyclingUser) !== 'precious_metal_recycling') {
  throw new Error('expected precious_metal_recycling department to normalize')
}

if (getUserDepartment(weidaAliasUser) !== 'precious_metal_recycling') {
  throw new Error('expected 伟达公司 alias to normalize')
}

if (!hasPageAccess(electricalComponentsUser, 'logistics-single-person-electrical-components-detection')) {
  throw new Error('expected electrical components department to access its logistics single person page')
}

if (!hasPageAccess(electricalComponentsUser, 'security-vlm-electrical-components')) {
  throw new Error('expected electrical components department to access its security VLM page')
}

if (!hasPageAccess(preciousMetalRecyclingUser, 'security-vlm-precious-metal-recycling')) {
  throw new Error('expected precious metal recycling department to access its security VLM page')
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

const haodaUser = {
  employee_id: 'u4',
  name: '皓达公司用户',
  role: 'viewer',
  department: 'haoda_company',
}

if (getUserDepartment(haodaUser) !== 'haoda_company') {
  throw new Error('expected haoda_company department to normalize')
}

if (!hasPageAccess(haodaUser, 'haoda-human-detection')) {
  throw new Error('expected Haoda users to access their human dwell page')
}

if (hasPageAccess(haodaUser, 'human-detection')) {
  throw new Error('expected Haoda users to be isolated from the general electric human dwell page')
}

if (alarmEventTypesByPage['haoda-human-detection']?.join(',') !== 'detect_human_haoda') {
  throw new Error('expected Haoda human dwell page to map to its independent alarm event type')
}
