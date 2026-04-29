function readError(response: Response) {
  return response.text().then((text) => {
    if (!text) return `${response.status} ${response.statusText}`
    try {
      const parsed = JSON.parse(text) as { detail?: string; message?: string }
      return parsed.detail || parsed.message || text
    } catch {
      return text
    }
  })
}

async function securityVlmGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/security-vlm${path}`, {
    ...init,
    method: 'GET',
    credentials: 'include',
    headers: {
      ...(init?.headers || {}),
    },
  })

  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<T>
}

async function securityVlmPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const response = await fetch(`/security-vlm${path}`, {
    ...init,
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<T>
}

export type SecurityVlmWorkerStatus = {
  ok?: boolean
  width?: number
  height?: number
  fps?: number
  [key: string]: unknown
}

export type SecurityVlmStats = {
  total?: number
  compliant?: number
  non_compliant?: number
  error?: number
  rate?: number
  queue?: number
  budget?: {
    spent_yuan?: number
    daily_limit_yuan?: number
  }
}

export type SecurityVlmHistoryItem = {
  time?: string
  session_id?: string
  roi_name?: string
  duration_sec?: number
  status?: 'compliant' | 'non_compliant' | 'error' | string
  upper_checked?: boolean | null
  middle_checked?: boolean | null
  lower_checked?: boolean | null
  arms_open?: boolean | null
  reason?: string
  error?: string
}

export type SecurityVlmHealth = {
  running?: boolean
  ts?: number
  capture?: SecurityVlmWorkerStatus
  detector?: SecurityVlmWorkerStatus
  session?: SecurityVlmWorkerStatus
  vlm?: SecurityVlmWorkerStatus
  stats?: SecurityVlmStats
  history?: SecurityVlmHistoryItem[]
  staff_rois?: Record<string, number[]>
}

export type SecurityVlmRoisResponse = {
  staff_rois: Record<string, number[]>
  available_slots: string[]
  video_id?: string
  ok?: boolean
}

export const getSecurityVlmHealth = () => securityVlmGet<SecurityVlmHealth>('/health')

export const getSecurityVlmHistory = (limit = 100) =>
  securityVlmGet<{ date?: string; stats?: SecurityVlmStats; history?: SecurityVlmHistoryItem[] }>(`/api/history?limit=${limit}`)

export const getSecurityVlmRois = () => securityVlmGet<SecurityVlmRoisResponse>('/api/rois')

export const saveSecurityVlmRois = (staff_rois: Record<string, number[]>) =>
  securityVlmPost<SecurityVlmRoisResponse>('/api/rois', { staff_rois })

export const securityVlmVideoUrl = (kind: 'original' | 'rule', nonce?: number) =>
  `/security-vlm/video/${kind}${nonce ? `?t=${nonce}` : ''}`
