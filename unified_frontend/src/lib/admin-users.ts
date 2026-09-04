export type AdminUserRole = 'admin' | 'viewer'

export type AdminUserDepartment =
  | 'all'
  | 'general_electric'
  | 'research_institute'
  | 'electronics_electrician'
  | 'electrical_components'
  | 'precious_metal_recycling'
  | 'haoda_company'

export type AdminUser = {
  employee_id: string
  name: string
  role: AdminUserRole
  department: AdminUserDepartment
  departments: AdminUserDepartment[]
  enabled: boolean
  auth_version: number
}

export type CreateAdminUserInput = {
  employee_id: string
  name: string
  role: AdminUserRole
  departments: AdminUserDepartment[] | null
  password: string
}

export type UpdateAdminUserInput = {
  name: string
  role: AdminUserRole
  departments: AdminUserDepartment[] | null
  enabled: boolean
}

async function readError(response: Response) {
  const text = await response.text().catch(() => '')
  if (!text) return `${response.status} ${response.statusText}`
  try {
    const payload = JSON.parse(text) as { detail?: string; message?: string }
    return payload.detail || payload.message || text
  } catch {
    return text
  }
}

async function adminUserRequest<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api/admin/users${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<T>
}

export async function listAdminUsers() {
  const response = await adminUserRequest<{ items: AdminUser[] }>('GET', '')
  return response.items
}

export async function createAdminUser(input: CreateAdminUserInput) {
  const response = await adminUserRequest<{ success: boolean; user: AdminUser }>(
    'POST',
    '',
    input,
  )
  return response.user
}

export async function updateAdminUser(
  employeeId: string,
  input: UpdateAdminUserInput,
) {
  const response = await adminUserRequest<{ success: boolean; user: AdminUser }>(
    'PATCH',
    `/${encodeURIComponent(employeeId)}`,
    input,
  )
  return response.user
}

export async function resetAdminUserPassword(
  employeeId: string,
  newPassword: string,
) {
  const response = await adminUserRequest<{ success: boolean; user: AdminUser }>(
    'POST',
    `/${encodeURIComponent(employeeId)}/reset-password`,
    { new_password: newPassword },
  )
  return response.user
}

export async function deleteAdminUser(employeeId: string) {
  await adminUserRequest<{ success: boolean }>(
    'DELETE',
    `/${encodeURIComponent(employeeId)}`,
  )
}
