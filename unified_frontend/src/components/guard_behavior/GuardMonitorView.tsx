import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera, Car, Coffee, Gauge, Radio, RefreshCw, ShieldCheck, Smartphone, UserRound, Users, Video } from 'lucide-react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'
import {
  createPreviewPerformanceGroup,
  type PreviewPerformanceGroupReport,
  type PreviewPerformanceReport,
} from '@/components/AiVisionMonitor.performance'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { GuardDetectionStatusRow, GuardMonitorStatCard, GuardVideoStatusPill } from './GuardMonitorUi'
import { GuardCameraPreview } from './GuardCameraPreview'
import { GuardLatestAlarm } from './GuardLatestAlarm'
import { getMembers, getSiteStatus } from './api'
import { summarizeGuardMonitor } from './monitorPresentation'
import type { CameraAvailability, GuardMember, GuardSite, RuleDecision, SiteStatus } from './types'

const CARD_CLASS = 'rounded-2xl border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100'
const SITE_LABELS: Record<SiteStatus['status'], string> = { disabled: '已停用', unconfigured: '未配置摄像头', healthy: '正常', degraded: '部分不可用', unavailable: '未运行 / 不可用' }
const CAMERA_LABELS: Record<CameraAvailability, string> = { READY: '就绪', OFFLINE: '无推理结果', STALE: '结果过期', PHYSICAL_DISABLED: '未运行', INFERENCE_ERROR: '检测未就绪 / 推理不可用' }
const RULE_LABELS: Record<RuleDecision['state'], string> = { normal: '正常', pending: '持续观察', alarm: '异常', unknown: '未知', idle: '无车辆事件', monitoring: '车辆检查中' }
const RULES = [
  { key: 'phone', label: '手机使用检测', icon: Smartphone }, { key: 'prone', label: '俯卧姿态检测', icon: Coffee },
  { key: 'vehicle', label: '车辆看护检测', icon: Car }, { key: 'absence', label: '保安在岗识别', icon: UserRound },
] as const

export function GuardMonitorView({ site, sites = [], loadingSites = false, onSelectSite, onRefreshSites }: {
  site: GuardSite | null; sites?: GuardSite[]; loadingSites?: boolean
  onSelectSite?: (id: number) => void; onRefreshSites?: () => Promise<void>
}) {
  const [status, setStatus] = useState<SiteStatus | null>(null)
  const [members, setMembers] = useState<GuardMember[]>([])
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const performanceGroup = useRef<ReturnType<typeof createPreviewPerformanceGroup> | null>(null)
  const siteId = site?.id ?? null
  const department = site?.department ?? ''
  useEffect(() => {
    let lastReport: PreviewPerformanceGroupReport | undefined
    const group = createPreviewPerformanceGroup({
      siteId, department,
      onReport(report) {
        lastReport = report
        window.aivisionPreviewDiagnostics = report
        console.debug('[保安室预览性能]', report)
      },
    })
    performanceGroup.current = group
    group.publish()
    return () => {
      group.dispose()
      if (performanceGroup.current === group) performanceGroup.current = null
      if (window.aivisionPreviewDiagnostics === lastReport) delete window.aivisionPreviewDiagnostics
    }
  }, [siteId, department])
  useEffect(() => {
    performanceGroup.current?.setCameras(members.map((member) => member.shm_name))
  }, [members])
  const reportPerformance = useCallback((report: PreviewPerformanceReport) => {
    performanceGroup.current?.update(report)
  }, [])
  useSerialPoll(async (signal) => {
    if (!site) return
    const [next, cameras] = await Promise.all([getSiteStatus(site.id, signal), getMembers(site.id, signal)])
    if (signal.aborted) return
    setStatus(next); setMembers(cameras); setError('')
  }, { intervalMs: 1000, timeoutMs: 8000, enabled: !!site, restartKey: refreshKey, onError: (cause) => {
    setStatus(null); setError(cause instanceof Error ? cause.message : String(cause))
  } })
  const { online, guards, guardConfidence, fps, abnormalCount, videoLabel } = summarizeGuardMonitor(status, members)
  const siteLabel = status ? SITE_LABELS[status.status] : '未运行 / 不可用'
  const confidenceText = (value: number | null | undefined) => value == null ? '—' : `${Math.round(value * 100)}%`
  return <div className="w-full min-w-0 space-y-5">
    {error && <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">{error}</p>}
    <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <GuardMonitorStatCard label="摄像头状态" value={videoLabel} detail={`${online} / ${members.length} 路视频在线`} icon={Video} tone={online > 0 ? 'emerald' : 'amber'} ping={members.length > 0 && online === members.length} />
      <GuardMonitorStatCard label="在岗人数" value={guards === null ? '—' : `${guards} 人`} detail={members.length > 1 ? '取有效画面最大人数，跨摄像头不累加' : `识别置信度 ${confidenceText(guardConfidence)}`} icon={Users} tone={guards ? 'emerald' : 'amber'} />
      <GuardMonitorStatCard label="检测帧率" value={fps === null ? '—' : `${fps.toFixed(1)} FPS`} detail="有效摄像头的平均处理帧率" icon={Gauge} tone="indigo" />
      <GuardMonitorStatCard label="异常行为" value={abnormalCount === null ? '—' : `${abnormalCount} 项`} detail={siteLabel} icon={ShieldCheck} tone={abnormalCount ? 'rose' : status?.status === 'healthy' ? 'emerald' : 'amber'} />
    </section>
    <ResizableMonitorLayout id="guard-behavior">
      <div className="space-y-5">
        <Card className={CARD_CLASS}>
          <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-3 text-base font-bold">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300"><Camera className="h-4 w-4" /></span>监控对象
          </CardTitle></CardHeader>
          <CardContent className="space-y-3 px-5 pb-5">
            <div className="space-y-2"><Label htmlFor="guard-monitor-site" className="text-xs text-slate-500">保安室名称</Label>
              <Select value={site ? String(site.id) : ''} disabled={loadingSites || !sites.length} onValueChange={(id) => onSelectSite?.(Number(id))}>
                <SelectTrigger id="guard-monitor-site" className="w-full rounded-xl border-slate-200 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-950/60"><SelectValue placeholder={loadingSites ? '正在读取保安室' : '选择保安室'} /></SelectTrigger>
                <SelectContent>{sites.map((item) => <SelectItem key={item.id} value={String(item.id)}>{item.name}{item.enabled ? '' : '（已停用）'}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <Button variant="outline" className="w-full gap-2 rounded-xl text-slate-600 dark:text-slate-300" disabled={loadingSites}
              onClick={() => { setRefreshKey((value) => value + 1); void onRefreshSites?.() }}><RefreshCw className="h-4 w-4" />刷新状态</Button>
          </CardContent>
        </Card>
        <Card className={CARD_CLASS}>
          <CardHeader className="p-5 pb-2"><CardTitle className="text-base font-bold">实时检测项</CardTitle></CardHeader>
          <CardContent className="px-5 pb-4">{RULES.map(({ key, label, icon }) => {
            const rule = status?.[key]
            return <div key={key} title={rule?.reason}>
              <GuardDetectionStatusRow label={label} icon={icon}
                state={rule?.state === 'alarm' ? 'danger' : !rule || rule.state === 'unknown' || rule.state === 'pending' ? 'warning' : 'normal'}
                stateLabel={key === 'absence' && rule?.state === 'normal' && guards !== null ? `${guards} 人在岗` : rule ? RULE_LABELS[rule.state] : '未知'} />
              {rule && (rule.state === 'alarm' || rule.state === 'pending' || rule.availability !== 'available') && <p className="pb-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{rule.reason}</p>}
            </div>
          })}</CardContent>
        </Card>
        <Card className={CARD_CLASS}>
          <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-2 text-base font-bold"><Radio className="h-4 w-4 text-[#1B3FA0] dark:text-blue-300" />检测详情</CardTitle></CardHeader>
          <CardContent className="space-y-5 px-5 pb-5">
            {[
              { label: '保安识别置信度', value: guardConfidence },
              { label: '手机置信度', value: status?.phone.state === 'unknown' ? null : status?.phone.confidence },
              { label: '趴睡识别置信度', value: status?.prone.state === 'unknown' ? null : status?.prone.confidence },
            ].map(({ label, value }) => <div key={label}><div className="mb-2 flex items-center justify-between text-sm"><span>{label}</span><span>{confidenceText(value)}</span></div><Progress aria-label={label} value={value == null ? 0 : Math.max(0, Math.min(100, value * 100))} /></div>)}
            <details className="border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
              <summary className="cursor-pointer">摄像头状态 · {online} / {members.length} 路在线</summary>
              <div className="mt-3 space-y-3">{members.map((member) => <div key={member.camera_id} className="flex justify-between gap-3"><span>{member.name}</span><div className="text-right">
                <p>视频：{!member.physical_enabled ? '设备已停用' : status?.camera_online[String(member.camera_id)] === true ? '在线' : status?.camera_online[String(member.camera_id)] === false ? '离线' : '状态待确认'}</p>
                <p>Guard AI：{!site?.enabled || !member.member_enabled ? '未参与联合检测' : status?.camera_states[String(member.camera_id)] ? CAMERA_LABELS[status.camera_states[String(member.camera_id)]] : '检测未就绪'}</p>
              </div></div>)}</div>
            </details>
          </CardContent>
        </Card>
        <GuardLatestAlarm key={site?.id ?? 'empty'} siteId={site?.id} />
      </div>
      <Card className={`${CARD_CLASS} overflow-hidden`}>
        <CardHeader className="border-b border-slate-100 p-4 dark:border-slate-800 sm:px-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white"><Camera className="h-5 w-5" /></span>
              <div className="min-w-0"><CardTitle className="text-base font-bold">视频流</CardTitle><p className="mt-0.5 truncate text-xs text-slate-400">{site?.name ?? '未选择保安室'} · {members.length} 路摄像头</p></div>
            </div>
            <div className="flex items-center gap-2"><span className="rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-300">FPS {fps?.toFixed(1) ?? '—'}</span>
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold ${online ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>
                {online > 0 && <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-70" /><span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" /></span>}{online ? 'LIVE' : '等待画面'}
              </span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center gap-2 bg-slate-900 px-3 py-2.5">
            <GuardVideoStatusPill label={guards === null ? '在岗人数待确认' : `在岗 ${guards} 人`} state={guards ? 'normal' : 'neutral'} />
            {RULES.slice(0, 3).map(({ key, label }) => <GuardVideoStatusPill key={key}
              label={`${label.replace('检测', '')} ${status ? RULE_LABELS[status[key].state] : '未知'}`}
              state={status?.[key].state === 'alarm' ? 'danger' : status?.[key].state === 'normal' ? 'normal' : 'neutral'} />)}
          </div>
          <div className={`grid h-fit gap-1 overflow-hidden bg-slate-950 ${members.length > 1 ? 'sm:grid-cols-2' : ''}`}>
          {members.map((member) => <GuardCameraPreview key={`${siteId}:${member.camera_id}:${refreshKey}`} member={member} online={status?.camera_online[String(member.camera_id)]}
            onPerformanceReport={reportPerformance}
            aiReady={!!site?.enabled && member.member_enabled && !!status?.running && status.camera_states[String(member.camera_id)] === 'READY'} />)}
          {!members.length && <div className="flex min-h-72 items-center justify-center px-6 text-center text-sm text-slate-300">{loadingSites ? '正在读取保安室…' : site ? '当前保安室尚未绑定摄像头。' : '请先在配置管理中新增并选择保安室。'}</div>}
        </div></CardContent>
      </Card>
    </ResizableMonitorLayout>
  </div>
}
