import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import {
  Play,
  Pause,
  RotateCcw,
  Camera,
  User,
  Smartphone,
  Coffee,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Activity,
  Circle,
  Square,
  Download,
} from 'lucide-react'
import { frameUrl, getStatus, restartRuntime, startRuntime, stopRuntime } from '@/lib/api'
import { useAuth } from '@/auth/AuthContext'
import type { BackendStatus } from '@/types'
const POLL_MS = 1000
const RECORD_POLL_MS = 2000
const FRAME_REFRESH_MS = 200

function alarmText(type?: string) {
  switch (type) {
    case 'absent':
      return '离岗报警'
    case 'phone_use':
      return '玩手机'
    case 'prone_sleep':
      return '趴睡'
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
    default:
      return <AlertTriangle className="w-5 h-5" />
  }
}

type RecordingStatus = {
  recording: boolean
  output_dir?: string
  current_file?: string | null
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  return fallback
}

function getDetailMessage(data: unknown): string | undefined {
  if (!data || typeof data !== 'object') return undefined
  const detail = (data as { detail?: unknown }).detail
  return typeof detail === 'string' && detail ? detail : undefined
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
    credentials: 'include',
  })
  const data: unknown = await res.json().catch(() => null)
  if (res.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!res.ok) {
    throw new Error(getDetailMessage(data) || `HTTP ${res.status}`)
  }
  return data as T
}

export function MonitorSection() {
  const { isAdmin } = useAuth()
  const [status, setStatus] = useState<BackendStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [imgKey, setImgKey] = useState(0)
  const [frameSrc, setFrameSrc] = useState('')
  const objectUrlRef = useRef<string | null>(null)

  const [recording, setRecording] = useState<RecordingStatus>({
    recording: false,
    output_dir: '-',
    current_file: null,
  })
  const [recordBusy, setRecordBusy] = useState(false)
  const [recordError, setRecordError] = useState('')

  const revokeFrameUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  useEffect(() => {
    let mounted = true

    const fetchStatus = async () => {
      try {
        const next = await getStatus()
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
  }, [])

  useEffect(() => {
    let cancelled = false
    let timeoutId: number | undefined
    let controller: AbortController | null = null

    const loadFrame = async () => {
      const startedAt = performance.now()
      controller = new AbortController()
      try {
        const response = await fetch(`${frameUrl()}?t=${Date.now()}`, {
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
  }, [imgKey, revokeFrameUrl])

  useEffect(() => {
    let mounted = true

    const fetchRecordingStatus = async () => {
      try {
        const next = await apiJson<RecordingStatus>('/api/recording/status')
        if (mounted) {
          setRecording(next)
          setRecordError('')
        }
      } catch (err: unknown) {
        if (mounted) {
          setRecordError(getErrorMessage(err, '录屏状态获取失败'))
        }
      }
    }

    fetchRecordingStatus().catch(() => undefined)
    const timer = window.setInterval(() => {
      fetchRecordingStatus().catch(() => undefined)
    }, RECORD_POLL_MS)

    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  const handleStartStop = async () => {
    if (!isAdmin) return
    setBusy(true)
    try {
      if (status?.running) {
        await stopRuntime()
      } else {
        await startRuntime()
      }
      setStatus(await getStatus())
      setImgKey((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  const handleRestart = async () => {
    if (!isAdmin) return
    setBusy(true)
    try {
      await restartRuntime()
      setStatus(await getStatus())
      setImgKey((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  const handleToggleRecording = async () => {
    if (!isAdmin) return
    setRecordBusy(true)
    try {
      if (recording.recording) {
        await apiJson('/api/recording/stop', { method: 'POST' })
      } else {
        await apiJson('/api/recording/start', { method: 'POST' })
      }
      const next = await apiJson<RecordingStatus>('/api/recording/status')
      setRecording(next)
      setRecordError('')
    } catch (err: unknown) {
      console.error(err)
      setRecordError(getErrorMessage(err, '录屏操作失败'))
    } finally {
      setRecordBusy(false)
    }
  }

  const lastAlarm = status?.last_alarm ?? null

  const overlayAlarm =
    lastAlarm &&
    (
      (lastAlarm.event_type === 'absent' && status?.decisions.absent) ||
      (lastAlarm.event_type === 'phone_use' && status?.decisions.phone_use) ||
      (lastAlarm.event_type === 'prone_sleep' && status?.decisions.prone_sleep)
    )
      ? lastAlarm
      : null
  const currentTime = new Date().toLocaleTimeString('zh-CN')

  return (
    <div className="w-full min-w-0 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-2xl font-bold text-slate-900">实时监控</h2>
          <p className="text-slate-500">保安室行为分析监控面板</p>
        </div>

        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:gap-3">
          <Badge variant={status?.running ? 'default' : 'secondary'} className="px-3 py-1">
            <div className={`w-2 h-2 rounded-full mr-2 ${status?.running ? 'bg-green-400 animate-pulse' : 'bg-gray-400'}`} />
            {status?.running ? '运行中' : '已停止'}
          </Badge>

          <Button variant="outline" size="icon" onClick={handleStartStop} disabled={!isAdmin || busy}>
            {status?.running ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </Button>

          <Button variant="outline" size="icon" onClick={handleRestart} disabled={!isAdmin || busy}>
            <RotateCcw className="w-4 h-4" />
          </Button>

          {!recording.recording ? (
            <Button onClick={handleToggleRecording} disabled={!isAdmin || recordBusy} className="min-w-0 flex-1 gap-2 sm:flex-none">
              <Circle className="w-4 h-4" />
              开启录屏
            </Button>
          ) : (
            <Button onClick={handleToggleRecording} disabled={!isAdmin || recordBusy} variant="destructive" className="min-w-0 flex-1 gap-2 sm:flex-none">
              <Square className="w-4 h-4" />
              停止录屏
            </Button>
          )}

          <div>
            {recording.recording ? (
              <Badge className="bg-red-500 gap-1">
                <Download className="w-3 h-3" />
                录制中
              </Badge>
            ) : (
              <Badge variant="outline">未录制</Badge>
            )}
          </div>
        </div>
      </div>

      <Card className="overflow-hidden">
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
            <div className="relative h-[clamp(220px,56vh,520px)] w-full overflow-hidden bg-slate-950 sm:h-[clamp(520px,68vh,980px)] 2xl:h-[clamp(680px,72vh,1180px)]">
              <img
                key={imgKey}
                src={frameSrc || `${frameUrl()}?t=${Date.now()}`}
                alt="实时监控"
                className="absolute inset-0 h-full w-full object-contain bg-black"
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
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>录屏信息</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div>状态：<strong>{recording.recording ? '录制中' : '未录制'}</strong></div>
          <div>输出目录：</div>
          <div className="break-all rounded border bg-slate-50 px-3 py-2">{recording.output_dir || '-'}</div>
          <div>当前活跃任务：<span>{recording.current_file || '-'}</span></div>
          {recordError ? <div className="text-red-500">错误：{recordError}</div> : null}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
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
                    {status?.decisions.absent || status?.decisions.prone_sleep || status?.decisions.phone_use ? '告警中' : '正常'}
                  </p>
                </div>
              </div>
              {status?.decisions.absent || status?.decisions.prone_sleep || status?.decisions.phone_use ? (
                <AlertTriangle className="w-5 h-5 text-yellow-500" />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-green-500" />
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
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
      </div>
    </div>
  )
}

export default MonitorSection
