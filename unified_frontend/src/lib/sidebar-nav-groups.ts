import { DEPARTMENT_LABELS, filterNavGroupsByPermission, getAccessibleDepartments, hasPageAccess } from '@/auth/permissions'
import { navGroups, type NavGroup } from '@/lib/nav'

export function buildSidebarNavGroups(user: Parameters<typeof filterNavGroupsByPermission>[0]): NavGroup[] {
  const visibleGroups = filterNavGroupsByPermission(user, navGroups)
  return visibleGroups.map((group) => group.id === 'modules' ? {
    ...group,
    items: [],
    // 功能必须在当前事业部分配，不能借用账号所属其他事业部的权限。
    children: getAccessibleDepartments(user).map((department) => ({
      id: department,
      department,
      label: DEPARTMENT_LABELS[department],
      items: group.items.filter((item) => hasPageAccess(user, item.id, department)),
    })).filter((child) => child.items.length > 0),
  } : group)
}
