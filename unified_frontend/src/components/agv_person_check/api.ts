import { apiGet } from '@/lib/api'
import type { JsonValue } from './config'

export type AgvRequestStatus = {
  request_id: string
  camera_key: string
  mode: 'sync' | 'callback'
  state: 'detecting' | 'completed' | 'error' | 'cancelled'
  started_at: string
  finished_at: string | null
  duration_seconds: number
  sample_count: number
  sample_target: number
  person_present: boolean | null
  delivery_state: 'pending' | 'ready' | 'sending' | 'succeeded' | 'failed' | 'not_sent'
  delivery_status_code: number | null
  response_body: JsonValue
  error_code: string | null
  error: string | null
  delivery_error: string | null
}

export type AgvMonitorStatus = {
  camera_key: string
  state: 'waiting' | 'detecting' | 'returning' | 'offline' | 'disabled' | 'unavailable'
  active_request: AgvRequestStatus | null
  latest_result: AgvRequestStatus | null
}

export const getAgvRequestStatus = (key: string, signal: AbortSignal) =>
  apiGet<AgvMonitorStatus>(`/agv-person-check/cameras/${encodeURIComponent(key)}/status`, { signal, cache: 'no-store' })
