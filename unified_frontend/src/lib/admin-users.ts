// 文件说明：实现`admin-users` 模块相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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

/**
 * 功能：读取或查询 `readError` 对应的`admin-users` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `response`（Response）：待读取或更新的 HTTP 响应
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`text`、`parse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：实现 `adminUserRequest` 对应的`admin-users` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `method`（'GET' | 'POST' | 'PATCH' | 'DELETE'）：`method` 对应的业务输入值
 *   - `path`（string）：目标路径
 *   - `body?`（unknown）：`body` 对应的业务输入值
 * 返回：Promise<T>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`fetch`、`stringify`、`dispatchEvent`、`Event`、`Error`、`readError`、`json`、`T`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
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

/**
 * 功能：读取或查询 `listAdminUsers` 对应的`admin-users` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/UserManagementSection.tsx` 的 `UserManagementSection` 调用本符号
 *   - 内部调用：`adminUserRequest`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export async function listAdminUsers() {
  const response = await adminUserRequest<{ items: AdminUser[] }>('GET', '')
  return response.items
}

/**
 * 功能：创建或构建 `createAdminUser` 对应的`admin-users` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `input`（CreateAdminUserInput）：`input` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/UserManagementSection.tsx` 的 `UserManagementSection` 调用本符号
 *   - 内部调用：`adminUserRequest`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export async function createAdminUser(input: CreateAdminUserInput) {
  const response = await adminUserRequest<{ success: boolean; user: AdminUser }>(
    'POST',
    '',
    input,
  )
  return response.user
}

/**
 * 功能：更新或保存 `updateAdminUser` 对应的`admin-users` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `employeeId`（string）：`employeeId` 对应业务对象的唯一标识
 *   - `input`（UpdateAdminUserInput）：`input` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/UserManagementSection.tsx` 的 `UserManagementSection` 调用本符号
 *   - 内部调用：`adminUserRequest`、`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：实现 `resetAdminUserPassword` 对应的`admin-users` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `employeeId`（string）：`employeeId` 对应业务对象的唯一标识
 *   - `newPassword`（string）：`newPassword` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/UserManagementSection.tsx` 的 `UserManagementSection` 调用本符号
 *   - 内部调用：`adminUserRequest`、`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：删除或清理 `deleteAdminUser` 对应的`admin-users` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `employeeId`（string）：`employeeId` 对应业务对象的唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/UserManagementSection.tsx` 的 `UserManagementSection` 调用本符号
 *   - 内部调用：`adminUserRequest`、`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export async function deleteAdminUser(employeeId: string) {
  await adminUserRequest<{ success: boolean }>(
    'DELETE',
    `/${encodeURIComponent(employeeId)}`,
  )
}
