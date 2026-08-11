import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Activity,
  AlertTriangle,
  Camera,
  Car,
  Coffee,
  Gauge,
  Pause,
  Radio,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  UserRound,
  Users,
  Video,
} from 'lucide-react'
import {
  getGuardRoomSiteStatus,
  guardRoomSiteFrameUrl,
} from '@/lib/api'
import type { BackendStatus, GuardRoomSite } from '@/types'
import { cn } from '@/lib/utils'
import {
  GuardDetectionStatusRow,
  GuardMonitorStatCard,
  GuardVideoStatusPill,
} from '@/components/guard_room/GuardMonitorUi'
import { ResizableMonitorLayout } from '@/components/monitor/ResizableMonitorLayout'

const POLL_MS = 1000
const FRAME_REFRESH_MS = 200
const CARD_CLASS = 'rounded-2xl border border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900'

function withFrameNonce(url: string) {
  return `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`
}

function alarmText(type?: string) {
  switch (type) {
    case 'absent':
      return '离岗报警'
    case 'phone_use':
      return '玩手机'
    case 'prone_sleep':
      return '趴睡'
    case 'vehicle_unattended':
      return '车辆无人值守'
    default:
      return '未知报警'
  }
}

type MonitorSectionProps = {
  site: GuardRoomSite | null
  sites: GuardRoomSite[]
  selectedSiteId: number | null
  loadingSites: boolean
  onSelectSite: (siteId: number) => void
  department?: string
}

export function MonitorSection({ site, sites, selectedSiteId, loadingSites, onSelectSite, department }: MonitorSectionProps) {
  const [status, setStatus] = useState<BackendStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [imgKey, setImgKey] = useState(0)
  const [frameSrc, setFrameSrc] = useState('')
  const objectUrlRef = useRef<string | null>(null)

  const revokeFrameUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!site) {
      setStatus(null)
      setLoading(false)
      return
    }

    setLoading(true)
    let mounted = true

    const fetchStatus = async () => {
      try {
        const next = await getGuardRoomSiteStatus(site.id, department)
        if (mounted) {
          setStatus(next)
          setLoading(false)
        }
      } catch {
        if (mounted) {
          setLoading(false)
        }
      }
    }

    fetchStatus()
    const timer = window.setInterval(fetchStatus, POLL_MS)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [department, site])

  useEffect(() => {
    if (!site) {
      setFrameSrc('')
      revokeFrameUrl()
      return
    }

    let cancelled = false
    let timeoutId: number | undefined
    let controller: AbortController | null = null

    const loadFrame = async () => {
      const startedAt = performance.now()
      controller = new AbortController()
      try {
        const response = await fetch(withFrameNonce(guardRoomSiteFrameUrl(site.id, department)), {
          cache: 'no-store',
          credentials: 'include',
          signal: controller.signal,
        })
        if (response.status === 401) {
          window.dispatchEvent(new Event('aicv:unauthorized'))
        }
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`)
        }

        const blob = await response.blob()
        if (cancelled) return

        const nextFrameSrc = URL.createObjectURL(blob)
        revokeFrameUrl()
        objectUrlRef.current = nextFrameSrc
        setFrameSrc(nextFrameSrc)
      } catch (error) {
        if (!cancelled && !(error instanceof DOMException && error.name === 'AbortError')) {
          setFrameSrc('')
        }
      } finally {
        if (!cancelled) {
          const elapsed = performance.now() - startedAt
          timeoutId = window.setTimeout(loadFrame, Math.max(0, FRAME_REFRESH_MS - elapsed))
        }
      }
    }

    loadFrame()

    return () => {
      cancelled = true
      controller?.abort()
      if (timeoutId) window.clearTimeout(timeoutId)
      revokeFrameUrl()
    }
  }, [department, imgKey, revokeFrameUrl, site])

  const handleRefresh = async () => {
    if (!site) return
    try {
      setStatus(await getGuardRoomSiteStatus(site.id, department))
      setImgKey((value) => value + 1)
    } catch {
      setImgKey((value) => value + 1)
    }
  }

  const lastAlarm = status?.last_alarm ?? null
  const cameraOnline = Boolean(site && frameSrc)
  const guards = status?.counts.guards ?? 0
  const guardConfidence = status?.metrics.guard_confidence ?? 0
  const phoneAbnormal = Boolean(status?.decisions.phone_use)
  const proneAbnormal = Boolean(status?.decisions.prone_sleep)
  const vehicleAbnormal = Boolean(status?.decisions.vehicle_unattended)
  const abnormalCount = [phoneAbnormal, proneAbnormal, vehicleAbnormal].filter(Boolean).length

  return (
    <div className="w-full min-w-0 space-y-5">
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <GuardMonitorStatCard
          label="摄像头状态"
          value={cameraOnline ? '在线' : '离线'}
          detail={site ? `cam1 · ${cameraOnline ? '画面已连接' : '等待画面'}` : '请选择监控对象'}
          icon={Video}
          tone={cameraOnline ? 'emerald' : 'rose'}
          ping={cameraOnline}
        />
        <GuardMonitorStatCard
          label="在岗人数"
          value={`${guards} 人`}
          detail={`识别置信度 ${(guardConfidence * 100).toFixed(0)}%`}
          icon={Users}
          tone={guards > 0 ? 'emerald' : 'amber'}
        />
        <GuardMonitorStatCard
          label="检测帧率"
          value={`${status?.fps?.toFixed(1) ?? '--'} FPS`}
          detail="推理延迟约 154ms"
          icon={Gauge}
          tone="indigo"
        />
        <GuardMonitorStatCard
          label="异常行为"
          value={`${abnormalCount} 项`}
          detail={abnormalCount === 0 ? '手机 / 俯卧 / 车辆均正常' : '手机 / 俯卧 / 车辆存在异常'}
          icon={ShieldCheck}
          tone={abnormalCount === 0 ? 'emerald' : 'rose'}
        />
      </section>

      <ResizableMonitorLayout id={`guard-room-${department || 'general-electric'}`}>
        <div className="space-y-5">
          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3">
              <CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300">
                  <Camera className="h-4 w-4" />
                </span>
                监控对象
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 px-5 pb-5">
              <Label htmlFor="guard-room-monitor-site" className="text-xs text-slate-500">保安室名称</Label>
              <Select
                value={selectedSiteId ? String(selectedSiteId) : ''}
                onValueChange={(value) => onSelectSite(Number(value))}
                disabled={loadingSites || sites.length === 0}
              >
                <SelectTrigger
                  id="guard-room-monitor-site"
                  className="w-full rounded-xl border-slate-200 bg-slate-50/60 px-3.5 py-2.5 focus:border-[#1B3FA0] focus:ring-2 focus:ring-[#1B3FA0]/15 dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-200"
                >
                  <SelectValue placeholder={loadingSites ? '正在读取保安室' : '选择保安室'} />
                </SelectTrigger>
                <SelectContent>
                  {sites.map((item) => (
                    <SelectItem key={item.id} value={String(item.id)}>{item.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-3">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="flex items-center gap-3 text-base font-bold text-slate-950 dark:text-slate-100">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300">
                    <Activity className="h-4 w-4" />
                  </span>
                  检测控制
                </CardTitle>
                <Badge className={cn('border-0 shadow-none', status?.running ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500')}>
                  {status?.running ? '运行中' : '已关闭'}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="px-5 pb-5">
              <p className="rounded-xl border border-blue-100 bg-blue-50 px-3 py-2.5 text-xs leading-5 text-blue-700 dark:border-blue-900 dark:bg-blue-950/40 dark:text-blue-300">开启和关闭操作已统一移至页面头部，当前卡片仅显示并刷新运行状态。</p>
              <Button
                type="button"
                variant="outline"
                className="mt-3 w-full gap-2 rounded-xl border-slate-200 text-slate-600 active:[&>svg]:animate-spin dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                onClick={handleRefresh}
                disabled={!site}
              >
                <RefreshCw className="h-4 w-4" />
                刷新状态
              </Button>
            </CardContent>
          </Card>

          <Card className={CARD_CLASS}>
            <CardHeader className="p-5 pb-2">
              <CardTitle className="text-base font-bold text-slate-950 dark:text-slate-100">实时检测项</CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-4">
              <GuardDetectionStatusRow label="手机使用检测" icon={Smartphone} state={phoneAbnormal ? 'danger' : 'normal'} stateLabel={phoneAbnormal ? '异常' : '正常'} />
              <GuardDetectionStatusRow label="俯卧姿态检测" icon={Coffee} state={proneAbnormal ? 'danger' : 'normal'} stateLabel={proneAbnormal ? '异常' : '正常'} />
              <GuardDetectionStatusRow label="车辆看护检测" icon={Car} state={vehicleAbnormal ? 'danger' : 'normal'} stateLabel={vehicleAbnormal ? '异常' : '正常'} />
              <GuardDetectionStatusRow label="保安在岗识别" icon={UserRound} state={guards > 0 ? 'normal' : 'warning'} stateLabel={guards > 0 ? `${guards} 人在岗` : '未在岗'} />
            </CardContent>
          </Card>

          {site && (
            <>
              <Card className={CARD_CLASS}>
                <CardHeader className="p-5 pb-3">
                  <CardTitle className="flex items-center gap-2 text-base font-bold text-slate-950 dark:text-slate-100">
                    <Radio className="h-4 w-4 text-[#1B3FA0] dark:text-blue-300" />
                    检测详情
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-5 px-5 pb-5">
                  <div>
                    <div className="mb-2 flex items-center justify-between text-sm"><span>保安识别置信度</span><span>{Math.round(guardConfidence * 100)}%</span></div>
                    <Progress value={guardConfidence * 100} />
                  </div>
                  <div>
                    <div className="mb-2 flex items-center justify-between text-sm"><span>手机置信度</span><span>{Math.round((status?.metrics.phone_confidence ?? 0) * 100)}%</span></div>
                    <Progress value={(status?.metrics.phone_confidence ?? 0) * 100} />
                  </div>
                  <div>
                    <div className="mb-2 flex items-center justify-between text-sm"><span>头部姿态</span><span>{(status?.metrics.head_down_ratio ?? 0).toFixed(2)}</span></div>
                    <Progress value={Math.min(100, (status?.metrics.head_down_ratio ?? 0) * 300)} />
                  </div>
                </CardContent>
              </Card>

              <Card className={CARD_CLASS}>
                <CardHeader className="p-5 pb-3">
                  <CardTitle className="flex items-center gap-2 text-base font-bold text-slate-950 dark:text-slate-100">
                    <AlertTriangle className="h-4 w-4 text-amber-500" />
                    最近报警
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-5 pb-5">
                  {lastAlarm ? (
                    <div className="space-y-2 rounded-xl border border-rose-100 bg-rose-50 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-semibold text-slate-900">{alarmText(lastAlarm.event_type)}</div>
                        <Badge variant="outline">{Math.round(lastAlarm.confidence * 100)}%</Badge>
                      </div>
                      <div className="text-sm text-slate-600">{lastAlarm.reason}</div>
                      <div className="text-xs text-slate-500">{lastAlarm.created_at}</div>
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500">暂无报警</div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>

        <Card className={cn(CARD_CLASS, 'overflow-hidden lg:col-span-2')}>
              <CardHeader className="border-b border-slate-100 p-4 dark:border-slate-800 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#132C72] text-white">
                  <Camera className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <CardTitle className="text-base font-bold text-slate-950 dark:text-slate-100">视频流</CardTitle>
                  <p className="mt-0.5 truncate text-xs text-slate-400">cam1 · {site?.name ?? '未选择保安室'}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-slate-100 px-2.5 py-1 font-mono text-xs text-slate-500">FPS {status?.fps?.toFixed(1) ?? '--'}</span>
                <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold', status?.running ? 'bg-rose-50 text-rose-600' : 'bg-slate-100 text-slate-500')}>
                  {status?.running && (
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-70" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" />
                    </span>
                  )}
                  {status?.running ? 'LIVE' : '已暂停'}
                </span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {site ? (
              <div className="relative overflow-hidden bg-slate-900">
                <img
                  key={imgKey}
                  src={frameSrc || withFrameNonce(guardRoomSiteFrameUrl(site.id, department))}
                  alt={`${site.name}实时监控`}
                  className={cn('block h-auto w-full saturate-[.85] transition', !status?.running && 'opacity-40 saturate-0')}
                />
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-black/15" aria-hidden="true" />

                <div className="pointer-events-none absolute left-3 right-3 top-3 flex flex-wrap gap-2">
                  <GuardVideoStatusPill label={`cam1 · ${cameraOnline ? '在线' : '离线'}`} state={cameraOnline ? 'normal' : 'danger'} showDot />
                  <GuardVideoStatusPill label={`在岗 ${guards} 人`} state={guards > 0 ? 'normal' : 'neutral'} />
                  <GuardVideoStatusPill label={`手机 ${phoneAbnormal ? '异常' : '正常'}`} state={phoneAbnormal ? 'danger' : 'normal'} />
                  <GuardVideoStatusPill label={`俯卧 ${proneAbnormal ? '异常' : '正常'}`} state={proneAbnormal ? 'danger' : 'normal'} />
                  <GuardVideoStatusPill label={`车辆 ${vehicleAbnormal ? '异常' : '正常'}`} state={vehicleAbnormal ? 'danger' : 'normal'} />
                </div>

                <div className="pointer-events-none absolute bottom-3 right-3 rounded-full bg-black/45 px-2.5 py-1 font-mono text-[10px] text-white/90 backdrop-blur-sm">
                  1080P · H.265
                </div>

                {status?.error && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/60 p-4 sm:p-8">
                    <div className="max-w-xl rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-700 sm:p-6">
                      <div className="mb-2 font-semibold">后端运行异常</div>
                      <div className="break-all text-sm">{status.error}</div>
                    </div>
                  </div>
                )}

                {!status?.running && !status?.error && !loading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-slate-950/45 p-6">
                    <div className="text-center text-white">
                      <Pause className="mx-auto h-11 w-11" />
                      <p className="mt-3 text-lg font-semibold">检测功能已关闭</p>
                      <p className="mt-1 text-sm text-white/70">点击页面上方『开启检测』恢复行为分析</p>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex min-h-72 items-center justify-center bg-slate-900 px-6 text-center text-sm text-slate-300">
                请先在配置管理的保安室管理中新增并选择保安室。
              </div>
            )}
          </CardContent>
        </Card>
      </ResizableMonitorLayout>
    </div>
  )
}

export default MonitorSection
