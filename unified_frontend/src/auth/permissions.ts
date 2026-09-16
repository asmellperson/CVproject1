import type { AuthUser } from '@/auth/auth-context'
import type { NavGroup } from '@/lib/nav'

export const DEPARTMENTS = [
  'general_electric', 'research_institute', 'electronics_electrician',
  'electrical_components', 'precious_metal_recycling', 'haoda_company',
] as const
export type DepartmentId = typeof DEPARTMENTS[number]
export type Department = DepartmentId | 'all'
export const DEPARTMENT_LABELS: Record<DepartmentId, string> = {
  general_electric: '通用电气', research_institute: '福达新材院',
  electronics_electrician: '电子电工', electrical_components: '电气部件事业部',
  precious_metal_recycling: '伟达公司', haoda_company: '皓达公司',
}
export const DETECTION_PAGE_IDS = [
  'security-vlm', 'guard-behavior', 'intrusion-detection', 'door-detection',
  'face-detection', 'face-recognition', 'human-detection', 'logistics-single-person', 'phone-detection',
] as const
export type DetectionPageId = typeof DETECTION_PAGE_IDS[number]
export type UserRole = 'admin' | 'viewer'
export type PageId = DetectionPageId | 'overview' | 'alarms' | 'statistics' | 'access-audit' | 'user-management'

export const alarmEventTypesByPage: Record<DetectionPageId, string[]> = {
  'security-vlm': ['security_vlm_non_compliant', 'security_vlm_error'],
  'guard-behavior': ['guard_absent', 'guard_phone_use', 'guard_prone_sleep'],
  'intrusion-detection': ['blocks'], 'door-detection': ['detect_door'],
  'face-detection': ['detect_face'], 'face-recognition': ['recognize_face'],
  'human-detection': ['detect_human'], 'logistics-single-person': ['detect_logistics_single_person'],
  'phone-detection': ['detect_phone'],
}
export const DETECTION_EVENT_TYPES = Object.values(alarmEventTypesByPage).flat()
const pageIds = new Set<string>([...DETECTION_PAGE_IDS, 'overview', 'alarms', 'statistics', 'access-audit', 'user-management'])

export function isDepartment(value: unknown): value is DepartmentId {
  return typeof value === 'string' && (DEPARTMENTS as readonly string[]).includes(value)
}

export function getUserRole(user: AuthUser | null | undefined): UserRole | null {
  return user?.role === 'admin' || user?.role === 'viewer' ? user.role : null
}

export function getUserDepartments(user: AuthUser | null | undefined): Department[] {
  const values = Array.isArray(user?.departments) ? user.departments : []
  return [...new Set(values.filter((value): value is Department => value === 'all' || isDepartment(value)))]
}

export function getUserDepartment(user: AuthUser | null | undefined): Department | null {
  return getUserDepartments(user)[0] ?? null
}

export function getAccessibleDepartments(user: AuthUser | null | undefined): DepartmentId[] {
  const departments = getUserDepartments(user)
  if (getUserRole(user) === 'admin') return [...DEPARTMENTS]
  if (getUserRole(user) !== 'viewer') return []
  return departments.includes('all') ? [...DEPARTMENTS] : departments.filter(isDepartment)
}

export function resolveDepartment(user: AuthUser | null | undefined, requested: unknown): DepartmentId | null {
  const accessible = getAccessibleDepartments(user)
  return isDepartment(requested) && accessible.includes(requested) ? requested : accessible[0] ?? null
}

export function hasPageAccess(user: AuthUser | null | undefined, pageId: string) {
  if (!pageIds.has(pageId)) return false
  if (pageId === 'access-audit') return user?.capabilities?.view_access_audit === true
  if (pageId === 'overview') return true
  if (getUserRole(user) === 'admin') return true
  if (pageId === 'user-management') return false
  return getUserRole(user) === 'viewer' && getAccessibleDepartments(user).length > 0
}

export function filterNavGroupsByPermission(user: AuthUser | null | undefined, groups: NavGroup[]): NavGroup[] {
  return groups.map((group) => ({
    ...group,
    items: group.items.filter((item) => hasPageAccess(user, item.id)),
    children: group.children ? filterNavGroupsByPermission(user, group.children) : undefined,
  })).filter((group) => group.items.length > 0 || (group.children?.length ?? 0) > 0)
}

export function filterHomeModulesByPermission<T extends { id: string; title: string; description?: string }>(
  user: AuthUser | null | undefined, moduleEntries: T[],
): T[] {
  return moduleEntries.filter((entry) => hasPageAccess(user, entry.id))
}

export function getAccessibleAlarmEventTypes(user: AuthUser | null | undefined): string[] | null {
  if (getUserRole(user) === 'admin') return null
  return getAccessibleDepartments(user).length ? [...DETECTION_EVENT_TYPES] : []
}
