import { useEffect, useState } from 'react'
import { Settings2 } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardHeader, DetectionConfigCardContent, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { VLM_PARAMETERS, getVlmSettings, saveVlmSettings, type VlmSettings } from '@/lib/security-inspection'

export function InspectionModelConfig() {
  const { isAdmin } = useAuth()
  const [settings, setSettings] = useState<VlmSettings | null>(null)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (!isAdmin) return
    let active = true
    getVlmSettings().then((value) => { if (active) setSettings(value) })
      .catch((cause: unknown) => { if (active) setMessage(`读取失败：${String(cause)}`) })
    return () => { active = false }
  }, [isAdmin])
  const invalid = !settings || VLM_PARAMETERS.some(([key, , min, max, step]) => !Number.isFinite(settings[key])
    || settings[key] < min || settings[key] > max || (step === 1 && !Number.isInteger(settings[key])))
  const save = async () => {
    if (!isAdmin || !settings || saving || invalid) return
    setSaving(true)
    try {
      const result = await saveVlmSettings(settings)
      setSettings(result.settings)
      setMessage(result.vlm.reachable === false ? `设置已保存；${result.vlm.last_error}`
        : result.vlm.reachable === true ? '设置已保存，福达AI接口可达' : '设置已保存，正在检查福达AI连接')
    } catch (cause) { setMessage(`保存失败：${String(cause)}`) }
    finally { setSaving(false) }
  }
  if (!isAdmin) return <p className="p-6 text-sm text-slate-500 dark:text-slate-400">全平台模型设置仅管理员可查看和修改。</p>
  return <div className="space-y-6">
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Settings2} tone="blue" title="福达AI判定设置" description="全平台共用，保存后作用于所有部门和摄像头。" />
      <DetectionConfigCardContent>
        {settings ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(['base_url', 'model'] as const).map((key) => <div key={key} className="space-y-2"><Label htmlFor={`vlm-${key}`}>{key === 'base_url' ? '模型接口地址' : '模型名称'}</Label>
            <Input id={`vlm-${key}`} value={settings[key]} disabled={saving} onChange={(event) => setSettings({ ...settings, [key]: event.target.value })} /></div>)}
          {VLM_PARAMETERS.map(([key, label, min, max, step]) => <div key={key} className="space-y-2"><Label htmlFor={`vlm-${key}`}>{label}</Label>
            <Input id={`vlm-${key}`} type="number" min={min} max={max} step={step} value={Number.isFinite(settings[key]) ? settings[key] : ''} disabled={saving}
              onChange={(event) => setSettings({ ...settings, [key]: event.target.value === '' ? NaN : Number(event.target.value) })} /></div>)}
        </div> : <p role="status" className="text-sm text-slate-500 dark:text-slate-400">{message || '正在读取模型设置…'}</p>}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={message || '模型设置单独保存。'} saving={saving} disabled={invalid || saving}
      onSave={() => void save()} saveLabel="保存模型设置" />
  </div>
}
