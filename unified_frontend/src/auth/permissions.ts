import type { AuthUser } from '@/auth/auth-context'
import type { NavGroup, NavItem } from '@/lib/nav'

export type Department = 'general_electric' | 'research_institute' | 'electronics_electrician' | 'electrical_components' | 'precious_metal_recycling' | 'haoda_company' | 'all'
export type UserRole = 'admin' | 'viewer'
export type PageId =
  | 'overview'
  | 'home'
  | 'security-vlm'
  | 'security-vlm-general-electric'
  | 'security-vlm-electronics-electrician'
  | 'security-vlm-electrical-components'
  | 'security-vlm-precious-metal-recycling'
  | 'guard-behavior'
  | 'guard-behavior-general-electric'
  | 'guard-behavior-electronics-electrician'
  | 'intrusion-detection'
  | 'door-detection'
  | 'face-detection'
  | 'human-detection'
  | 'haoda-human-detection'
  | 'logistics-single-person-detection'
  | 'logistics-single-person-electronics-electrician-detection'
  | 'logistics-single-person-electrical-components-detection'
  | 'logistics-single-person-precious-metal-recycling-detection'
  | 'phone-detection'
  | 'alarms'
  | 'statistics'
  | 'access-audit'
  | 'user-management'

type PageDisplayOverride = {
  label?: string
  title?: string
  description?: string
}

type DepartmentPermission = {
  pages: PageId[]
  displayOverrides?: Record<string, PageDisplayOverride>
}

export const departmentPermissions: Record<Exclude<Department, 'all'>, DepartmentPermission> = {
  general_electric: {
    pages: ['overview', 'security-vlm-general-electric', 'guard-behavior-general-electric', 'human-detection', 'logistics-single-person-detection', 'alarms', 'statistics'],
    displayOverrides: {
      'guard-behavior-general-electric': {
        label: '保安行为规范检测',
        title: '保安行为规范检测',
        description: '通用电气保安行为规范监控与配置',
      },
      'human-detection': {
        label: '后大门异常逗留检测',
        title: '后大门异常逗留检测',
        description: '后大门异常逗留监控与配置入口',
      },
    },
  },
  research_institute: {
    pages: ['overview', 'intrusion-detection', 'face-detection', 'phone-detection', 'alarms', 'statistics'],
    displayOverrides: {
      'intrusion-detection': {
        label: '区域入侵检测',
        title: '区域入侵检测',
        description: '区域入侵监控与配置入口',
      },
    },
  },
  electronics_electrician: {
    pages: ['overview', 'security-vlm-electronics-electrician', 'guard-behavior-electronics-electrician', 'logistics-single-person-electronics-electrician-detection', 'alarms', 'statistics'],
    displayOverrides: {
      'guard-behavior-electronics-electrician': {
        label: '保安行为规范检测',
        title: '保安行为规范检测',
        description: '电子电工保安行为规范监控与配置',
      },
      'logistics-single-person-electronics-electrician-detection': {
        label: '物流通道单人检测',
        title: '物流通道单人检测（电子电工）',
        description: '电子电工物流通道单人监控与配置入口',
      },
    },
  },
  electrical_components: {
    pages: ['overview', 'security-vlm-electrical-components', 'logistics-single-person-electrical-components-detection', 'alarms', 'statistics'],
    displayOverrides: {
      'logistics-single-person-electrical-components-detection': {
        label: '物流通道单人检测',
        title: '物流通道单人检测（电气部件）',
        description: '电气部件物流通道单人监控与配置入口',
      },
    },
  },
  precious_metal_recycling: {
    pages: ['overview', 'security-vlm-precious-metal-recycling', 'logistics-single-person-precious-metal-recycling-detection', 'alarms', 'statistics'],
    displayOverrides: {
      'logistics-single-person-precious-metal-recycling-detection': {
        label: '物流通道单人检测',
        title: '物流通道单人检测（伟达公司）',
        description: '伟达公司物流通道单人监控与配置入口',
      },
    },
  },
  haoda_company: {
    pages: ['overview', 'haoda-human-detection', 'alarms', 'statistics'],
  },
}

export const alarmEventTypesByPage: Partial<Record<PageId, string[]>> = {
  'security-vlm': ['security_vlm_non_compliant', 'security_vlm_error'],
  'security-vlm-general-electric': ['security_vlm_non_compliant', 'security_vlm_error'],
  'security-vlm-electronics-electrician': ['security_vlm_non_compliant', 'security_vlm_error'],
  'security-vlm-electrical-components': ['security_vlm_non_compliant', 'security_vlm_error'],
  'security-vlm-precious-metal-recycling': ['security_vlm_non_compliant', 'security_vlm_error'],
  'guard-behavior': ['guard_absent', 'guard_phone_use', 'guard_prone_sleep'],
  'guard-behavior-general-electric': ['guard_absent', 'guard_phone_use', 'guard_prone_sleep'],
  'guard-behavior-electronics-electrician': ['guard_absent', 'guard_phone_use', 'guard_prone_sleep'],
  'intrusion-detection': ['blocks'],
  'door-detection': ['detect_door'],
  'face-detection': ['detect_face'],
  'human-detection': ['detect_human'],
  'haoda-human-detection': ['detect_human_haoda'],
  'logistics-single-person-detection': ['detect_logistics_single_person'],
  'logistics-single-person-electronics-electrician-detection': ['detect_logistics_single_person_electronics_electrician'],
  'logistics-single-person-electrical-components-detection': ['detect_logistics_single_person_electrical_components'],
  'logistics-single-person-precious-metal-recycling-detection': ['detect_logistics_single_person_precious_metal_recycling'],
  'phone-detection': ['detect_phone'],
}

const departmentAliases: Record<string, Department> = {
  all: 'all',
  general_electric: 'general_electric',
  'general electric': 'general_electric',
  generalElectric: 'general_electric',
  'general-electric': 'general_electric',
  ge: 'general_electric',
  electronics_electrician: 'electronics_electrician',
  'electronics electrician': 'electronics_electrician',
  electronicsElectrician: 'electronics_electrician',
  'electronics-electrician': 'electronics_electrician',
  research_institute: 'research_institute',
  'research institute': 'research_institute',
  researchInstitute: 'research_institute',
  'research-institute': 'research_institute',
  ri: 'research_institute',
  electrical_components: 'electrical_components',
  'electrical components': 'electrical_components',
  electricalComponents: 'electrical_components',
  'electrical-components': 'electrical_components',
  ec: 'electrical_components',
  precious_metal_recycling: 'precious_metal_recycling',
  'precious metal recycling': 'precious_metal_recycling',
  preciousMetalRecycling: 'precious_metal_recycling',
  'precious-metal-recycling': 'precious_metal_recycling',
  pmr: 'precious_metal_recycling',
  weida: 'precious_metal_recycling',
  weida_company: 'precious_metal_recycling',
  'weida company': 'precious_metal_recycling',
  'weida-company': 'precious_metal_recycling',
  '伟达': 'precious_metal_recycling',
  '伟达公司': 'precious_metal_recycling',
  '贵金属回收': 'precious_metal_recycling',
  haoda_company: 'haoda_company',
  'haoda company': 'haoda_company',
  haodaCompany: 'haoda_company',
  'haoda-company': 'haoda_company',
  haoda: 'haoda_company',
  '皓达': 'haoda_company',
  '皓达公司': 'haoda_company',
}

const roleAliases: Record<string, UserRole> = {
  admin: 'admin',
  administrator: 'admin',
  viewer: 'viewer',
  user: 'viewer',
}

const pageIds = new Set<string>([
  'overview',
  'home',
  'security-vlm',
  'security-vlm-general-electric',
  'security-vlm-electronics-electrician',
  'security-vlm-electrical-components',
  'security-vlm-precious-metal-recycling',
  'guard-behavior',
  'guard-behavior-general-electric',
  'guard-behavior-electronics-electrician',
  'intrusion-detection',
  'door-detection',
  'face-detection',
  'human-detection',
  'haoda-human-detection',
  'logistics-single-person-detection',
  'logistics-single-person-electronics-electrician-detection',
  'logistics-single-person-electrical-components-detection',
  'logistics-single-person-precious-metal-recycling-detection',
  'phone-detection',
  'alarms',
  'statistics',
  'access-audit',
  'user-management',
])

function normalizePageId(pageId: string): PageId | null {
  if (!pageIds.has(pageId)) return null
  return (pageId === 'home' ? 'overview' : pageId) as PageId
}

function normalizeKey(value: unknown) {
  return String(value ?? '').trim()
}

export function getUserRole(user: AuthUser | null | undefined): UserRole | null {
  const rawRole = normalizeKey(user?.role)
  if (!rawRole) return null
  return roleAliases[rawRole] ?? roleAliases[rawRole.toLowerCase()] ?? null
}

function normalizeDepartment(value: unknown): Department | null {
  const rawDepartment = normalizeKey(value)
  if (!rawDepartment) return null
  return departmentAliases[rawDepartment] ?? departmentAliases[rawDepartment.toLowerCase()] ?? null
}

export function getUserDepartments(user: AuthUser | null | undefined): Department[] {
  const rawDepartments = Array.isArray(user?.departments) && user.departments.length > 0
    ? user.departments
    : [user?.department]
  const departments: Department[] = []
  rawDepartments.forEach((value) => {
    const department = normalizeDepartment(value)
    if (department && !departments.includes(department)) departments.push(department)
  })
  return departments
}

export function getUserDepartment(user: AuthUser | null | undefined): Department | null {
  return getUserDepartments(user)[0] ?? null
}

export function hasPageAccess(user: AuthUser | null | undefined, pageId: string) {
  const normalizedPageId = normalizePageId(pageId)
  if (!normalizedPageId) return false
  if (normalizedPageId === 'access-audit') {
    return user?.capabilities?.view_access_audit === true
  }
  const role = getUserRole(user)
  if (normalizedPageId === 'overview') return true
  if (role === 'admin') return true
  if (!user || role !== 'viewer') return false

  const departments = getUserDepartments(user)
  if (departments.length === 0) return false
  if (departments.includes('all')) return true

  return departments.some((department) => (
    department !== 'all'
    && departmentPermissions[department]?.pages.includes(normalizedPageId)
  ))
}

export function getPageDisplayOverride(user: AuthUser | null | undefined, pageId: string) {
  if (getUserRole(user) === 'admin') return undefined
  const departments = getUserDepartments(user)
  if (departments.length === 0 || departments.includes('all')) return undefined
  const normalizedPageId = normalizePageId(pageId)
  if (!normalizedPageId) return undefined
  for (const department of departments) {
    if (department === 'all') continue
    const override = departmentPermissions[department]?.displayOverrides?.[normalizedPageId]
    if (override) return override
  }
  return undefined
}

function applyDisplayOverride<T extends { id: string; label?: string; title?: string; description?: string }>(
  user: AuthUser | null | undefined,
  item: T,
): T {
  const override = getPageDisplayOverride(user, item.id)
  if (!override) return item
  const next = { ...item }
  if (override.label && 'label' in next) next.label = override.label
  if (override.title && 'title' in next) next.title = override.title
  if (override.description) next.description = override.description
  return next
}

export function filterNavGroupsByPermission(user: AuthUser | null | undefined, groups: NavGroup[]): NavGroup[] {
  return groups
    .map((group) => {
      const items = group.items
        .filter((item) => hasPageAccess(user, item.id))
        .map((item) => applyDisplayOverride<NavItem>(user, item))
      const children = group.children ? filterNavGroupsByPermission(user, group.children) : undefined
      return { ...group, items, children }
    })
    .filter((group) => group.items.length > 0 || (group.children?.length ?? 0) > 0)
}

export function filterHomeModulesByPermission<T extends { id: string; title: string; description?: string }>(
  user: AuthUser | null | undefined,
  moduleEntries: T[],
): T[] {
  return moduleEntries
    .filter((entry) => hasPageAccess(user, entry.id))
    .map((entry) => applyDisplayOverride<T>(user, entry))
}

export function getAccessibleAlarmEventTypes(user: AuthUser | null | undefined): string[] | null {
  const role = getUserRole(user)
  if (role === 'admin') return null
  if (!user || role !== 'viewer') return []

  const departments = getUserDepartments(user)
  if (departments.includes('all')) return null
  if (departments.length === 0) return []

  const allowed = new Set<string>()
  for (const [pageId, eventTypes] of Object.entries(alarmEventTypesByPage)) {
    if (hasPageAccess(user, pageId)) {
      eventTypes.forEach((eventType) => allowed.add(eventType))
    }
  }
  return Array.from(allowed)
}
