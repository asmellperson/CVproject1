import type { AuthUser } from '@/auth/auth-context'
import type { NavGroup, NavItem } from '@/lib/nav'

export type Department = 'general_electric' | 'research_institute' | 'all'
export type UserRole = 'admin' | 'viewer'
export type PageId =
  | 'overview'
  | 'home'
  | 'security-vlm'
  | 'guard-behavior'
  | 'intrusion-detection'
  | 'door-detection'
  | 'face-detection'
  | 'human-detection'
  | 'phone-detection'
  | 'alarms'
  | 'statistics'

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
    pages: ['overview', 'security-vlm', 'guard-behavior', 'human-detection'],
    displayOverrides: {
      'human-detection': {
        label: '后大门异常逗留检测',
        title: '后大门异常逗留检测',
        description: '后大门异常逗留监控与配置入口',
      },
    },
  },
  research_institute: {
    pages: ['overview', 'intrusion-detection', 'face-detection', 'phone-detection'],
    displayOverrides: {
      'intrusion-detection': {
        label: '区域逗留检测',
        title: '区域逗留检测',
        description: '区域逗留监控与配置入口',
      },
    },
  },
}

const departmentAliases: Record<string, Department> = {
  all: 'all',
  general_electric: 'general_electric',
  'general electric': 'general_electric',
  generalElectric: 'general_electric',
  'general-electric': 'general_electric',
  ge: 'general_electric',
  research_institute: 'research_institute',
  'research institute': 'research_institute',
  researchInstitute: 'research_institute',
  'research-institute': 'research_institute',
  ri: 'research_institute',
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
  'guard-behavior',
  'intrusion-detection',
  'door-detection',
  'face-detection',
  'human-detection',
  'phone-detection',
  'alarms',
  'statistics',
])

function normalizePageId(pageId: string): PageId | null {
  // Handle "feature@department" pattern
  const baseId = pageId.split('@')[0]
  if (!pageIds.has(baseId)) return null
  return (baseId === 'home' ? 'overview' : baseId) as PageId
}

function normalizeKey(value: unknown) {
  return String(value ?? '').trim()
}

export function getUserRole(user: AuthUser | null | undefined): UserRole | null {
  const rawRole = normalizeKey(user?.role)
  if (!rawRole) return null
  return roleAliases[rawRole] ?? roleAliases[rawRole.toLowerCase()] ?? null
}

export function getUserDepartment(user: AuthUser | null | undefined): Department | null {
  const rawDepartment = normalizeKey(user?.department)
  if (!rawDepartment) return null
  return departmentAliases[rawDepartment] ?? departmentAliases[rawDepartment.toLowerCase()] ?? null
}

export function hasPageAccess(user: AuthUser | null | undefined, pageId: string) {
  const normalizedPageId = normalizePageId(pageId)
  if (!normalizedPageId) return false
  const role = getUserRole(user)
  if (normalizedPageId === 'overview') return true
  if (role === 'admin') return true
  if (!user || role !== 'viewer') return false

  const department = getUserDepartment(user)
  if (!department) return false
  if (department === 'all') return true

  // Check if user has access to the page, and if it's a dept-specific page, check if it's their dept
  const hasAccess = departmentPermissions[department]?.pages.includes(normalizedPageId) ?? false
  
  // Also check if the page's department (if any) matches the user's department
  const pageDept = pageId.split('@')[1]
  if (pageDept) {
    // Convert kebab-case to snake_case
    const normalizedPageDept = pageDept.replace(/-/g, '_') as Department
    return hasAccess && normalizedPageDept === department
  }
  
  return hasAccess
}

export function getPageDisplayOverride(user: AuthUser | null | undefined, pageId: string) {
  if (getUserRole(user) === 'admin') return undefined
  const department = getUserDepartment(user)
  if (!department || department === 'all') return undefined
  const normalizedPageId = normalizePageId(pageId)
  if (!normalizedPageId) return undefined
  return departmentPermissions[department]?.displayOverrides?.[normalizedPageId]
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
      const filteredItems = group.items
        .filter((item) => hasPageAccess(user, item.id))
        .map((item) => applyDisplayOverride<NavItem>(user, item))

      let filteredDepartments = group.departments
      if (filteredDepartments) {
        filteredDepartments = filteredDepartments
          .map((dept) => ({
            ...dept,
            items: dept.items
              .filter((item) => hasPageAccess(user, item.id))
              .map((item) => applyDisplayOverride<NavItem>(user, item)),
          }))
          .filter((dept) => dept.items.length > 0)
      }

      return {
        ...group,
        items: filteredItems,
        departments: filteredDepartments,
      }
    })
    .filter((group) => group.items.length > 0 || (group.departments && group.departments.length > 0))
}

export function filterHomeModulesByPermission<T extends { id: string; title: string; description?: string }>(
  user: AuthUser | null | undefined,
  moduleEntries: T[],
): T[] {
  return moduleEntries
    .filter((entry) => hasPageAccess(user, entry.id))
    .map((entry) => applyDisplayOverride<T>(user, entry))
}
