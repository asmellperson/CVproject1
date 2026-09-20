import { parseNormalizedRoi, type NormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import type { NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'

export const AGV_FEATURE = 'agv_person_check'

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
type ResultValue = string | number | boolean | null

export type AgvConfig = {
  enable: boolean
  alarm: NormalizedFeatureAlarmConfig
  value: {
    alarm_interval: number
    roi_pos: NormalizedRoi
    confidence_threshold: number
    iou_threshold: number
    sample_count: number
    cap_interval: number
    request_timeout_seconds: number
    inference_timeout_seconds: number
    frame_max_age_seconds: number
    http: {
      mode: 'sync' | 'callback'
      method: 'GET' | 'POST'
      callback_url: string
      headers: Record<string, string>
      body_template: JsonValue
      present_value: ResultValue
      absent_value: ResultValue
      timeout_seconds: number
    }
  }
}

export const AGV_NUMBER_FIELDS = [
  { key: 'confidence_threshold', label: '人体检测置信度', min: 0, max: 1, step: 0.05 },
  { key: 'request_timeout_seconds', label: '检测时长上限（秒）', min: 0, max: 60, step: 0.1 },
  { key: 'sample_count', label: '采样帧数', min: 2, max: 30, step: 1 },
  { key: 'cap_interval', label: '采样间隔（秒）', min: 0.05, max: 5, step: 0.05 },
  { key: 'iou_threshold', label: '人体检测 IOU 阈值', min: 0, max: 1, step: 0.05 },
  { key: 'inference_timeout_seconds', label: '单帧推理超时（秒）', min: 0, max: 2, step: 0.1 },
  { key: 'frame_max_age_seconds', label: '画面最大有效时长（秒）', min: 0, max: 5, step: 0.1 },
] as const

type NumberField = typeof AGV_NUMBER_FIELDS[number]['key']

export type AgvForm = {
  alarm: NormalizedFeatureAlarmConfig
  alarmInterval: string
  roiJson: string
  parameters: Record<NumberField, string>
  http: Omit<AgvConfig['value']['http'], 'headers' | 'body_template' | 'present_value' | 'absent_value' | 'timeout_seconds'> & {
    headers: string
    body_template: string
    present_value: string
    absent_value: string
    timeout_seconds: string
  }
}

export function toAgvForm(config: AgvConfig): AgvForm {
  const http = config.value.http
  return {
    alarm: config.alarm,
    alarmInterval: String(config.value.alarm_interval),
    roiJson: JSON.stringify(config.value.roi_pos),
    parameters: Object.fromEntries(AGV_NUMBER_FIELDS.map(({ key }) => [key, String(config.value[key])])) as AgvForm['parameters'],
    http: {
      ...http,
      headers: JSON.stringify(http.headers, null, 2),
      body_template: JSON.stringify(http.body_template, null, 2),
      present_value: http.present_value === null ? '' : JSON.stringify(http.present_value),
      absent_value: http.absent_value === null ? '' : JSON.stringify(http.absent_value),
      timeout_seconds: String(http.timeout_seconds),
    },
  }
}

function parseJson(text: string, label: string): JsonValue {
  try {
    return JSON.parse(text, (_key, value: unknown) => {
      if (typeof value === 'number' && !Number.isFinite(value)) throw new Error('数值必须有限')
      return value
    }) as JsonValue
  } catch {
    throw new Error(`${label} 必须是有效 JSON。`)
  }
}

function parseResult(text: string, label: string): ResultValue {
  if (!text.trim()) return null
  const value = parseJson(text, label)
  if (!['string', 'number', 'boolean'].includes(typeof value) || (typeof value === 'number' && !Number.isFinite(value))) {
    throw new Error(`${label} 只支持数字、布尔值或带双引号的文本。`)
  }
  return value as Exclude<ResultValue, null>
}

export function toAgvConfig(form: AgvForm, current: AgvConfig): AgvConfig {
  const parameters = { ...current.value }
  for (const { key, label, min, max } of AGV_NUMBER_FIELDS) {
    const value = Number(form.parameters[key])
    if (!form.parameters[key].trim() || !Number.isFinite(value) || value < min || value > max
      || (key.endsWith('_seconds') && value <= 0) || (key === 'sample_count' && !Number.isInteger(value))) {
      throw new Error(`${label} 必须在 ${min}～${max} 范围内${key.endsWith('_seconds') ? '且大于 0' : ''}${key === 'sample_count' ? '，并且为整数' : ''}。`)
    }
    parameters[key] = value
  }
  if (parameters.request_timeout_seconds <= (parameters.sample_count - 1) * parameters.cap_interval + parameters.inference_timeout_seconds) {
    throw new Error('检测时长上限必须大于「采样帧数减一 × 采样间隔 + 单帧推理超时」。')
  }
  const headers = parseJson(form.http.headers, 'Headers')
  if (!headers || typeof headers !== 'object' || Array.isArray(headers) || Object.values(headers).some((value) => typeof value !== 'string')) {
    throw new Error('Headers 必须是名称和值均为字符串的 JSON 对象。')
  }
  const presentValue = parseResult(form.http.present_value, '有人返回值')
  const absentValue = parseResult(form.http.absent_value, '无人返回值')
  if (presentValue !== null && presentValue === absentValue) throw new Error('有人返回值和无人返回值必须不同。')
  const callbackUrl = form.http.callback_url.trim()
  if (callbackUrl) {
    let url: URL
    try { url = new URL(callbackUrl) } catch { throw new Error('请填写有效的 HTTP/HTTPS 回调 URL。') }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash) {
      throw new Error('回调 URL 必须使用 HTTP/HTTPS，且不包含账号密码或 URL 片段。')
    }
  }
  const timeout = Number(form.http.timeout_seconds)
  if (!form.http.timeout_seconds.trim() || !Number.isFinite(timeout) || timeout <= 0 || timeout > 10) {
    throw new Error('回调超时必须大于 0 且不超过 10 秒。')
  }
  const alarmInterval = Number(form.alarmInterval)
  if (!form.alarmInterval.trim() || !Number.isFinite(alarmInterval) || alarmInterval <= 0) {
    throw new Error('报警间隔必须大于 0 秒。')
  }
  return {
    enable: current.enable,
    alarm: form.alarm,
    value: {
      ...parameters,
      alarm_interval: alarmInterval,
      roi_pos: parseNormalizedRoi(form.roiJson),
      http: {
        ...form.http,
        callback_url: callbackUrl,
        headers: headers as Record<string, string>,
        body_template: parseJson(form.http.body_template, 'JSON Body 模板'),
        present_value: presentValue,
        absent_value: absentValue,
        timeout_seconds: timeout,
      },
    },
  }
}
