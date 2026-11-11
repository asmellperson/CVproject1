import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { useFeatureConfigDraft } from '@/components/detection/useFeatureConfigDraft'
import { validateHornBinding } from '@/lib/horn-alarm-binding'
import { getVisualLanguageConfig, saveVisualLanguageConfig, VISUAL_LANGUAGE_PARAMETERS, type VisualLanguageConfig } from '@/lib/visual-language-detection'

type Draft = { config: VisualLanguageConfig; roiJson: string }
const createDraft = (config: VisualLanguageConfig): Draft => ({ config, roiJson: JSON.stringify(config.value.roi_pos) })

export function validVisualLanguageParameters(config: VisualLanguageConfig) {
  return config.value.observation_prompt.trim().length > 0
    && Number.isFinite(config.value.alarm_interval) && config.value.alarm_interval > 0
    && VISUAL_LANGUAGE_PARAMETERS.every(([key, , min, max, step]) => Number.isFinite(config.value[key])
      && config.value[key] >= min && config.value[key] <= max && (step !== 1 || Number.isInteger(config.value[key])))
}

function buildConfig({ config, roiJson }: Draft) {
  if (!validVisualLanguageParameters(config)) throw new Error('请填写有效的监控指令、推理参数和报警间隔。')
  const error = validateHornBinding(config.alarm.horn)
  if (error) throw new Error(error)
  return { ...config, value: { ...config.value, roi_pos: parseNormalizedRoi(roiJson) } }
}

export function useVisualLanguageConfig(cameraKey: string, configVersion: number) {
  const canConfigure = useDepartmentConfigAccess(undefined, 'visual_language_detection')
  return { ...useFeatureConfigDraft({ cameraKey, configVersion, canConfigure,
    read: getVisualLanguageConfig, write: saveVisualLanguageConfig, createDraft, buildConfig }), canConfigure }
}
