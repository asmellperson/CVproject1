export type CameraZoomCapabilities = {
  status: 'supported' | 'unsupported' | 'unknown'
  message: string
  channel_id: number | null
  zoom_in: boolean
  zoom_out: boolean
  minimum: number | null
  maximum: number | null
}

export type ZoomAction = 'in' | 'out' | 'stop'

export class CameraZoomError extends Error {
  readonly status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

async function request(cameraKey: string, feature: string, options: RequestInit) {
  const response = await fetch(`/api/cameras/${encodeURIComponent(cameraKey)}/zoom?${new URLSearchParams({ feature })}`, {
    ...options, credentials: 'include', cache: 'no-store',
  })
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
    const body = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new CameraZoomError(typeof body?.detail === 'string' ? body.detail : `镜头操作失败（${response.status}）`, response.status)
  }
  return response
}

export async function getCameraZoom(cameraKey: string, feature: string, signal: AbortSignal): Promise<CameraZoomCapabilities> {
  return (await request(cameraKey, feature, { signal })).json()
}

export async function controlCameraZoom(cameraKey: string, feature: string, action: ZoomAction,
  { keepalive = false, speedFraction }: { keepalive?: boolean; speedFraction?: number } = {}): Promise<void> {
  const response = await request(cameraKey, feature, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, speed_fraction: speedFraction }), keepalive,
  })
  const result = await response.json() as { action: ZoomAction; stopped: boolean }
  if (result.action !== action || result.stopped !== true) throw new Error('设备尚未确认停止变焦，请点击停止重试')
}
