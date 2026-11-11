import type { DepartmentId } from '@/auth/permissions'
import { useCameraFeatureConfig } from '@/components/detection/useCameraFeatureConfig'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { FENCE_FEATURE, NUMBER_FIELDS, type FenceConfig, type NumberField } from './api'

export type FenceDraft = { config: FenceConfig; roi: string; numbers: Record<NumberField, string> }
const createDraft = (config: FenceConfig): FenceDraft => ({
  config,
  roi: JSON.stringify(config.value.roi_pos),
  numbers: Object.fromEntries(NUMBER_FIELDS.map(([key]) => [key, String(config.value[key])])) as Record<NumberField, string>,
})

function buildConfig(draft: FenceDraft): FenceConfig {
  const value = { ...draft.config.value, roi_pos: parseNormalizedRoi(draft.roi) }
  for (const [field, label, min, max, step] of NUMBER_FIELDS) {
    const number = Number(draft.numbers[field])
    if (!draft.numbers[field].trim() || !Number.isFinite(number) || number < min || (max !== undefined && number > max)
      || (['confirmation_frames', 'min_face_size'].includes(field) && step === 1 && !Number.isInteger(number))) {
      throw new Error(`${label}超出有效范围`)
    }
    value[field] = number
  }
  if (value.unknown_similarity_threshold >= value.similarity_threshold) throw new Error('未匹配判定阈值必须小于身份匹配阈值')
  return { ...draft.config, value }
}

export function useFenceConfig(department: DepartmentId, canConfigure: boolean) {
  return useCameraFeatureConfig({ feature: FENCE_FEATURE, department, canConfigure, createDraft, buildConfig })
}
