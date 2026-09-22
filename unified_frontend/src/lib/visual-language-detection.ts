import type { DepartmentId } from '@/auth/permissions'
import { apiGet, apiPost } from '@/lib/api'
import { getAiVisionFeatureConfig, saveAiVisionFeatureConfig } from '@/lib/aivision'

export const VISUAL_LANGUAGE_FEATURE = 'visual_language_detection'

export type VisualLanguageValue = {
  cap_interval: number
  jpeg_quality: number
  max_image_width: number
  max_tokens: number
  temperature: number
  top_p: number
  observation_prompt: string
}
export type VisualLanguageConfig = { enable: boolean; value: VisualLanguageValue }
export type VisualLanguageStatus = {
  processed_frames: number
  latest_result: string | null
  latest_result_at: string | null
  latency_seconds: number | null
  error: string | null
}
export type VisualLanguageEvent = {
  id: number
  kind: 'observation' | 'question' | 'error'
  text: string
  question: string | null
  captured_at: string
  latency_seconds: number | null
}
export type VideoAnswer = { text: string | null; latency_seconds: number; captured_at: string }

const cameraPath = (key: string, action: string, department: DepartmentId) =>
  `/visual-language-detection/cameras/${encodeURIComponent(key)}/${action}?department=${encodeURIComponent(department)}`

export const getVisualLanguageStatus = (key: string, department: DepartmentId, signal: AbortSignal) =>
  apiGet<VisualLanguageStatus>(cameraPath(key, 'status', department), { signal })

export const getVisualLanguageEvents = (key: string, department: DepartmentId, signal: AbortSignal) =>
  apiGet<{ items: VisualLanguageEvent[] }>(cameraPath(key, 'events', department), { signal })

export const askVideo = (key: string, department: DepartmentId, question: string, signal: AbortSignal) =>
  apiPost<VideoAnswer>(cameraPath(key, 'questions', department), { question }, { signal })

export async function getVisualLanguageConfig(cameraKey: string) {
  const response = await getAiVisionFeatureConfig(VISUAL_LANGUAGE_FEATURE, cameraKey)
  return response.config as VisualLanguageConfig
}

export async function saveVisualLanguageConfig(cameraKey: string, config: VisualLanguageConfig) {
  const response = await saveAiVisionFeatureConfig(VISUAL_LANGUAGE_FEATURE, cameraKey, config)
  return response.config as VisualLanguageConfig
}

export const VISUAL_LANGUAGE_PARAMETERS = [
  ['cap_interval', '帧发送间隔（秒）', 0.1, 300, 0.1],
  ['jpeg_quality', 'JPEG 质量', 1, 100, 1],
  ['max_image_width', '最大图像宽度（像素）', 160, 3840, 1],
  ['max_tokens', '最大输出 Token 数', 1, 8192, 1],
  ['temperature', '采样温度（temperature）', 0, 2, 0.1],
  ['top_p', '采样范围（top_p）', 0.01, 1, 0.01],
] as const
