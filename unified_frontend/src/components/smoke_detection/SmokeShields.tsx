import { useEffect, useRef, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { DetectionSaveBar } from '@/components/detection/DetectionConfigUi'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { readSmokeShields, saveSmokeShields, smokePictureUrl, type SmokeShieldRegion, type SmokeShieldState } from './api'

export function SmokeShields({ cameraKey, department, disabled }: {
  cameraKey: string; department: DepartmentId; disabled: boolean
}) {
  const [state, setState] = useState<SmokeShieldState | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [message, setMessage] = useState('')
  const [editorValid, setEditorValid] = useState(false)
  const revision = useRef(0)
  const mutation = useRef(false)
  useEffect(() => {
    const token = ++revision.current
    const controller = new AbortController()
    setLoading(true); setState(null); setSelected(null); setMessage('正在读取摄像头烟雾屏蔽区域…')
    void readSmokeShields(cameraKey, department, controller.signal).then((value) => {
      if (token !== revision.current) return
      setState(value); setSelected(value.regions[0]?.id ?? null)
      setMessage(value.message || '已读取设备烟雾屏蔽区域。')
    }).catch((error: unknown) => {
      if (token === revision.current && !controller.signal.aborted) setMessage(`屏蔽区域读取失败：${String(error)}`)
    }).finally(() => { if (token === revision.current) setLoading(false) })
    return () => { revision.current += 1; controller.abort() }
  }, [cameraKey, department, refresh])

  const readOnly = disabled || loading || saving || !state?.writable
  const region = state?.regions.find((item) => item.id === selected)
  const updateRegion = (change: (current: SmokeShieldRegion) => SmokeShieldRegion) => {
    if (readOnly) return
    setState((current) => current ? { ...current, regions: current.regions.map((item) => item.id === selected ? change(item) : item) } : current)
  }
  const addRegion = () => {
    if (readOnly || !state || state.regions.length >= state.max_regions) return
    const id = Array.from({ length: state.max_regions }, (_, index) => index + 1).find((candidate) => !state.regions.some((item) => item.id === candidate))
    if (!id) return
    setState({ ...state, regions: [...state.regions, { id, name: `屏蔽区域 ${id}`, enabled: true, points: [] }] })
    setSelected(id)
    setEditorValid(false)
  }
  const removeRegion = () => {
    if (readOnly || !state || selected === null) return
    const regions = state.regions.filter((item) => item.id !== selected)
    setState({ ...state, regions }); setSelected(regions[0]?.id ?? null)
  }
  const save = async () => {
    if (readOnly || !state || mutation.current || (state.regions.length > 0 && !editorValid)) return
    const token = revision.current
    try {
      for (const item of state.regions) {
        if (item.points.length < state.min_points || item.points.length > state.max_points) throw new Error(`${item.name || item.id}需要 ${state.min_points}～${state.max_points} 个顶点`)
        parseNormalizedRoi(JSON.stringify(item.points.map((point) => [point.x, point.y])))
      }
      mutation.current = true; setSaving(true); setMessage('正在写入摄像头并回读区域…')
      const value = await saveSmokeShields(cameraKey, department, { enabled: state.enabled, regions: state.regions })
      if (token === revision.current) { setState(value); setMessage('烟雾屏蔽区域已保存到摄像头并回读确认。') }
    } catch (error) {
      if (token === revision.current) setMessage(`屏蔽区域保存失败：${String(error)}`)
    } finally {
      mutation.current = false
      if (token === revision.current) setSaving(false)
    }
  }
  return <div className="space-y-5">
    {state?.supported && <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <label className="flex items-center justify-between gap-4"><span className="text-sm">启用设备烟雾区域屏蔽</span><Switch aria-label="启用设备烟雾区域屏蔽" checked={state.enabled} disabled={readOnly}
        onCheckedChange={(enabled) => setState((current) => current ? { ...current, enabled } : current)} /></label>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-40 flex-1 space-y-2"><Label htmlFor="smoke-shield-region">屏蔽区域</Label>
          <Select value={selected === null ? '' : String(selected)} onValueChange={(value) => { setSelected(Number(value)); setEditorValid(false) }} disabled={loading || saving || !state.regions.length}>
            <SelectTrigger id="smoke-shield-region"><SelectValue placeholder="暂无屏蔽区域" /></SelectTrigger>
            <SelectContent>{state.regions.map((item) => <SelectItem key={item.id} value={String(item.id)}>{item.name || `区域 ${item.id}`}{item.enabled ? '' : '（停用）'}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <Button variant="outline" disabled={readOnly || state.regions.length >= state.max_regions} onClick={addRegion}><Plus className="mr-2 h-4 w-4" />添加区域</Button>
        <Button variant="outline" disabled={readOnly || !region} onClick={removeRegion}><Trash2 className="mr-2 h-4 w-4" />移除区域</Button>
      </div>
      {region && <div className="grid items-center gap-4 sm:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="smoke-shield-name">区域名称</Label><Input id="smoke-shield-name" value={region.name} maxLength={32} disabled={readOnly}
          onChange={(event) => updateRegion((current) => ({ ...current, name: event.target.value }))} /></div>
        <label className="flex items-center justify-between gap-4"><span className="text-sm">启用当前屏蔽区域</span><Switch aria-label="启用当前屏蔽区域" checked={region.enabled} disabled={readOnly}
          onCheckedChange={(enabled) => updateRegion((current) => ({ ...current, enabled }))} /></label>
      </div>}
      {!state.writable && <p className="text-sm text-amber-700 dark:text-amber-300">{state.message || '设备未返回完整区域配置能力，当前只读。'}</p>}
    </div>}
    {state && region && <AiVisionRoiEditor key={`${cameraKey}:${region.id}`} title="烟雾屏蔽区域绘制" regionLabel="屏蔽区"
      cameraKey={cameraKey} frameUrl={smokePictureUrl(cameraKey, department)}
      emptyRoiLabel="尚未绘制屏蔽区"
      minRoiArea={1} minPoints={state.min_points} maxPoints={state.max_points} allowFullFrame={false} showSaveButton={false}
      onValidityChange={setEditorValid}
      roiJson={JSON.stringify(region.points.map((point) => [point.x, point.y]))} disabled={readOnly} saving={saving} message={message}
      onChange={(raw) => { const points = JSON.parse(raw) as [number, number][]; updateRegion((current) => ({ ...current, points: points.map(([x, y]) => ({ x, y })) })) }}
      onSave={() => { void save() }} />}
    <DetectionSaveBar message={message} loading={loading} saving={saving} disabled={readOnly || (Boolean(state?.regions.length) && !editorValid)}
      onReload={() => setRefresh((value) => value + 1)} onSave={() => { void save() }} saveLabel="保存屏蔽配置到摄像头" />
  </div>
}
