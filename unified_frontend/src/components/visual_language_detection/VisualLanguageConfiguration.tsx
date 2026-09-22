import { useEffect, useRef, useState } from 'react'
import { MessageSquareText, Settings2 } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { getVisualLanguageConfig, saveVisualLanguageConfig, VISUAL_LANGUAGE_PARAMETERS, type VisualLanguageConfig } from '@/lib/visual-language-detection'

export function VisualLanguageConfiguration({ cameraKey, tab }: { cameraKey: string; tab: 'parameters' | 'prompt' }) {
  const { isAdmin } = useAuth()
  const [config, setConfig] = useState<VisualLanguageConfig | null>(null)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const operation = useRef(0)
  const savingRef = useRef(false)
  useEffect(() => {
    const version = ++operation.current
    getVisualLanguageConfig(cameraKey).then((result) => {
      if (version === operation.current) setConfig(result)
    }).catch((cause: unknown) => {
      if (version === operation.current) setMessage(`读取失败：${String(cause)}`)
    })
    return () => { operation.current += 1 }
  }, [cameraKey])

  const save = async () => {
    if (!config || !isAdmin || savingRef.current) return
    const version = operation.current
    savingRef.current = true
    setSaving(true); setMessage('')
    try {
      const next = await saveVisualLanguageConfig(cameraKey, config)
      if (version === operation.current) { setConfig(next); setMessage('配置已保存并生效') }
    } catch (cause) {
      if (version === operation.current) setMessage(`保存失败：${String(cause)}`)
    } finally {
      savingRef.current = false
      if (version === operation.current) setSaving(false)
    }
  }
  if (!config) return <p role="status" className="p-6 text-sm text-slate-500">{message || '正在读取配置…'}</p>
  const disabled = !isAdmin || saving
  const valid = config.value.observation_prompt.trim().length > 0 && VISUAL_LANGUAGE_PARAMETERS.every(([key, , min, max, step]) =>
    Number.isFinite(config.value[key]) && config.value[key] >= min && config.value[key] <= max && (step !== 1 || Number.isInteger(config.value[key])))
  return <div className="space-y-5">
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={tab === 'parameters' ? Settings2 : MessageSquareText} tone="blue"
        title={tab === 'parameters' ? '推理参数' : '观察提示词'} description="配置按摄像头独立保存，保存后自动用于后续视频理解。" />
      <DetectionConfigCardContent>
        {tab === 'parameters' ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {VISUAL_LANGUAGE_PARAMETERS.map(([key, label, min, max, step]) => <div key={key} className="space-y-2">
            <Label htmlFor={`visual-language-${key}`}>{label}</Label>
            <Input id={`visual-language-${key}`} type="number" min={min} max={max} step={step} disabled={disabled}
              value={Number.isFinite(config.value[key]) ? config.value[key] : ''}
              onChange={(event) => setConfig({ ...config, value: { ...config.value, [key]: event.target.value === '' ? NaN : Number(event.target.value) } })} />
          </div>)}
        </div> : <div className="space-y-2"><Label htmlFor="visual-language-prompt">观察提示词</Label>
          <Textarea id="visual-language-prompt" rows={8} maxLength={8000} value={config.value.observation_prompt} disabled={disabled}
            onChange={(event) => setConfig({ ...config, value: { ...config.value, observation_prompt: event.target.value } })} />
        </div>}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={message || (isAdmin ? '参数和提示词仅作用于当前摄像头。' : '当前账号可查看配置，修改需要管理员权限。')}
      saving={saving} disabled={disabled || !valid} onSave={() => void save()} />
  </div>
}
