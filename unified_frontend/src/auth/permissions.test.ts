import {
  DEPARTMENTS, DETECTION_PAGE_IDS, DETECTION_EVENT_TYPES, alarmEventTypesByPage,
  getUserDepartments, getAccessibleDepartments, getAccessibleAlarmEventTypes, hasPageAccess, resolveDepartment, resolvePage,
} from './permissions'

const viewer = (departments: string[]) => ({ employee_id: 'viewer', name: '查看者', role: 'viewer', departments })
const admin = { ...viewer([]), role: 'admin' }
if (DEPARTMENTS.length !== 7 || !DEPARTMENTS.includes('fulida_company')) throw new Error('seven official departments required')
if (DETECTION_PAGE_IDS.length !== 9 || new Set(DETECTION_PAGE_IDS).size !== 9) throw new Error('canonical detection pages must be unique')
for (const department of DEPARTMENTS) {
  const user = viewer([department])
  for (const page of DETECTION_PAGE_IDS) {
    if (!hasPageAccess(user, page)) throw new Error(`${department} must access ${page}`)
  }
  if (getAccessibleDepartments(user).join() !== department) throw new Error('viewer department scope leaked')
  if (getAccessibleAlarmEventTypes(user)?.join() !== DETECTION_EVENT_TYPES.join()) throw new Error('all departments need all event types')
  for (const requested of DEPARTMENTS) {
    if (resolveDepartment(user, requested) !== (requested === department ? department : null)) throw new Error('unauthorized department must be rejected')
    for (const page of DETECTION_PAGE_IDS) {
      if (resolvePage(user, page, requested) !== (requested === department ? page : 'overview')) throw new Error('detection URL must require an authorized department')
      if (resolvePage(admin, page, requested) !== page) throw new Error('admin must access explicitly scoped detection pages')
    }
    if (resolveDepartment(admin, requested) !== requested) throw new Error('admin must access every department')
  }
  if (hasPageAccess(user, 'user-management')) throw new Error('viewer must not manage users')
}
for (const departments of [[], ['unknown'], ['all'], ['ge'], ['通用电气']]) {
  if (DETECTION_PAGE_IDS.some((page) => hasPageAccess(viewer(departments), page))) throw new Error('unassigned viewer must not access detection data')
  if (resolveDepartment(viewer(departments), 'general_electric') !== null) throw new Error('unassigned viewer must have no department context')
}
if (getUserDepartments(viewer(['unknown', 'general_electric', 'general_electric'])).join() !== 'general_electric') throw new Error('only unique registered departments are accepted')
if (!hasPageAccess(admin, 'user-management')) throw new Error('admin must manage users')
if (hasPageAccess(admin, 'access-audit')) throw new Error('access audit requires explicit capability')
if (!hasPageAccess({ ...admin, capabilities: { view_access_audit: true } }, 'access-audit')) throw new Error('owner must access audit')
if (hasPageAccess(admin, 'unknown-page')) throw new Error('unknown PageId must be rejected')
if (alarmEventTypesByPage['face-recognition'].join() !== 'recognize_face') throw new Error('identity alarm type missing')

for (const user of [admin, viewer([DEPARTMENTS[0]]), viewer([...DEPARTMENTS])]) {
  for (const requested of [undefined, null, '', 'unknown', 'ge', '通用电气']) {
    if (resolveDepartment(user, requested) !== null) throw new Error('missing or invalid department must remain unresolved')
    for (const page of DETECTION_PAGE_IDS) {
      if (resolvePage(user, page, requested) !== 'overview') throw new Error('unscoped detection URL must return to overview')
    }
  }
}
