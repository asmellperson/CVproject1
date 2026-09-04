export type LogisticsCameraDraft = {
  name: string
  fps: string
  url: string
}

export type LogisticsCameraCreateInput = {
  name: string
  fps: number
  url: string
}

export const initialLogisticsCameraDraft: LogisticsCameraDraft = {
  name: '',
  fps: '5',
  url: '',
}

export function validateLogisticsCameraDraft(draft: LogisticsCameraDraft): string | null {
  if (!draft.name.trim()) return '请输入摄像头名称。'
  const fps = Number(draft.fps)
  if (!Number.isInteger(fps) || fps < 1) return 'FPS 必须是大于等于 1 的整数。'
  if (!draft.url.trim()) return '请输入 RTSP 地址。'
  return null
}

export function normalizeLogisticsCameraDraft(
  draft: LogisticsCameraDraft,
): LogisticsCameraCreateInput {
  const error = validateLogisticsCameraDraft(draft)
  if (error) throw new Error(error)
  return {
    name: draft.name.trim(),
    fps: Number(draft.fps),
    url: draft.url.trim(),
  }
}
