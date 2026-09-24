import { apiGet, apiPut } from './api'
import type { DepartmentId } from '@/auth/permissions'

export const FEATURE_ACCESS_POLL_INTERVAL_MS = 30_000
export const FEATURE_ACCESS_TIMEOUT_MS = 10_000

export type FeatureAssignment = {
  department: DepartmentId
  features: string[]
  revision: number
}

export type FeatureSettings = {
  assignments: FeatureAssignment[]
  features: Array<{ name: string; display_name: string }>
}

export function getFeatureAccess(signal: AbortSignal) {
  return apiGet<Record<string, string[]>>('/departments/feature-access', { signal, cache: 'no-store' })
}

export function getFeatureSettings(signal: AbortSignal) {
  return apiGet<FeatureSettings>('/departments/feature-settings', { signal, cache: 'no-store' })
}

export function saveFeatureSettings(assignments: FeatureAssignment[]) {
  return apiPut<FeatureSettings>('/departments/feature-settings', { assignments })
}
