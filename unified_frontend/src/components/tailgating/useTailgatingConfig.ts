import type { DepartmentId } from '@/auth/permissions'
import { useCameraFeatureConfig } from '@/components/detection/useCameraFeatureConfig'
import { buildTailgatingConfig, createTailgatingDraft, TAILGATING_FEATURE } from './config'

export function useTailgatingConfig(department: DepartmentId, isAdmin: boolean) {
  return useCameraFeatureConfig({ feature: TAILGATING_FEATURE, department, isAdmin,
    createDraft: createTailgatingDraft, buildConfig: buildTailgatingConfig })
}
