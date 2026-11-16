import { useState } from 'react'
import { Crosshair, Plus, Settings2, Trash2 } from 'lucide-react'
import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DetectionConfigCardHeader, DetectionConfigCardContent, DetectionSaveBar, DETECTION_CONFIG_CARD_CLASS } from '@/components/detection/DetectionConfigUi'
import { INSPECTION_PARAMETERS, type InspectionConfig } from '@/lib/security-inspection'
import { validInspectionParameters, type useInspectionConfig } from './useInspectionConfig'

export function InspectionConfiguration({ cameraKey, tab, state }: {
  cameraKey: string; tab: 'roi' | 'parameters' | 'alarm'; state: ReturnType<typeof useInspectionConfig>
}) {
  const [selectedRoi, setRoiName] = useState('')
  const config = state.draft
  const { message, saving, disabled, save } = state
  const setConfig = (value: InspectionConfig) => state.update(() => value)
  if (!config) return <p className="p-6 text-sm text-slate-500">{message || '加载配置中…'}</p>
  const validParameters = validInspectionParameters(config)
  if (tab === 'alarm') return <AlarmPushConfig showSql alarm={config.alarm} disabled={disabled} saving={saving} message={message}
    alarmInterval={String(config.value.alarm_interval)} onAlarmIntervalChange={(value) => setConfig({ ...config, value: { ...config.value, alarm_interval: Number(value) } })}
    onChange={(alarm) => setConfig({ ...config, alarm: alarm as InspectionConfig['alarm'] })} onSave={() => void save()} />
  if (tab === 'parameters') return <div className="space-y-6">
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Settings2} tone="blue" title="检测参数" />
      <DetectionConfigCardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {INSPECTION_PARAMETERS.filter(([key]) => key !== 'alarm_interval').map(([key, label, min, max, step]) => <div key={key} className="space-y-2">
          <Label htmlFor={`inspection-${key}`}>{label}</Label>
          <Input id={`inspection-${key}`} type="number" min={min} max={max} step={step} value={Number.isFinite(config.value[key]) ? config.value[key] : ''} disabled={disabled}
            onChange={(event) => setConfig({ ...config, value: { ...config.value, [key]: event.target.value === '' ? NaN : Number(event.target.value) } })} />
        </div>)}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={message} saving={saving} disabled={disabled || !validParameters} onSave={() => void save()} />
  </div>
  const rois = config.value.staff_rois
  const roiName = Object.hasOwn(rois, selectedRoi) ? selectedRoi : Object.keys(rois)[0] || ''
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
    <DetectionConfigCardHeader icon={Crosshair} tone="rose" title="工位 ROI 绘制"
      actions={<><Button variant="outline" size="sm" disabled={disabled || Object.keys(rois).length >= 16} onClick={add}><Plus className="h-4 w-4" />新增</Button>
        <Button variant="outline" size="sm" disabled={disabled || !roiName} onClick={remove}><Trash2 className="h-4 w-4" />删除</Button></>} />
    <DetectionConfigCardContent className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <AiVisionRoiEditor key={roiName || 'preview'} title={roiName || '摄像头原始预览'} cameraKey={cameraKey} mode="polygon" roiJson={JSON.stringify(rois[roiName] || [])}
        disabled={disabled || !roiName} saving={saving} emptyRoiLabel="尚未配置工位区域"
        message={message}
        onChange={(json) => {
          if (!roiName) return
          setConfig({ ...config, value: { ...config.value, staff_rois: { ...rois, [roiName]: JSON.parse(json) } } })
        }}
        onSave={() => void save()} />
      <div className="space-y-3">{Object.entries(rois).map(([name, points]) => <button key={name} onClick={() => setRoiName(name)}
        className={`w-full rounded-lg border p-3 text-left ${roiName === name ? 'border-blue-500 bg-blue-50 dark:bg-slate-800' : 'hover:bg-slate-50 dark:hover:bg-slate-800'}`}>
        <span className="block text-sm font-semibold">{name}</span><span className="text-xs text-slate-500">{points.length >= 3 ? `${points.length} 个顶点` : '未设置'}</span>
      </button>)}{!roiName && <Button onClick={() => void save()} disabled={disabled}>保存工位配置</Button>}
        {!roiName && message && <p role="status" className="text-sm text-slate-500">{message}</p>}
      </div>
    </DetectionConfigCardContent>
  </Card>
}
