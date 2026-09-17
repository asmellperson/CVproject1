import { useState } from 'react'
import { Activity, Camera, Car, Moon, Phone, ShieldCheck, Video } from 'lucide-react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { GuardDetectionStatusRow, GuardMonitorStatCard } from './GuardMonitorUi'
import { GuardCameraPreview } from './GuardCameraPreview'
import { getMembers, getSiteStatus } from './api'
import type { CameraAvailability, GuardMember, GuardSite, RuleDecision, SiteStatus } from './types'

const SITE_LABELS: Record<SiteStatus['status'], string> = { disabled: '已停用', unconfigured: '未配置摄像头', healthy: '正常', degraded: '部分不可用', unavailable: '未运行 / 不可用' }
const CAMERA_LABELS: Record<CameraAvailability, string> = { READY: '就绪', OFFLINE: '无推理结果', STALE: '结果过期', PHYSICAL_DISABLED: '未运行', INFERENCE_ERROR: '检测未就绪 / 推理不可用' }
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
  useSerialPoll(async (signal) => {
    const [next, cameras] = await Promise.all([getSiteStatus(site.id, signal), getMembers(site.id, signal)])
    if (signal.aborted) return
    setStatus(next); setMembers(cameras); setError('')
  }, { intervalMs: 1000, timeoutMs: 8000, onError: (cause) => {
    setStatus(null); setError(cause instanceof Error ? cause.message : String(cause))
  } })
  const ready = Object.values(status?.camera_states ?? {}).filter((state) => state === 'READY').length
  const online = members.filter((member) => status?.camera_online[String(member.camera_id)] === true).length
  const siteLabel = status ? SITE_LABELS[status.status] : '未运行 / 不可用'
  const alarmCount = status ? RULES.filter(({ key }) => status[key].state === 'alarm').length : 0
  return <div className="space-y-5">
    {error && <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{error}</p>}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <GuardMonitorStatCard label="保安室状态" value={siteLabel} detail={site.name} icon={Activity} tone={status?.status === 'healthy' ? 'emerald' : 'amber'} />
      <GuardMonitorStatCard label="视频在线" value={status ? `${online} / ${members.length}` : '—'} detail={`Guard AI 就绪 ${ready} 路 · 已绑定 ${members.length} 路`} icon={Camera} tone="indigo" ping={members.length > 0 && online === members.length} />
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
          {members.map((member) => <div key={member.camera_id} className="flex items-center justify-between gap-3 text-sm"><span>{member.name}</span><div className="text-right text-xs text-slate-500">
            <p>视频：{!member.physical_enabled ? '设备已停用' : status?.camera_online[String(member.camera_id)] === true ? '在线' : status?.camera_online[String(member.camera_id)] === false ? '离线' : '状态待确认'}</p>
            <p>Guard AI：{!site.enabled || !member.member_enabled ? '未参与联合检测' : status?.camera_states[String(member.camera_id)] ? CAMERA_LABELS[status.camera_states[String(member.camera_id)]] : '检测未就绪'}</p>
          </div></div>)}
        </CardContent></Card>
      </div>
      <div className={`grid h-fit gap-1 overflow-hidden rounded-2xl bg-slate-950 ${members.length > 1 ? 'sm:grid-cols-2' : ''}`}>
        {members.map((member) => <GuardCameraPreview key={member.camera_id} member={member}
          online={status?.camera_online[String(member.camera_id)]}
          aiReady={!!site.enabled && member.member_enabled && !!status?.running && status.camera_states[String(member.camera_id)] === 'READY'} />)}
        {!members.length && <div className="flex aspect-video items-center justify-center text-sm text-slate-400">尚未绑定摄像头</div>}
      </div>
    </ResizableMonitorLayout>
  </div>
}
