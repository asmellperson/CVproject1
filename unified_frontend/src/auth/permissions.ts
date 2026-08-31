// 文件说明：实现页面权限相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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

/**
 * 功能：转换或规范化 `normalizePageId` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `pageId`（string）：`pageId` 对应业务对象的唯一标识
 * 返回：PageId | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `hasPageAccess` 调用本符号；`unified_frontend/src/auth/permissions.ts` 的
 *         `getPageDisplayOverride` 调用本符号
 *   - 内部调用：`has`、`return`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function normalizePageId(pageId: string): PageId | null {
  if (!pageIds.has(pageId)) return null
  return (pageId === 'home' ? 'overview' : pageId) as PageId
}

/**
 * 功能：转换或规范化 `normalizeKey` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `getUserRole` 调用本符号；`unified_frontend/src/auth/permissions.ts` 的
 *         `normalizeDepartment` 调用本符号
 *   - 内部调用：`String`、`trim`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function normalizeKey(value: unknown) {
  return String(value ?? '').trim()
}

/**
 * 功能：读取或查询 `getUserRole` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 * 返回：UserRole | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `hasPageAccess` 调用本符号；`unified_frontend/src/auth/permissions.ts` 的
 *         `getPageDisplayOverride` 调用本符号；`unified_frontend/src/auth/permissions.ts` 的 `getAccessibleAlarmEventTypes` 调用本符号
 *   - 内部调用：`normalizeKey`、`toLowerCase`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function getUserRole(user: AuthUser | null | undefined): UserRole | null {
  const rawRole = normalizeKey(user?.role)
  if (!rawRole) return null
  return roleAliases[rawRole] ?? roleAliases[rawRole.toLowerCase()] ?? null
}

/**
 * 功能：转换或规范化 `normalizeDepartment` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（unknown）：待转换、校验或写入的值
 * 返回：Department | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `getUserDepartments` 调用本符号
 *   - 内部调用：`normalizeKey`、`toLowerCase`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function normalizeDepartment(value: unknown): Department | null {
  const rawDepartment = normalizeKey(value)
  if (!rawDepartment) return null
  return departmentAliases[rawDepartment] ?? departmentAliases[rawDepartment.toLowerCase()] ?? null
}

/**
 * 功能：读取或查询 `getUserDepartments` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 * 返回：Department[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `getUserDepartment` 调用本符号；`unified_frontend/src/auth/permissions.ts` 的
 *         `hasPageAccess` 调用本符号；`unified_frontend/src/auth/permissions.ts` 的 `getPageDisplayOverride`
 *         调用本符号；`unified_frontend/src/auth/permissions.ts` 的 `getAccessibleAlarmEventTypes` 调用本符号；另有 1 处静态调用
 *   - 内部调用：`isArray`、`forEach`、`normalizeDepartment`、`includes`、`push`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：读取或查询 `getUserDepartment` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 * 返回：Department | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`getUserDepartments`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function getUserDepartment(user: AuthUser | null | undefined): Department | null {
  return getUserDepartments(user)[0] ?? null
}

/**
 * 功能：检查或判断 `hasPageAccess` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 *   - `pageId`（string）：`pageId` 对应业务对象的唯一标识
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `filterNavGroupsByPermission`
 *         调用本符号；`unified_frontend/src/auth/permissions.ts` 的 `filterHomeModulesByPermission`
 *         调用本符号；`unified_frontend/src/auth/permissions.ts` 的 `getAccessibleAlarmEventTypes` 调用本符号
 *   - 内部调用：`normalizePageId`、`getUserRole`、`getUserDepartments`、`includes`、`some`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：读取或查询 `getPageDisplayOverride` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 *   - `pageId`（string）：`pageId` 对应业务对象的唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `applyDisplayOverride` 调用本符号
 *   - 内部调用：`getUserRole`、`getUserDepartments`、`includes`、`normalizePageId`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：实现 `applyDisplayOverride` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 *   - `item`（T）：`item` 对应的业务输入值
 * 返回：T；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/permissions.ts` 的 `filterNavGroupsByPermission`
 *         调用本符号；`unified_frontend/src/auth/permissions.ts` 的 `filterHomeModulesByPermission` 调用本符号
 *   - 内部调用：`getPageDisplayOverride`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：实现 `filterNavGroupsByPermission` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 *   - `groups`（NavGroup[]）：`groups` 对应的业务输入值
 * 返回：NavGroup[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`map`、`filter`、`hasPageAccess`、`applyDisplayOverride`、`NavItem`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：实现 `filterHomeModulesByPermission` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 *   - `moduleEntries`（T[]）：`moduleEntries` 对应的业务输入值
 * 返回：T[]；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`filter`、`hasPageAccess`、`map`、`applyDisplayOverride`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function filterHomeModulesByPermission<T extends { id: string; title: string; description?: string }>(
  user: AuthUser | null | undefined,
  moduleEntries: T[],
): T[] {
  return moduleEntries
    .filter((entry) => hasPageAccess(user, entry.id))
    .map((entry) => applyDisplayOverride<T>(user, entry))
}

/**
 * 功能：读取或查询 `getAccessibleAlarmEventTypes` 对应的页面权限逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `user`（AuthUser | null | undefined）：当前用户或待处理用户对象
 * 返回：string[] | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`getUserRole`、`getUserDepartments`、`includes`、`Set`、`entries`、`hasPageAccess`、`forEach`、`add`、`from`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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
