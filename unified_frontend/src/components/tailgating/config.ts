import { parseNormalizedRoi, type NormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { normalizeFeatureAlarmConfig, type NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'

export const TAILGATING_FEATURE = 'tailgating'
export const NUMBER_FIELDS = [
  ['overlap_seconds', '共同出现确认时间（秒）', 0.1, 5, 0.1],
  ['crossing_window_seconds', '共同出现结束后的关联窗口（秒）', 0.5, 10, 0.1],
  ['max_frame_gap_seconds', '允许的最大检测间隔（秒）', 0.2, 3, 0.1],
  ['cap_interval', '检测间隔（秒）', 0.05, 0.5, 0.05],
  ['threshold', '人体检测置信度', 0.01, 1, 0.01],
  ['foot_ratio', '人体脚底参考点比例', 0.5, 1, 0.01],
  ['alarm_interval', '报警间隔（秒）', 1, undefined, 1],
] as const
type NumberField = typeof NUMBER_FIELDS[number][0]

export type TailgatingConfig = {
  enable: boolean
  value: Record<NumberField, number> & { roi_pos: NormalizedRoi; line_points: NormalizedRoi; direction: -1 | 0 | 1 }
  alarm: NormalizedFeatureAlarmConfig
}
export type TailgatingDraft = {
  config: TailgatingConfig
  roi: string
  line: string
  numbers: Record<NumberField, string>
}

export function createTailgatingDraft(config: TailgatingConfig): TailgatingDraft {
  return { config: { ...config, alarm: normalizeFeatureAlarmConfig(config.alarm) },
    roi: JSON.stringify(config.value.roi_pos), line: JSON.stringify(config.value.line_points),
    numbers: Object.fromEntries(NUMBER_FIELDS.map(([key]) => [key, String(config.value[key])])) as Record<NumberField, string> }
}

export function buildTailgatingConfig(draft: TailgatingDraft): TailgatingConfig {
  const value = { ...draft.config.value, roi_pos: parseNormalizedRoi(draft.roi), line_points: parseNormalizedRoi(draft.line, 'line') }
  for (const [field, label, min, max] of NUMBER_FIELDS) {
    const number = Number(draft.numbers[field])
    if (!draft.numbers[field].trim() || !Number.isFinite(number) || number < min || (max !== undefined && number > max)) {
      throw new Error(`${label}超出有效范围`)
    }
    value[field] = number
  }
  if (value.max_frame_gap_seconds <= value.cap_interval) throw new Error('允许采样间隔必须大于检测间隔')
  if (value.crossing_window_seconds < value.overlap_seconds) throw new Error('通行关联窗口不能小于共同出现确认时间')
  return { ...draft.config, value }
}
