// 文件说明：实现`access-audit` 模块相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export type AccessAuditItem = {
  employee_id: string
  name: string
  role: string
  department: string | null
  first_seen_at: string
  last_seen_at: string
  visit_count: number
}

/**
 * 功能：读取或查询 `readError` 对应的`access-audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
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
 * 功能：读取或查询 `listAccessAudit` 对应的`access-audit` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `limit`（未显式标注）：返回或处理的最大记录数；声明包含默认值 `100`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AccessAuditSection.tsx` 的 `AccessAuditSection` 调用本符号
 *   - 内部调用：`fetch`、`encodeURIComponent`、`String`、`dispatchEvent`、`Event`、`Error`、`readError`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
export async function listAccessAudit(limit = 100) {
  const response = await fetch(
    `/api/admin/access-audit?limit=${encodeURIComponent(String(limit))}`,
    {
      method: 'GET',
      credentials: 'include',
    },
  )
  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const payload = (await response.json()) as { items: AccessAuditItem[] }
  return payload.items
}
