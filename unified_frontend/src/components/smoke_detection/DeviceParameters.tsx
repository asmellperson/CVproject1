import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, SlidersHorizontal } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader, DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
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
      const values: Record<string, boolean | number | string> = {}
      for (const field of state.parameters) {
        const current = draft[field.key]
        if (field.kind === 'boolean') values[field.key] = current === true
        else if (field.kind === 'enum') {
          if (typeof current !== 'string' || !field.choices.some((choice) => choice.value === current)) {
            throw new Error(`${field.label}不在设备允许的选项中`)
          }
          values[field.key] = current
        }
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
      <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="设备参数" />
      <DetectionConfigCardContent className="space-y-5">
        {state?.global_enabled === false && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">设备烟火检测已关闭。</p>}
        {state?.warnings.map((warning) => <div key={warning} role="alert" className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span>{warning}</span>
        </div>)}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {state?.parameters.filter((field) => field.kind === 'boolean').map((field) => <label key={field.key} className="flex min-h-14 items-center justify-between gap-4 rounded-xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-3 dark:border-slate-800 dark:bg-slate-950/40">
            <span className="text-sm font-medium">{field.label}</span><Switch aria-label={field.label} checked={draft[field.key] === true} disabled={readOnly}
              onCheckedChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))} />
          </label>)}
        </div>
        <div className="grid gap-5 md:grid-cols-2">
        {state?.parameters.filter((field) => field.kind !== 'boolean').map((field) => <div key={field.key} className="space-y-2">
          {field.kind === 'enum'
              ? <><Label htmlFor={`smoke-device-${field.key}`}>{field.label}</Label><Select value={String(draft[field.key] ?? '')} disabled={readOnly}
                onValueChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))}>
                <SelectTrigger id={`smoke-device-${field.key}`} className="w-full"><SelectValue placeholder="选择设备支持的选项" /></SelectTrigger>
                <SelectContent>{field.choices.map((choice) => <SelectItem key={choice.value} value={choice.value}>{choice.label}</SelectItem>)}</SelectContent>
              </Select></>
              : <><Label htmlFor={`smoke-device-${field.key}`}>{field.label}</Label><Input id={`smoke-device-${field.key}`} type="number" step={1}
              min={field.minimum ?? undefined} max={field.maximum ?? undefined} value={String(draft[field.key] ?? '')} disabled={readOnly}
              onChange={(event) => setDraft((current) => ({ ...current, [field.key]: event.target.value }))} /></>}
        </div>)}
        </div>
        {!loading && state && !state.parameters.length && <p className="text-sm text-slate-500 dark:text-slate-400">{state.message || '设备没有返回可调整的烟雾参数。'}</p>}
      </DetectionConfigCardContent>
    </Card>
    <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={readOnly || !state?.supported || !state.parameters.length}
      onReload={() => setRefresh((value) => value + 1)} onSave={() => { void save() }} saveLabel="保存到摄像头" />
  </div>
}
