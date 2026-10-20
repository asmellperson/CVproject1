import type { DepartmentId } from '@/auth/permissions'

export type AssistantSession = { id: string; title: string; department: DepartmentId | null; created_at: string; updated_at: string }
export type AssistantAction = {
  id: string
  resource: { key: string; kind: string; name: string; department: DepartmentId | null; feature: string | null }
  status: 'executing' | 'saved' | 'failed' | 'unknown' | 'changed'
  before: Record<string, unknown>
  after: Record<string, unknown> | null
  changes: Record<string, unknown>
  detail: string
  created_at: string
}
export type AssistantTurn = {
  id: number; request_id: string; question: string; answer: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  progress: string; actions: AssistantAction[]; created_at: string
}
export type AssistantConversation = { session: AssistantSession; turns: AssistantTurn[]; hidden_turns: number }
export type AssistantModelSettings = { base_url: string; model: string; max_tokens: number; temperature: number; api_timeout_sec: number }
export const isTurnActive = (turn: AssistantTurn) => turn.status === 'queued' || turn.status === 'running'
