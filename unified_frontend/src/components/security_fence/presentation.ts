import type { AlarmEvent } from '@/lib/api'
import { FENCE_FEATURE, type FencePerson } from './api'

export const FENCE_IDENTITY_LABELS = { pending: '身份待核验', allowed: '白名单', unauthorized: '非白名单' }
export const FENCE_REASON_LABELS: Record<string, string> = {
  forbidden_time: '异常时间出没', unauthorized: '异常人员出没', unknown_face: '异常人员出没（未知人员）',
}

type PersonIdentity = Pick<FencePerson, 'identity' | 'person_id' | 'person_name' | 'job_no' | 'org_index_code' | 'similarity'>
const text = (value: unknown) => typeof value === 'string' && value.trim() ? value : null

export function fenceAlarmPerson(alarm: AlarmEvent): PersonIdentity | null {
  if (alarm.feature_name !== FENCE_FEATURE) return null
  const person = alarm.metadata?.person
  if (!person || typeof person !== 'object' || Array.isArray(person) || !('identity' in person)) return null
  const identity = person.identity
  if (identity !== 'pending' && identity !== 'allowed' && identity !== 'unauthorized') return null
  return {
    identity,
    person_id: 'person_id' in person && typeof person.person_id === 'number' ? person.person_id : null,
    person_name: text('person_name' in person ? person.person_name : null),
    job_no: text('job_no' in person ? person.job_no : null),
    org_index_code: text('org_index_code' in person ? person.org_index_code : null),
    similarity: 'similarity' in person && typeof person.similarity === 'number' ? person.similarity : null,
  }
}

export function fencePersonName(person: Pick<PersonIdentity, 'identity' | 'person_id' | 'person_name'> | null) {
  if (!person || person.identity === 'pending') return '身份待核验'
  return person.person_name || (person.person_id == null ? '未知人员' : `人员 #${person.person_id}`)
}

export function alarmReasonText(alarm: AlarmEvent) {
  return alarm.feature_name === FENCE_FEATURE ? FENCE_REASON_LABELS[alarm.reason] || alarm.reason : alarm.reason
}
