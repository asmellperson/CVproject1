import type { DepartmentId } from '@/auth/permissions'
import { apiUrl } from '@/lib/api'

export const FACE_FEATURE = 'recognize_face'

export type FaceIdentity = {
  bbox: [number, number, number, number]
  matched: boolean
  is_allowed: boolean
  person_id: number | null
  person_name: string
  job_no: string | null
  person_code: string | null
  org_index_code: string | null
  similarity: number
  type: 'face_identity'
}

export type FaceRecognitionStatus = {
  camera_key: string
  online: boolean
  count: number | null
  alarm: boolean
  reason: 'normal' | 'unauthorized' | 'unknown'
  updated_at: string | null
  frame_width: number | null
  frame_height: number | null
  detections: FaceIdentity[]
}

export type RecognitionRecord = {
  id: number
  camera_id: number
  person_id: number | null
  person_name: string
  similarity: number
  recognized_at: string
  image_path: string | null
  image_url: string | null
}

export type RecognitionRecordPage = { total: number; page: number; page_size: number; items: RecognitionRecord[] }

export type FacePerson = {
  id: number
  hik_source: 'one' | 'two'
  hik_person_id: string
  person_name: string | null
  job_no: string | null
  person_code: string | null
  org_index_code: string | null
  server_index_code: string | null
  pic_uri: string | null
  is_active: boolean
  is_allowed: boolean
  created_at: string
  updated_at: string
  last_synced_at: string
}

export type FacePersonPage = { total: number; page: number; page_size: number; items: FacePerson[] }

async function requestRecognition<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...options, credentials: 'include', cache: 'no-store',
  })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const payload = await response.json() as { detail?: unknown } | null
      if (typeof payload?.detail === 'string' && payload.detail.trim()) message += `：${payload.detail}`
    } catch {
      // 响应不是有效 JSON 时保留 HTTP 状态信息。
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export function getFaceRecognitionStatus(cameraKey: string, signal: AbortSignal) {
  return requestRecognition<FaceRecognitionStatus>(
    `features/${FACE_FEATURE}/cameras/${encodeURIComponent(cameraKey)}/status`, { signal },
  )
}

export function getRecognitionRecords(department: DepartmentId, page: number, cameraId: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ department, page: String(page), page_size: '20' })
  if (cameraId) params.set('camera_id', cameraId)
  return requestRecognition<RecognitionRecordPage>(`face-recognition/records?${params}`, { signal })
}

export type PersonPermissionsQuery = {
  page: number
  page_size: number
  keyword?: string
  source?: FacePerson['hik_source']
  is_active?: boolean
  is_allowed?: boolean
}

export type PersonPermissionsApi<Scope extends string = DepartmentId> = {
  list: (scope: Scope, query: PersonPermissionsQuery, signal?: AbortSignal) => Promise<FacePersonPage>
  update: (scope: Scope, personId: number, isAllowed: boolean, signal?: AbortSignal) => Promise<FacePerson>
}

export function createPersonPermissionsApi<Scope extends string = DepartmentId>(resource: 'face-recognition' | 'security-fence'): PersonPermissionsApi<Scope> {
  const personsPath = (scope: Scope) => resource === 'security-fence'
    ? `${resource}/cameras/${encodeURIComponent(scope)}/persons` : `${resource}/persons`
  return {
    list(scope, query, signal) {
      const params = new URLSearchParams({ page: String(query.page), page_size: String(query.page_size) })
      if (resource === 'face-recognition') params.set('department', scope)
      if (query.keyword) params.set('keyword', query.keyword)
      if (query.source) params.set('source', query.source)
      if (query.is_active !== undefined) params.set('is_active', String(query.is_active))
      if (query.is_allowed !== undefined) params.set('is_allowed', String(query.is_allowed))
      return requestRecognition<FacePersonPage>(`${personsPath(scope)}?${params}`, { signal })
    },
    update(scope, personId, isAllowed, signal) {
      const query = resource === 'face-recognition' ? `?${new URLSearchParams({ department: scope })}` : ''
      return requestRecognition<FacePerson>(`${personsPath(scope)}/${personId}${query}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_allowed: isAllowed }), signal,
      })
    },
  }
}

export const facePersonPermissionsApi = createPersonPermissionsApi('face-recognition')

export function recognitionImageUrl(path: string) {
  return apiUrl(path.replace(/^\/api\//, ''))
}
