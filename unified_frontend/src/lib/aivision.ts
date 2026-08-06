function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, '')
}

const PUBLIC_ORIGIN = trimTrailingSlash((import.meta.env.VITE_PUBLIC_ORIGIN as string | undefined) || '')

export const AIVISION_URL =
  (import.meta.env.VITE_AIVISION_URL as string | undefined) ||
  (PUBLIC_ORIGIN ? `${PUBLIC_ORIGIN}/aivision/` : '/aivision/')

export type AiVisionCamera = {
  id: string
  name: string
  shm_name: string
  url: string
  camera_id: number
  fps?: number
  enabled: boolean
  functions: Record<string, boolean> | string[]
  department?: string | null
}

export type AiVisionDepartment = {
  name: string
  display_name: string
}

export type AiVisionFeatureMeta = {
  name: string
  display_name: string
  required_models: string[]
  violation_type: number
  config_schema: Record<string, unknown>
  departments: string[]
}

export type CreateAiVisionCameraPayload = {
  name: string
  url: string
  shm_name: string
  fps?: number
  max_restart?: number
  enabled?: boolean
  department?: string | null
}

export type UpdateAiVisionCameraPayload = Partial<Pick<CreateAiVisionCameraPayload, 'name' | 'url' | 'fps' | 'max_restart' | 'enabled' | 'department'>>

export type AiVisionExceptionAlertSettings = {
  wechat_enable: boolean
  wechat_user: string
}

export type AiVisionModel = {
  id: number
  name: string
  type: string
  path: string
  import_path?: string | null
  description?: string | null
  enable: boolean
}

export type CreateAiVisionModelPayload = Pick<AiVisionModel, 'name' | 'type' | 'path'> &
  Partial<Pick<AiVisionModel, 'import_path' | 'description' | 'enable'>>

export type AiVisionFeatureConfig = {
  enable: boolean
  value: Record<string, unknown>
  alarm?: unknown
}

export type AiVisionLogisticsSinglePersonStatus = {
  camera_key: string
  feature: 'detect_logistics_single_person'
  online: boolean
  count: number | null
  alarm: boolean
  reason: 'normal' | 'empty' | 'multiple' | 'unknown'
  updated_at: string | null
}

type AiVisionFeatureConfigResponse = {
  camera: {
    id: number
    name: string
    shm_name: string
    enable: boolean
  }
  feature: string
  config: AiVisionFeatureConfig
}

type AiVisionCamerasResponse = {
  cameras: AiVisionCamera[]
} | AiVisionCamera[]

async function readAiVisionError(response: Response) {
  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  let detail = await response.text().catch(() => '')
  try {
    const parsed = JSON.parse(detail) as { detail?: string }
    detail = parsed.detail || detail
  } catch {
    // Keep the raw response text when it is not JSON.
  }
  return detail || `${response.status} ${response.statusText}`
}

export async function getAiVisionCameras(department?: string) {
  const params = new URLSearchParams()
  if (department) params.set('department', department)
  const query = params.toString()
  const response = await fetch(`/api/aivision/cameras${query ? `?${query}` : ''}`, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const payload = (await response.json()) as AiVisionCamerasResponse
  return Array.isArray(payload) ? payload : payload.cameras || []
}

export async function getAiVisionLogisticsSinglePersonStatus(cameraKey: string) {
  const response = await fetch(
    `/api/aivision/cameras/${encodeURIComponent(cameraKey)}/features/detect_logistics_single_person/status`,
    { credentials: 'include' },
  )
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionLogisticsSinglePersonStatus
}

export async function getAiVisionDepartments() {
  const response = await fetch('/api/aivision/departments', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionDepartment[]
}

export async function getAiVisionDepartmentFeatures(departmentName: string) {
  const response = await fetch(`/api/aivision/departments/${encodeURIComponent(departmentName)}/features`, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as Array<{ name: string; display_name: string }>
}

export function getAiVisionCameraKey(camera: AiVisionCamera) {
  return camera.shm_name || camera.id || String(camera.camera_id)
}

export function isAiVisionFeatureEnabled(camera: AiVisionCamera, feature: string) {
  const functions = camera.functions
  if (Array.isArray(functions)) {
    return functions.includes(feature)
  }
  return Boolean(functions?.[feature])
}

export type AiVisionFrameOptions = {
  maxWidth?: number
  maxHeight?: number
  quality?: number
}

export function aiVisionFrameUrl(cameraKey: string, feature?: string, nonce?: number, options: AiVisionFrameOptions = {}) {
  const params = new URLSearchParams()
  if (feature) params.set('feature', feature)
  if (nonce) params.set('t', String(nonce))
  if (options.maxWidth) params.set('max_width', String(options.maxWidth))
  if (options.maxHeight) params.set('max_height', String(options.maxHeight))
  if (options.quality) params.set('quality', String(options.quality))
  const query = params.toString()
  return `/api/aivision/cameras/${encodeURIComponent(cameraKey)}/frame.jpg${query ? `?${query}` : ''}`
}

export async function createAiVisionCamera(payload: CreateAiVisionCameraPayload) {
  const response = await fetch('/api/aivision/cameras', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  return camera
}

export async function updateAiVisionCamera(cameraKey: string, payload: UpdateAiVisionCameraPayload) {
  const response = await fetch(`/api/aivision/cameras/${encodeURIComponent(cameraKey)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  return camera
}

export async function deleteAiVisionCamera(cameraKey: string) {
  const response = await fetch(`/api/aivision/cameras/${encodeURIComponent(cameraKey)}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  window.dispatchEvent(new Event('aivision:cameras-changed'))
  return (await response.json()) as { ok: boolean }
}

export async function getAiVisionExceptionAlertSettings() {
  const response = await fetch('/api/v2/runtime/exception-alert', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionExceptionAlertSettings
}

export async function saveAiVisionExceptionAlertSettings(payload: AiVisionExceptionAlertSettings) {
  const response = await fetch('/api/v2/runtime/exception-alert', {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionExceptionAlertSettings
}

export async function getAiVisionFeatureConfig(feature: string, cameraKey: string) {
  const response = await fetch(`/api/v2/features/${encodeURIComponent(feature)}/configs/${encodeURIComponent(cameraKey)}`, {
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionFeatureConfigResponse
}

export async function saveAiVisionFeatureConfig(feature: string, cameraKey: string, config: AiVisionFeatureConfig) {
  const response = await fetch(`/api/v2/features/${encodeURIComponent(feature)}/configs/${encodeURIComponent(cameraKey)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  window.dispatchEvent(new Event('aivision:cameras-changed'))
  return (await response.json()) as AiVisionFeatureConfigResponse
}

export async function getAiVisionModels() {
  const response = await fetch('/api/aivision/models', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModel[]
}

export async function updateAiVisionModel(modelId: number, payload: Partial<Pick<AiVisionModel, 'path'>>) {
  const response = await fetch(`/api/aivision/models/${encodeURIComponent(String(modelId))}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModel
}

export async function createAiVisionModel(payload: CreateAiVisionModelPayload) {
  const response = await fetch('/api/aivision/models', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModel
}
