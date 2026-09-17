import { useEffect, useRef, useState } from 'react'
import { Activity, Camera, Car, Moon, Phone, ShieldCheck, Video } from 'lucide-react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { GuardDetectionStatusRow, GuardMonitorStatCard, GuardVideoStatusPill } from './GuardMonitorUi'
import { getMembers, getSiteStatus, siteFrameUrl } from './api'
import type { CameraAvailability, GuardMember, GuardSite, RuleDecision, SiteStatus } from './types'

const SITE_LABELS: Record<SiteStatus['status'], string> = { disabled: '已停用', unconfigured: '未配置摄像头', healthy: '正常', degraded: '部分不可用', unavailable: '未运行 / 不可用' }
const CAMERA_LABELS: Record<CameraAvailability, string> = { READY: '可用', OFFLINE: '离线', STALE: '数据过期', PHYSICAL_DISABLED: '物理设备已停用', INFERENCE_ERROR: '核心推理不足' }
const RULE_LABELS: Record<RuleDecision['state'], string> = { normal: '正常', pending: '持续观察', alarm: '异常', unknown: '未知', idle: '无车辆事件', monitoring: '车辆检查中' }
const AVAILABILITY_LABELS: Record<RuleDecision['availability'], string> = { available: '可用', degraded: '降级', unavailable: '不可用' }
const RULES = [
  { key: 'absence', label: '离岗', icon: ShieldCheck }, { key: 'phone', label: '手机', icon: Phone },
  { key: 'prone', label: '趴睡', icon: Moon }, { key: 'vehicle', label: '车辆出厂检查', icon: Car },
] as const

export function GuardMonitorView({ site }: { site: GuardSite }) {
  const [status, setStatus] = useState<SiteStatus | null>(null)
  const [members, setMembers] = useState<GuardMember[]>([])
  const [error, setError] = useState('')
  const [frameUrl, setFrameUrl] = useState<string | null>(null)
  const [frameError, setFrameError] = useState('')
  const objectUrl = useRef<string | null>(null)
  const clearFrame = () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = null
    setFrameUrl(null)
  }
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current) }, [])
  useSerialPoll(async (signal) => {
    const [next, cameras] = await Promise.all([getSiteStatus(site.id, signal), getMembers(site.id, signal)])
    if (signal.aborted) return
    setStatus(next); setMembers(cameras); setError('')
    if (!Object.values(next.camera_states).includes('READY')) clearFrame()
  }, { intervalMs: 1000, timeoutMs: 8000, onError: (cause) => {
    setStatus(null); clearFrame(); setError(cause instanceof Error ? cause.message : String(cause))
  } })
  const ready = Object.values(status?.camera_states ?? {}).filter((state) => state === 'READY').length
  useSerialPoll(async (signal) => {
    const response = await fetch(siteFrameUrl(site.id), { credentials: 'include', cache: 'no-store', signal })
    if (!response.ok) throw new Error(response.status === 503 ? '尚无实时画面' : `画面读取失败（${response.status}）`)
    const blob = await response.blob()
    if (signal.aborted) return
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = URL.createObjectURL(blob)
    setFrameUrl(objectUrl.current); setFrameError('')
  }, { intervalMs: 500, timeoutMs: 8000, enabled: ready > 0 && !!status?.running,
    onError: (cause) => { clearFrame(); setFrameError(cause instanceof Error ? cause.message : String(cause)) } })
  const siteLabel = status ? SITE_LABELS[status.status] : '未运行 / 不可用'
  const alarmCount = status ? RULES.filter(({ key }) => status[key].state === 'alarm').length : 0
  return <div className="space-y-5">
    {error && <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{error}</p>}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <GuardMonitorStatCard label="保安室状态" value={siteLabel} detail={site.name} icon={Activity} tone={status?.status === 'healthy' ? 'emerald' : 'amber'} />
      <GuardMonitorStatCard label="可用摄像头" value={`${ready} / ${Object.keys(status?.camera_states ?? {}).length}`} detail={`已绑定 ${members.length} 路摄像头`} icon={Camera} tone="indigo" ping={status?.status === 'healthy'} />
      <GuardMonitorStatCard label="异常规则" value={status ? String(alarmCount) : '—'} detail="按保安室聚合，不重复计算摄像头" icon={ShieldCheck} tone={alarmCount ? 'rose' : 'indigo'} />
      <GuardMonitorStatCard label="最近更新" value={status?.updated_at ? new Date(status.updated_at * 1000).toLocaleTimeString() : '—'} detail={status?.running ? '等待或接收单摄感知结果' : '运行数据尚不可用'} icon={Video} tone="indigo" />
    </div>
    <ResizableMonitorLayout id="guard-behavior">
      <div className="space-y-5">
        <Card className="rounded-2xl dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100"><CardHeader><CardTitle>规则状态</CardTitle></CardHeader><CardContent>
          {RULES.map(({ key, label, icon }) => {
            const rule = status?.[key]
            return <div key={key} className="pb-3"><GuardDetectionStatusRow label={label} icon={icon}
              state={rule?.state === 'alarm' ? 'danger' : !rule || rule.state === 'unknown' || rule.state === 'pending' ? 'warning' : 'normal'}
              stateLabel={rule ? RULE_LABELS[rule.state] : '未知'} />
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{rule ? `${AVAILABILITY_LABELS[rule.availability]} · ${rule.reason}` : '未运行 / 不可用'}</p>
              {!!rule?.offending_camera_ids.length && <p className="mt-1 text-xs text-slate-500">异常摄像头：{rule.offending_camera_ids.map((id) => members.find((member) => member.camera_id === id)?.name ?? `#${id}`).join('、')}</p>}
            </div>
          })}
        </CardContent></Card>
        <Card className="rounded-2xl dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100"><CardHeader><CardTitle>摄像头状态</CardTitle></CardHeader><CardContent className="space-y-3">
          {!members.length && <p className="text-sm text-slate-500">尚未绑定摄像头</p>}
          {members.map((member) => <div key={member.camera_id} className="flex items-center justify-between gap-3 text-sm"><span>{member.name}</span><span className="text-xs text-slate-500">{!member.member_enabled ? '未参与联合检测' : !member.physical_enabled ? '物理设备已停用' : status?.camera_states[String(member.camera_id)] ? CAMERA_LABELS[status.camera_states[String(member.camera_id)]] : '未运行 / 不可用'}</span></div>)}
        </CardContent></Card>
      </div>
      <div className="relative overflow-hidden rounded-2xl bg-slate-950">
        <div className="absolute left-3 top-3 z-10"><GuardVideoStatusPill label={`${site.name} · ${siteLabel}`} state={ready ? 'normal' : 'neutral'} showDot /></div>
        {frameUrl ? <img src={frameUrl} alt={`${site.name}拼接画面`} className="block h-auto w-full object-contain" /> : <div className="flex aspect-video items-center justify-center p-8 text-center text-sm text-slate-400">{frameError || '未运行 / 不可用，等待摄像头感知画面'}</div>}
      </div>
    </ResizableMonitorLayout>
  </div>
}
