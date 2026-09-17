import { useCallback, useEffect, useState } from 'react'
import { Bell, Building2, Camera, Cpu, Settings2 } from 'lucide-react'
import type { DepartmentId } from '@/auth/permissions'
import { AiVisionModelConfig } from '@/components/AiVisionModelConfig'
import { DetectionConfigTab, DetectionConfigTabsList } from '@/components/detection/DetectionConfigUi'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { getAlarmPolicies, getMembers, getPolicy } from './api'
import { SiteSettings } from './SiteSettings'
import { CameraMembership } from './CameraMembership'
import { PolicySettings } from './PolicySettings'
import { AlarmPolicies } from './AlarmPolicies'
import type { AlarmPolicy, GuardMember, GuardSite, SitePolicy } from './types'

const GUARD_MODELS = ['yolo_guard_person_phone', 'guard_uniform', 'yolo_guard_pose', 'yolo_vehicle']
type ConfigData = { members: GuardMember[]; policy: SitePolicy; alarms: AlarmPolicy[] }

export function GuardConfigView({ site, department, onSitesChanged }: {
  site: GuardSite | null; department: DepartmentId; onSitesChanged: (preferredId?: number) => Promise<void>
}) {
  const [data, setData] = useState<ConfigData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const siteId = site?.id
  const reload = useCallback(async (signal?: AbortSignal) => {
    if (!siteId) return
    const [members, policy, alarms] = await Promise.all([
      getMembers(siteId, signal), getPolicy(siteId, signal), getAlarmPolicies(siteId, signal),
    ])
    if (!signal?.aborted) { setData({ members, policy, alarms }); setError('') }
  }, [siteId])
  useEffect(() => {
    const controller = new AbortController()
    void reload(controller.signal).catch((cause) => { if (!controller.signal.aborted) setError(String(cause)) })
    return () => controller.abort()
  }, [reload])
  const change = async (operation: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true); setError(''); setMessage('')
    try { await operation(); await reload(); setMessage('配置已保存。') }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  return <Tabs defaultValue="sites" className="space-y-5">
    <DetectionConfigTabsList>
      <DetectionConfigTab value="sites" icon={Building2}>保安室管理</DetectionConfigTab>
      <DetectionConfigTab value="cameras" icon={Camera} disabled={!site}>摄像头</DetectionConfigTab>
      <DetectionConfigTab value="policy" icon={Settings2} disabled={!site}>检测参数</DetectionConfigTab>
      <DetectionConfigTab value="models" icon={Cpu}>模型配置</DetectionConfigTab>
      <DetectionConfigTab value="alarms" icon={Bell} disabled={!site}>报警推送</DetectionConfigTab>
    </DetectionConfigTabsList>
    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">{error}<Button variant="outline" className="ml-3" disabled={busy} onClick={() => void change(async () => undefined)}>重新读取配置</Button></div>}
    {message && <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">{message}</p>}
    {site && !data && !error && <p role="status">正在读取保安室配置…</p>}
    <TabsContent value="sites"><SiteSettings key={`${site?.id}:${site?.updated_at}`} site={site} department={department} onChanged={onSitesChanged} /></TabsContent>
    <TabsContent value="cameras">{site && data && <CameraMembership site={site} members={data.members} busy={busy} onChange={change} />}</TabsContent>
    <TabsContent value="policy">{data && <PolicySettings policy={data.policy} members={data.members} busy={busy} onChange={change} />}</TabsContent>
    <TabsContent value="models"><AiVisionModelConfig requiredModels={GUARD_MODELS} /></TabsContent>
    <TabsContent value="alarms">{data && <AlarmPolicies policies={data.alarms} busy={busy} onChange={change} />}</TabsContent>
  </Tabs>
}
