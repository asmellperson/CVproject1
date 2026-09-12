import { AIVISION_URL } from '@/lib/aivision'

export const FACE_FEATURE = 'recognize_face'
export const FACE_DEPARTMENT = 'electronics_electrician'

export type FaceIdentity = {
  bbox: [number, number, number, number]
  matched: boolean
  person_id: number | null
  person_name: string
  similarity: number
  type: 'face_identity'
}

export type FaceRecognitionStatus = {
  camera_key: string
  online: boolean
  count: number | null
  reason: 'normal' | 'unknown'
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
}

export type RecognitionRecordPage = { total: number; page: number; page_size: number; items: RecognitionRecord[] }

async function readRecognitionResponse<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${AIVISION_URL.replace(/\/$/, '')}/api/${path}`, {
    credentials: 'include', cache: 'no-store', signal,
  })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) throw new Error(`读取失败（HTTP ${response.status}）`)
  return response.json() as Promise<T>
}

export function getFaceRecognitionStatus(cameraKey: string, signal: AbortSignal) {
  return readRecognitionResponse<FaceRecognitionStatus>(
    `features/${FACE_FEATURE}/cameras/${encodeURIComponent(cameraKey)}/status`, signal,
  )
}

export function getRecognitionRecords(page: number, cameraId: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  if (cameraId) params.set('camera_id', cameraId)
  return readRecognitionResponse<RecognitionRecordPage>(`face-recognition/records?${params}`, signal)
}
