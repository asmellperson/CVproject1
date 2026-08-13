export type AccessAuditItem = {
  employee_id: string
  name: string
  role: string
  department: string | null
  first_seen_at: string
  last_seen_at: string
  visit_count: number
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
