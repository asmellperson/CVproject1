import { useEffect, useRef, useState } from 'react'
import { Crosshair, Plus, Settings2, Trash2 } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DetectionConfigCardHeader, DetectionConfigCardContent, DetectionSaveBar, DETECTION_CONFIG_CARD_CLASS } from '@/components/detection/DetectionConfigUi'
import { getAiVisionFeatureConfig, saveAiVisionFeatureConfig } from '@/lib/aivision'
import { INSPECTION_FEATURE, INSPECTION_PARAMETERS, VLM_PARAMETERS, getVlmSettings, saveVlmSettings,
  type InspectionConfig, type VlmSettings } from '@/lib/security-inspection'

export function InspectionConfiguration({ cameraKey, tab }: { cameraKey: string; tab: 'roi' | 'parameters' | 'alarm' }) {
  const { isAdmin } = useAuth()
  const [config, setConfig] = useState<InspectionConfig | null>(null)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [roiName, setRoiName] = useState('')
  const operation = useRef(0)
  useEffect(() => {
    const version = ++operation.current
    setConfig(null); setMessage(''); setRoiName('')
    getAiVisionFeatureConfig(INSPECTION_FEATURE, cameraKey).then((result) => {
      if (version !== operation.current) return
      const next = result.config as InspectionConfig
      setConfig(next); setRoiName(Object.keys(next.value.staff_rois)[0] || '')
    }).catch((error: unknown) => { if (version === operation.current) setMessage(String(error)) })
    return () => { operation.current += 1 }
  }, [cameraKey])
  const save = async () => {
    if (!config || !isAdmin || saving) return
    const version = operation.current
    setSaving(true); setMessage('')
    try {
      const result = await saveAiVisionFeatureConfig(INSPECTION_FEATURE, cameraKey, config)
      if (version === operation.current) { setConfig(result.config as InspectionConfig); setMessage('配置已保存并生效') }
    } catch (error) {
      if (version === operation.current) setMessage(`保存失败：${String(error)}`)
    } finally { if (version === operation.current) setSaving(false) }
  }
  if (!config) return <p className="p-6 text-sm text-slate-500">{message || '加载配置中…'}</p>
  const disabled = !isAdmin || saving
  const validParameters = INSPECTION_PARAMETERS.every(([key, , min, max, step]) => Number.isFinite(config.value[key]) && config.value[key] >= min && config.value[key] <= max && (step !== 1 || Number.isInteger(config.value[key])))
  if (tab === 'alarm') return <AlarmPushConfig showSql alarm={config.alarm} disabled={disabled} saving={saving} message={message}
    alarmInterval={String(config.value.alarm_interval)} onAlarmIntervalChange={(value) => setConfig({ ...config, value: { ...config.value, alarm_interval: Number(value) } })}
    onChange={(alarm) => setConfig({ ...config, alarm: alarm as InspectionConfig['alarm'] })} onSave={() => void save()} />
  if (tab === 'parameters') return <div className="space-y-6">
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Settings2} tone="blue" title="检测参数" description="当前摄像头的人员配对、会话结束条件及关键帧采样设置。" />
      <DetectionConfigCardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {INSPECTION_PARAMETERS.filter(([key]) => key !== 'alarm_interval').map(([key, label, min, max, step]) => <div key={key} className="space-y-2">
          <Label htmlFor={`inspection-${key}`}>{label}</Label>
          <Input id={`inspection-${key}`} type="number" min={min} max={max} step={step} value={Number.isFinite(config.value[key]) ? config.value[key] : ''} disabled={disabled}
            onChange={(event) => setConfig({ ...config, value: { ...config.value, [key]: event.target.value === '' ? NaN : Number(event.target.value) } })} />
        </div>)}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={message || '参数按摄像头独立保存，保存后更新检测状态。'} saving={saving} disabled={disabled || !validParameters} onSave={() => void save()} />
    {isAdmin && <VlmConfiguration />}
  </div>
  const rois = config.value.staff_rois
  const add = () => {
    let index = 1
    while (`security_staff_${index}` in rois) index += 1
    const name = `security_staff_${index}`
    setConfig({ ...config, value: { ...config.value, staff_rois: { ...rois, [name]: [] } } }); setRoiName(name)
  }
  const remove = () => {
    const next = { ...rois }; delete next[roiName]
    setConfig({ ...config, value: { ...config.value, staff_rois: next } }); setRoiName(Object.keys(next)[0] || '')
  }
  return <Card className={DETECTION_CONFIG_CARD_CLASS}>
    <DetectionConfigCardHeader icon={Crosshair} tone="rose" title="工位 ROI 绘制" description="选择工位后逐点绘制，或拖拽绘制四边区域。"
      actions={<><Button variant="outline" size="sm" disabled={disabled || Object.keys(rois).length >= 16} onClick={add}><Plus className="h-4 w-4" />新增</Button>
        <Button variant="outline" size="sm" disabled={disabled || !roiName} onClick={remove}><Trash2 className="h-4 w-4" />删除</Button></>} />
    <DetectionConfigCardContent className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      {roiName ? <AiVisionRoiEditor key={roiName} title={roiName} cameraKey={cameraKey} mode="polygon" roiJson={JSON.stringify(rois[roiName])}
        disabled={disabled} saving={saving} message={message}
        onChange={(json) => setConfig({ ...config, value: { ...config.value, staff_rois: { ...rois, [roiName]: JSON.parse(json) } } })}
        onSave={() => void save()} />
        : <div className="rounded-lg bg-slate-950 p-16 text-center text-sm text-slate-400">暂无工位，请新增后绘制。</div>}
      <div className="space-y-3">{Object.entries(rois).map(([name, points]) => <button key={name} onClick={() => setRoiName(name)}
        className={`w-full rounded-lg border p-3 text-left ${roiName === name ? 'border-blue-500 bg-blue-50 dark:bg-slate-800' : 'hover:bg-slate-50 dark:hover:bg-slate-800'}`}>
        <span className="block text-sm font-semibold">{name}</span><span className="text-xs text-slate-500">{points.length >= 3 ? `${points.length} 个顶点` : '未设置'}</span>
      </button>)}{!roiName && <Button onClick={() => void save()} disabled={disabled}>保存工位配置</Button>}
        {!roiName && message && <p role="status" className="text-sm text-slate-500">{message}</p>}
      </div>
    </DetectionConfigCardContent>
  </Card>
}

function VlmConfiguration() {
  const [settings, setSettings] = useState<VlmSettings | null>(null)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    let active = true
    getVlmSettings().then((value) => { if (active) setSettings(value) }).catch((error: unknown) => { if (active) setMessage(String(error)) })
    return () => { active = false }
  }, [])
  const save = async () => {
    if (!settings || saving) return
    setSaving(true)
    try { setSettings(await saveVlmSettings(settings)); setMessage('模型设置已保存并生效') }
    catch (error) { setMessage(`保存失败：${String(error)}`) }
    finally { setSaving(false) }
  }
  return <Card className={DETECTION_CONFIG_CARD_CLASS}>
    <DetectionConfigCardHeader icon={Settings2} tone="blue" title="千问判定设置" description="所有部门和摄像头共用的内部模型服务设置。" />
    <DetectionConfigCardContent className="space-y-4">
      {settings && <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(['base_url', 'model'] as const).map((key) => <div key={key} className="space-y-2"><Label htmlFor={`vlm-${key}`}>{key === 'base_url' ? '模型接口地址' : '模型名称'}</Label>
          <Input id={`vlm-${key}`} value={settings[key]} disabled={saving} onChange={(event) => setSettings({ ...settings, [key]: event.target.value })} /></div>)}
        {VLM_PARAMETERS.map(([key, label, min, max, step]) => <div key={key} className="space-y-2"><Label htmlFor={`vlm-${key}`}>{label}</Label>
          <Input id={`vlm-${key}`} type="number" min={min} max={max} step={step} value={Number.isFinite(settings[key]) ? settings[key] : ''} disabled={saving}
            onChange={(event) => setSettings({ ...settings, [key]: event.target.value === '' ? NaN : Number(event.target.value) })} /></div>)}
      </div>}
      <p role="status" className="text-sm text-slate-500">{message}</p>
      <Button disabled={!settings || saving || VLM_PARAMETERS.some(([key, , min, max, step]) => !Number.isFinite(settings[key]) || settings[key] < min || settings[key] > max || (step === 1 && !Number.isInteger(settings[key])))} onClick={() => void save()}>{saving ? '保存中…' : '保存模型设置'}</Button>
    </DetectionConfigCardContent>
  </Card>
}
