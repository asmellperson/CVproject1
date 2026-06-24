import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Play,
  Pause,
  RefreshCw,
  Camera,
  User,
  Smartphone,
  Coffee,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Activity,
} from 'lucide-react'
import {
  getGuardRoomSiteStatus,
  guardRoomSiteFrameUrl,
  startGuardRoomSiteRuntime,
  stopGuardRoomSiteRuntime,
} from '@/lib/api'
import { useAuth } from '@/auth/useAuth'
import type { BackendStatus, GuardRoomSite } from '@/types'
const POLL_MS = 1000
const FRAME_REFRESH_MS = 200

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

function alarmClass(type?: string) {
  switch (type) {
    case 'absent':
      return 'bg-red-600'
    case 'phone_use':
      return 'bg-orange-500'
    case 'prone_sleep':
      return 'bg-yellow-500'
    case 'vehicle_unattended':
      return 'bg-cyan-600'
    default:
      return 'bg-slate-600'
  }
}

function AlarmIcon({ type }: { type?: string }) {
  switch (type) {
    case 'absent':
      return <XCircle className="w-5 h-5" />
    case 'phone_use':
      return <Smartphone className="w-5 h-5" />
    case 'prone_sleep':
      return <Coffee className="w-5 h-5" />
    case 'vehicle_unattended':
      return <Camera className="w-5 h-5" />
    default:
      return <AlertTriangle className="w-5 h-5" />
  }
}

type MonitorSectionProps = {
  site: GuardRoomSite | null
  sites: GuardRoomSite[]
  selectedSiteId: number | null
  loadingSites: boolean
  onSelectSite: (siteId: number) => void
}

export function MonitorSection({ site, sites, selectedSiteId, loadingSites, onSelectSite }: MonitorSectionProps) {
  const { isAdmin } = useAuth()
  const [status, setStatus] = useState<BackendStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
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
        const next = await getGuardRoomSiteStatus(site.id)
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
  }, [site])

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
        const response = await fetch(`${guardRoomSiteFrameUrl(site.id)}?t=${Date.now()}`, {
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
  }, [imgKey, revokeFrameUrl, site])

  const handleStartStop = async () => {
    if (!isAdmin || !site) return
    setBusy(true)
    try {
      if (status?.running) {
        await stopGuardRoomSiteRuntime(site.id)
      } else {
        await startGuardRoomSiteRuntime(site.id)
      }
      setStatus(await getGuardRoomSiteStatus(site.id))
      setImgKey((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  const handleRefresh = async () => {
    if (!site) return
    try {
      setStatus(await getGuardRoomSiteStatus(site.id))
      setImgKey((value) => value + 1)
    } catch {
      setImgKey((value) => value + 1)
    }
  }

  const lastAlarm = status?.last_alarm ?? null

  const overlayAlarm =
    lastAlarm &&
    (
      (lastAlarm.event_type === 'absent' && status?.decisions.absent) ||
      (lastAlarm.event_type === 'phone_use' && status?.decisions.phone_use) ||
      (lastAlarm.event_type === 'prone_sleep' && status?.decisions.prone_sleep) ||
      (lastAlarm.event_type === 'vehicle_unattended' && status?.decisions.vehicle_unattended)
    )
      ? lastAlarm
      : null
  const currentTime = new Date().toLocaleTimeString('zh-CN')

  return (
    <div className="w-full min-w-0 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold text-slate-900">实时监控</h2>
          <p className="text-slate-500">{site ? `${site.name} 行为分析监控面板` : '选择保安室后查看实时拼接画面'}</p>
        </div>

        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:gap-3">
          <Badge variant={status?.running ? 'default' : 'secondary'} className={`gap-2 ${status?.running ? 'bg-emerald-600' : ''}`}>
            <span className={`h-2 w-2 rounded-full ${status?.running ? 'bg-emerald-200' : 'bg-slate-400'}`} />
            {status?.running ? '检测开启' : '检测关闭'}
          </Badge>

          <Button
            variant={status?.running ? 'destructive' : 'default'}
            size="sm"
            className="gap-2"
            onClick={handleStartStop}
            disabled={!isAdmin || busy || !site}
          >
            {status?.running ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            {busy ? '处理中' : status?.running ? '关闭功能' : '开启功能'}
          </Button>

          <Button variant="outline" size="sm" className="gap-2" onClick={handleRefresh} disabled={!site}>
            <RefreshCw className="w-4 h-4" />
            刷新
          </Button>

        </div>
      </div>

      <Card className="overflow-hidden border-white/80 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.10)] dark:border-slate-800 dark:bg-slate-900/92">
        <CardHeader className="border-b border-slate-100 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] dark:border-slate-800 dark:bg-slate-900">
          <CardTitle className="flex items-center gap-3 text-lg font-black text-[#071d3d] dark:text-slate-100">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_12px_24px_rgba(0,27,67,0.22)] dark:bg-blue-600">
              <Camera className="h-5 w-5" />
            </span>
            监控对象
          </CardTitle>
        </CardHeader>
        <CardContent className="bg-[#f8fbff] p-4 sm:p-5 dark:bg-slate-950/30">
          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="guard-room-monitor-site">保安室名称</Label>
              <Select
                value={selectedSiteId ? String(selectedSiteId) : ''}
                onValueChange={(value) => onSelectSite(Number(value))}
                disabled={loadingSites || sites.length === 0}
              >
                <SelectTrigger id="guard-room-monitor-site" className="w-full bg-white">
                  <SelectValue placeholder={loadingSites ? '正在读取保安室' : '选择保安室'} />
                </SelectTrigger>
                <SelectContent>
                  {sites.map((item) => (
                    <SelectItem key={item.id} value={String(item.id)}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {!site ? (
        <Card>
          <CardContent className="p-6 text-sm text-slate-500">
            请先在配置管理的保安室管理中新增保安室。
          </CardContent>
        </Card>
      ) : null}

      {site ? <Card className="overflow-hidden">
        <CardHeader className="pb-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2">
              <Camera className="w-5 h-5 text-blue-600" />
              视频流
            </CardTitle>
            <div className="flex items-center gap-3 text-sm text-slate-500 sm:gap-4">
              <span>FPS: {status?.fps?.toFixed(1) ?? '--'}</span>
              <span>{currentTime}</span>
            </div>
          </div>
        </CardHeader>

          <CardContent className="p-0">
            <div className="relative w-full overflow-hidden bg-slate-100 dark:bg-slate-950">
              <img
                key={imgKey}
                src={frameSrc || `${guardRoomSiteFrameUrl(site.id)}?t=${Date.now()}`}
                alt={`${site.name}实时监控`}
                className="block h-auto w-full"
              />

            {/* {lastAlarm && (
              <div
                className={`absolute top-3 left-3 max-w-[62%] rounded-xl text-white px-3 py-2 shadow-lg flex items-center gap-2 ${alarmClass(lastAlarm.event_type)}`}
              >
                <AlarmIcon type={lastAlarm.event_type} />
                <div className="min-w-0">
                  <div className="text-sm font-semibold leading-5">
                    {alarmText(lastAlarm.event_type)}
                  </div>
                  <div
                    className="text-xs opacity-90 truncate"
                    title={lastAlarm.reason || ''}
                  >
                    {lastAlarm.reason || ''}
                  </div>
                </div>
              </div>
            )} */}
            {overlayAlarm && (
              <div className={`absolute left-0 right-0 top-0 flex items-center gap-2 px-3 py-2 text-sm text-white sm:gap-3 sm:px-4 sm:py-3 ${alarmClass(overlayAlarm.event_type)}`}>
                <AlarmIcon type={overlayAlarm.event_type} />
                <span className="min-w-0 truncate font-semibold sm:whitespace-normal">
                  ALARM: {alarmText(overlayAlarm.event_type)} | track={overlayAlarm.track_id ?? '-'} | {overlayAlarm.reason}
                </span>
              </div>
            )}

            {status?.error && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60 p-4 sm:p-8">
                <div className="max-w-xl rounded-xl border border-red-200 bg-red-50 p-4 text-red-700 sm:p-6">
                  <div className="font-semibold mb-2">后端运行异常</div>
                  <div className="text-sm break-all">{status.error}</div>
                </div>
              </div>
            )}

            {!status?.running && !status?.error && !loading && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                <div className="text-white text-center">
                  <Pause className="mx-auto mb-3 h-12 w-12 sm:mb-4 sm:h-16 sm:w-16" />
                  <p className="text-lg font-semibold sm:text-xl">算法未启动</p>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card> : null}

      {site ? <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                  <User className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">人员检测</p>
                  <p className="text-lg font-semibold">{status?.counts.persons ?? 0} 人</p>
                </div>
              </div>
              <CheckCircle2 className="w-5 h-5 text-green-500" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                  <Smartphone className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">手机检测</p>
                  <p className="text-lg font-semibold">{status?.counts.phones ?? 0} 个</p>
                </div>
              </div>
              {(status?.decisions.phone_use ?? false) ? (
                <AlertTriangle className="w-5 h-5 text-yellow-500" />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-green-500" />
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
                  <Activity className="w-5 h-5 text-purple-600" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">姿态检测</p>
                  <p className="text-lg font-semibold">{status?.pose_enabled ? '正常' : '未启用'}</p>
                </div>
              </div>
              <CheckCircle2 className="w-5 h-5 text-green-500" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-red-100 rounded-lg flex items-center justify-center">
                  <AlertTriangle className="w-5 h-5 text-red-600" />
                </div>
                <div>
                  <p className="text-sm text-slate-500">当前状态</p>
                  <p className="text-lg font-semibold">
                    {status?.decisions.absent || status?.decisions.prone_sleep || status?.decisions.phone_use || status?.decisions.vehicle_unattended ? '告警中' : '正常'}
                  </p>
                </div>
              </div>
              {status?.decisions.absent || status?.decisions.prone_sleep || status?.decisions.phone_use || status?.decisions.vehicle_unattended ? (
                <AlertTriangle className="w-5 h-5 text-yellow-500" />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-green-500" />
              )}
            </div>
          </CardContent>
        </Card>
      </div> : null}

      {site ? <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>检测详情</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div>
              <div className="flex items-center justify-between text-sm mb-2">
                <span>人员置信度</span>
                <span>{Math.round((status?.metrics.person_confidence ?? 0) * 100)}%</span>
              </div>
              <Progress value={(status?.metrics.person_confidence ?? 0) * 100} />
            </div>

            <div>
              <div className="flex items-center justify-between text-sm mb-2">
                <span>手机置信度</span>
                <span>{Math.round((status?.metrics.phone_confidence ?? 0) * 100)}%</span>
              </div>
              <Progress value={(status?.metrics.phone_confidence ?? 0) * 100} />
            </div>

            <div>
              <div className="flex items-center justify-between text-sm mb-2">
                <span>头部姿态</span>
                <span>{(status?.metrics.head_down_ratio ?? 0).toFixed(2)}</span>
              </div>
              <Progress value={Math.min(100, (status?.metrics.head_down_ratio ?? 0) * 300)} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>最近报警</CardTitle>
          </CardHeader>
          <CardContent>
            {lastAlarm ? (
              <div className="rounded-xl border border-red-100 bg-red-50 p-4 space-y-2">
                <div className="flex items-center justify-between">
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
      </div> : null}
    </div>
  )
}

export default MonitorSection
