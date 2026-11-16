import { lazy, Suspense } from 'react'
import { MessageSquareText, Settings2 } from 'lucide-react'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { VISUAL_LANGUAGE_PARAMETERS, type VisualLanguageConfig } from '@/lib/visual-language-detection'
import { normalizeFeatureAlarmConfig } from '@/lib/alarm-config'
import { validVisualLanguageParameters, type useVisualLanguageConfig } from './useVisualLanguageConfig'

const AiVisionRoiEditor = lazy(() =>
  import('@/components/AiVisionRoiEditor').then((module) => ({ default: module.AiVisionRoiEditor })),
)

export function VisualLanguageConfiguration({ cameraKey, tab, state }: {
  cameraKey: string; tab: 'parameters' | 'prompt' | 'roi' | 'alarm'; state: ReturnType<typeof useVisualLanguageConfig>
}) {
  const { message, saving, disabled, save, canConfigure } = state
  if (!state.draft) return <p role="status" className="p-6 text-sm text-slate-500">{message || '正在读取配置…'}</p>
  const { config, roiJson } = state.draft
  const setConfig = (config: VisualLanguageConfig) => state.update((draft) => ({ ...draft, config }))
  const setRoiJson = (roiJson: string) => state.update((draft) => ({ ...draft, roiJson }))
  const valid = validVisualLanguageParameters(config)
  const saveMessage = message || (canConfigure ? '' : '当前账号仅可查看配置。')
  if (tab === 'roi') return <Suspense fallback={<p role="status" className="p-6 text-sm text-slate-500">正在加载 ROI 编辑器…</p>}>
    <AiVisionRoiEditor title="指令驱动智慧安防 ROI 绘制" cameraKey={cameraKey} roiJson={roiJson}
      disabled={disabled} saving={saving} message={saveMessage} onChange={setRoiJson} onSave={() => void save()} />
  </Suspense>
  if (tab === 'alarm') return <AlarmPushConfig alarm={config.alarm}
    alarmInterval={Number.isFinite(config.value.alarm_interval) ? String(config.value.alarm_interval) : ''}
    onAlarmIntervalChange={(value) => setConfig({ ...config, value: { ...config.value, alarm_interval: value === '' ? NaN : Number(value) } })}
    onChange={(alarm) => setConfig({ ...config, alarm: normalizeFeatureAlarmConfig(alarm) })}
    disabled={disabled} saving={saving} message={saveMessage} onSave={() => void save()} />
  return <div className="space-y-5">
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={tab === 'parameters' ? Settings2 : MessageSquareText} tone="blue"
        title={tab === 'parameters' ? '推理参数' : '监控指令'} />
      <DetectionConfigCardContent>
        {tab === 'parameters' ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {VISUAL_LANGUAGE_PARAMETERS.map(([key, label, min, max, step]) => <div key={key} className="space-y-2">
            <Label htmlFor={`visual-language-${key}`}>{label}</Label>
            <Input id={`visual-language-${key}`} type="number" min={min} max={max} step={step} disabled={disabled}
              value={Number.isFinite(config.value[key]) ? config.value[key] : ''}
              onChange={(event) => setConfig({ ...config, value: { ...config.value, [key]: event.target.value === '' ? NaN : Number(event.target.value) } })} />
          </div>)}
        </div> : <div className="space-y-2"><Label htmlFor="visual-language-prompt">监控指令</Label>
          <Textarea id="visual-language-prompt" rows={8} maxLength={8000} value={config.value.observation_prompt} disabled={disabled}
            onChange={(event) => setConfig({ ...config, value: { ...config.value, observation_prompt: event.target.value } })} />
        </div>}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={saveMessage}
      saving={saving} disabled={disabled || !valid} onSave={() => void save()} />
  </div>
}
