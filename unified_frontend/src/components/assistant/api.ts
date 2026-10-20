import { apiUrl } from '@/lib/api'
import type { DepartmentId } from '@/auth/permissions'
import type { AssistantConversation, AssistantModelSettings, AssistantSession, AssistantTurn } from './types'

async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(`/assistant${path}`), {
    method, credentials: 'include', signal,
    headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string | Array<{ msg: string }> } | null
    const detail = payload?.detail
    // 校验响应中的 input 可能含用户输入的凭据，只显示可读错误信息。
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item) => item.msg).join('；') : `请求失败（HTTP ${response.status}）`)
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

export const listAssistantSessions = (department: DepartmentId | null, signal?: AbortSignal) => request<AssistantSession[]>(`/sessions${department ? `?department=${department}` : ''}`, 'GET', undefined, signal)
export const createAssistantSession = (department: DepartmentId | null, signal?: AbortSignal) => request<AssistantSession>('/sessions', 'POST', { department }, signal)
export const getAssistantConversation = (id: string, signal?: AbortSignal) => request<AssistantConversation>(`/sessions/${id}`, 'GET', undefined, signal)
export const sendAssistantMessage = (id: string, body: { request_id: string; text: string }, signal?: AbortSignal) => request<AssistantTurn>(`/sessions/${id}/messages`, 'POST', body, signal)
export const cancelAssistantTurn = (sessionId: string, turnId: number, signal?: AbortSignal) => request<void>(`/sessions/${sessionId}/turns/${turnId}/cancel`, 'POST', undefined, signal)
export const getAssistantSettings = (signal?: AbortSignal) => request<AssistantModelSettings>('/settings', 'GET', undefined, signal)
export const saveAssistantSettings = (body: AssistantModelSettings, signal?: AbortSignal) => request<AssistantModelSettings>('/settings', 'PUT', body, signal)
