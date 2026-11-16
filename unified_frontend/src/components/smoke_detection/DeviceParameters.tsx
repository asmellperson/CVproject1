import { useEffect, useRef, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { readSmokeParameters, saveSmokeParameters, type SmokeParametersState } from './api'

export function DeviceParameters({ cameraKey, department, disabled }: {
  cameraKey: string; department: DepartmentId; disabled: boolean
}) {
  const [state, setState] = useState<SmokeParametersState | null>(null)
  const [draft, setDraft] = useState<Record<string, boolean | string>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [refresh, setRefresh] = useState(0)
  const revision = useRef(0)
  const mutation = useRef(false)

  const receive = (value: SmokeParametersState) => {
    setState(value)
    setDraft(Object.fromEntries(value.parameters.map((field) => [field.key, field.kind === 'boolean' ? Boolean(field.value) : String(field.value)])))
  }
  useEffect(() => {
    const token = ++revision.current
    const controller = new AbortController()
    setLoading(true); setState(null); setDraft({}); setMessage('正在读取摄像头实际参数…')
    void readSmokeParameters(cameraKey, department, controller.signal).then((value) => {
      if (token !== revision.current) return
      receive(value); setMessage(value.message || '已读取摄像头实际参数。')
    }).catch((error: unknown) => {
      if (token === revision.current && !controller.signal.aborted) setMessage(`设备参数读取失败：${String(error)}`)
    }).finally(() => { if (token === revision.current) setLoading(false) })
    return () => { revision.current += 1; controller.abort() }
  }, [cameraKey, department, refresh])

  const save = async () => {
    if (disabled || loading || mutation.current || !state?.supported || !state.parameters.length) return
    const token = revision.current
    try {
      const values: Record<string, boolean | number> = {}
      for (const field of state.parameters) {
        const current = draft[field.key]
        if (field.kind === 'boolean') values[field.key] = current === true
        else {
          const parsed = Number(current)
          if (typeof current !== 'string' || !current.trim() || !Number.isInteger(parsed)
            || (field.minimum !== null && parsed < field.minimum) || (field.maximum !== null && parsed > field.maximum)) {
            throw new Error(`${field.label}超出设备允许的范围`)
          }
          values[field.key] = parsed
        }
      }
      mutation.current = true; setSaving(true); setMessage('正在写入摄像头并回读确认…')
      const value = await saveSmokeParameters(cameraKey, department, values)
      if (token === revision.current) { receive(value); setMessage('摄像头参数已保存并回读确认。') }
    } catch (error) {
      if (token === revision.current) setMessage(`设备参数保存失败：${String(error)}`)
    } finally {
      mutation.current = false
      if (token === revision.current) setSaving(false)
    }
  }
  const readOnly = disabled || loading || saving
  return <div className="space-y-5">
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="摄像头烟雾参数" description="显示设备实际支持的参数；保存后直接写入摄像头。" />
      <DetectionConfigCardContent className="space-y-5">
        {state?.global_enabled === false && <p className="text-sm text-amber-700 dark:text-amber-300">设备烟火总开关当前关闭，请核对摄像头端的功能启用状态。</p>}
        {state?.parameters.map((field) => <div key={field.key} className="space-y-2">
          {field.kind === 'boolean'
            ? <label className="flex min-h-12 items-center justify-between gap-4"><span className="text-sm">{field.label}</span><Switch aria-label={field.label} checked={draft[field.key] === true} disabled={readOnly}
              onCheckedChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))} /></label>
            : <><Label htmlFor={`smoke-device-${field.key}`}>{field.label}</Label><Input id={`smoke-device-${field.key}`} type="number" step={1}
              min={field.minimum ?? undefined} max={field.maximum ?? undefined} value={String(draft[field.key] ?? '')} disabled={readOnly}
              onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))} /></>}
        </div>)}
        {!loading && state && !state.parameters.length && <p className="text-sm text-slate-500 dark:text-slate-400">{state.message || '设备没有返回可调整的烟雾参数。'}</p>}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={readOnly || !state?.supported || !state.parameters.length}
      onReload={() => setRefresh((value) => value + 1)} onSave={() => { void save() }} saveLabel="保存到摄像头" />
  </div>
}
