import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
import { useFeatureConfigDraft } from '@/components/detection/useFeatureConfigDraft'
import { getAiVisionFeatureConfig, saveAiVisionFeatureConfig } from '@/lib/aivision'
import { validateHornBinding } from '@/lib/horn-alarm-binding'
import { INSPECTION_FEATURE, INSPECTION_PARAMETERS, type InspectionConfig } from '@/lib/security-inspection'

const read = async (key: string) => (await getAiVisionFeatureConfig(INSPECTION_FEATURE, key)).config as InspectionConfig
const write = async (key: string, config: InspectionConfig) => (await saveAiVisionFeatureConfig(INSPECTION_FEATURE, key, config)).config as InspectionConfig
const createDraft = (config: InspectionConfig) => config

export function validInspectionParameters(config: InspectionConfig) {
  return INSPECTION_PARAMETERS.every(([key, , min, max, step]) => Number.isFinite(config.value[key])
    && config.value[key] >= min && config.value[key] <= max && (step !== 1 || Number.isInteger(config.value[key])))
}

function buildConfig(config: InspectionConfig) {
  if (!validInspectionParameters(config)) throw new Error('请检查检测参数和报警间隔的范围。')
  const error = validateHornBinding(config.alarm.horn)
  if (error) throw new Error(error)
  return config
}

export function useInspectionConfig(cameraKey: string, configVersion: number) {
  const canConfigure = useDepartmentConfigAccess(undefined, INSPECTION_FEATURE)
  return useFeatureConfigDraft({ cameraKey, configVersion, canConfigure, read, write, createDraft, buildConfig })
}
