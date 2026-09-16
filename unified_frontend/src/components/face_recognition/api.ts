import { AIVISION_URL } from '@/lib/aivision'

export const FACE_FEATURE = 'recognize_face'
export const FACE_DEPARTMENT = 'electronics_electrician'

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
  const response = await fetch(`${AIVISION_URL.replace(/\/$/, '')}/api/${path}`, {
    ...options, credentials: 'include', cache: 'no-store',
  })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) throw new Error(`请求失败（HTTP ${response.status}）`)
  return response.json() as Promise<T>
}

export function getFaceRecognitionStatus(cameraKey: string, signal: AbortSignal) {
  return requestRecognition<FaceRecognitionStatus>(
    `features/${FACE_FEATURE}/cameras/${encodeURIComponent(cameraKey)}/status`, { signal },
  )
}

export function getRecognitionRecords(page: number, cameraId: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  if (cameraId) params.set('camera_id', cameraId)
  return requestRecognition<RecognitionRecordPage>(`face-recognition/records?${params}`, { signal })
}

export function getFacePersons(query: {
  page: number
  page_size: number
  keyword?: string
  source?: FacePerson['hik_source']
  is_active?: boolean
  is_allowed?: boolean
}, signal?: AbortSignal) {
  const params = new URLSearchParams({ page: String(query.page), page_size: String(query.page_size) })
  if (query.keyword) params.set('keyword', query.keyword)
  if (query.source) params.set('source', query.source)
  if (query.is_active !== undefined) params.set('is_active', String(query.is_active))
  if (query.is_allowed !== undefined) params.set('is_allowed', String(query.is_allowed))
  return requestRecognition<FacePersonPage>(`face-recognition/persons?${params}`, { signal })
}

export function updateFacePerson(personId: number, isAllowed: boolean, signal?: AbortSignal) {
  return requestRecognition<FacePerson>(`face-recognition/persons/${personId}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_allowed: isAllowed }), signal,
  })
}

export function recognitionImageUrl(path: string) {
  return `${AIVISION_URL.replace(/\/$/, '')}${path}`
}
