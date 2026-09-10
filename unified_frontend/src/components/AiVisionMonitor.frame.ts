import { aiVisionFrameUrl } from '../lib/aivision'

export const PREVIEW_MAX_WIDTH = 960
export const PREVIEW_QUALITY = 72
export const FRAME_REQUEST_TIMEOUT_MS = 5000

type ScheduleTimeout = (callback: () => void, delay: number) => ReturnType<typeof setTimeout>

export function buildAiVisionPreviewFrameUrl(cameraKey: string, feature: string, nonce: number) {
  return aiVisionFrameUrl(cameraKey, feature, nonce, {
    maxWidth: PREVIEW_MAX_WIDTH,
    quality: PREVIEW_QUALITY,
  })
}

export function scheduleFrameRequestAbort(
  controller: AbortController,
  timeoutMs = FRAME_REQUEST_TIMEOUT_MS,
  schedule: ScheduleTimeout = setTimeout,
) {
  return schedule(() => controller.abort(), timeoutMs)
}
