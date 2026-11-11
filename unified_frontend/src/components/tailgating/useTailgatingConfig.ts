import type { DepartmentId } from '@/auth/permissions'
import { useCameraFeatureConfig } from '@/components/detection/useCameraFeatureConfig'
import { buildTailgatingConfig, createTailgatingDraft, TAILGATING_FEATURE } from './config'

export function useTailgatingConfig(department: DepartmentId, canConfigure: boolean) {
  return useCameraFeatureConfig({ feature: TAILGATING_FEATURE, department, canConfigure,
    createDraft: createTailgatingDraft, buildConfig: buildTailgatingConfig })
}
