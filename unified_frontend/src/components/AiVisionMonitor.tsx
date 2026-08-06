import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, RefreshCw, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  getAiVisionCameraKey,
  getAiVisionCameras,
  getAiVisionFeatureConfig,
  isAiVisionFeatureEnabled,
  type AiVisionCamera,
} from '@/lib/aivision'
import { buildAiVisionMonitorOverlay } from './AiVisionMonitor.overlay'
import {
  buildAiVisionPreviewFrameUrl,
  FRAME_REQUEST_TIMEOUT_MS,
  readFrameCoordinateSize,
  scheduleFrameRequestAbort,
  type FrameCoordinateSize,
} from './AiVisionMonitor.frame'
import { LogisticsSinglePersonMonitorView } from './logistics_single_person/LogisticsSinglePersonMonitorView'
import { useLogisticsSinglePersonMonitor } from './logistics_single_person/useLogisticsSinglePersonMonitor'

type AiVisionMonitorProps = {
  title: string
  feature: string
  department?: string
  presentation?: 'default' | 'logistics-single-person'
}

const FRAME_REFRESH_MS = 200
const fallbackImageSize = { width: 1920, height: 1080 }

export function AiVisionMonitor({ title, feature, department, presentation = 'default' }: AiVisionMonitorProps) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [selectedCamera, setSelectedCamera] = useState('')
  const [loading, setLoading] = useState(true)
  const [frameSrc, setFrameSrc] = useState('')
  const [message, setMessage] = useState('正在读取摄像头列表...')
  const [featureValue, setFeatureValue] = useState<Record<string, unknown> | null>(null)
  const [imageSize, setImageSize] = useState(fallbackImageSize)
  const [isPageVisible, setIsPageVisible] = useState(() => (typeof document === 'undefined' ? true : !document.hidden))
  const selectedCameraRef = useRef('')
  const objectUrlRef = useRef<string | null>(null)
  const frameCoordinateSizeRef = useRef<FrameCoordinateSize | null>(null)

  const selectedCameraInfo = useMemo(
    () => cameras.find((camera) => getAiVisionCameraKey(camera) === selectedCamera || camera.shm_name === selectedCamera),
    [cameras, selectedCamera],
  )
  const overlay = useMemo(
    () => buildAiVisionMonitorOverlay({ feature, value: featureValue, imageSize }),
    [feature, featureValue, imageSize],
  )
  const logisticsMonitor = useLogisticsSinglePersonMonitor({
    enabled: presentation === 'logistics-single-person',
    selectedCamera,
    selectedCameraName: selectedCameraInfo?.name || '',
  })

  const revokeFrameUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  const refreshCameras = useCallback(async () => {
    setLoading(true)
    setMessage('正在读取摄像头列表...')
    try {
      const items = await getAiVisionCameras(department)
      const featureCameras = items.filter((camera) => isAiVisionFeatureEnabled(camera, feature))
      setCameras(featureCameras)
      const currentCamera = selectedCameraRef.current
      const selectedStillEnabled = featureCameras.some((camera) => getAiVisionCameraKey(camera) === currentCamera)
      const nextCamera = selectedStillEnabled ? currentCamera : featureCameras[0] ? getAiVisionCameraKey(featureCameras[0]) : ''
      selectedCameraRef.current = nextCamera
      setSelectedCamera(nextCamera)
      setMessage(nextCamera ? '正在读取实时画面...' : '当前功能未添加摄像头，请先在配置管理中添加。')
    } catch (error) {
      setMessage(`摄像头列表读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setLoading(false)
    }
  }, [feature, department])

  const handleSelectCamera = useCallback((value: string) => {
    selectedCameraRef.current = value
    setSelectedCamera(value)
    setMessage('正在读取实时画面...')
  }, [])

  useEffect(() => {
    selectedCameraRef.current = selectedCamera
  }, [selectedCamera])

  useEffect(() => {
    if (!selectedCamera) {
      setFeatureValue(null)
      return
    }

    let cancelled = false
    getAiVisionFeatureConfig(feature, selectedCamera)
      .then((payload) => {
        if (!cancelled) setFeatureValue(payload.config.value || {})
      })
      .catch(() => {
        if (!cancelled) setFeatureValue(null)
      })

    return () => {
      cancelled = true
    }
  }, [feature, selectedCamera])

  useEffect(() => {
    refreshCameras()
    const handleCamerasChanged = () => {
      refreshCameras()
    }
    window.addEventListener('aivision:cameras-changed', handleCamerasChanged)
    return () => window.removeEventListener('aivision:cameras-changed', handleCamerasChanged)
  }, [refreshCameras])

  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsPageVisible(!document.hidden)
    }

    handleVisibilityChange()
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  useEffect(() => {
    if (!selectedCamera) {
      revokeFrameUrl()
      setFrameSrc('')
      return
    }

    if (!isPageVisible) {
      revokeFrameUrl()
      setFrameSrc('')
      setMessage('页面不可见，已暂停实时画面刷新。')
      return
    }

    let cancelled = false
    let timeoutId: number | undefined
    let requestTimeoutId: ReturnType<typeof setTimeout> | undefined
    let controller: AbortController | null = null

    const loadFrame = async () => {
      const startedAt = performance.now()
      controller = new AbortController()
      requestTimeoutId = scheduleFrameRequestAbort(controller, FRAME_REQUEST_TIMEOUT_MS)
      try {
        const response = await fetch(
          buildAiVisionPreviewFrameUrl(selectedCamera, feature, Date.now()),
          { cache: 'no-store', credentials: 'include', signal: controller.signal },
        )
        if (response.status === 401) {
          window.dispatchEvent(new Event('aicv:unauthorized'))
        }
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`)
        }

        const frameCoordinateSize = readFrameCoordinateSize(response.headers)
        frameCoordinateSizeRef.current = frameCoordinateSize
        if (frameCoordinateSize) {
          setImageSize(frameCoordinateSize)
        }
        const blob = await response.blob()
        if (requestTimeoutId) {
          clearTimeout(requestTimeoutId)
          requestTimeoutId = undefined
        }
        if (cancelled) return

        const nextFrameSrc = URL.createObjectURL(blob)
        revokeFrameUrl()
        objectUrlRef.current = nextFrameSrc
        setFrameSrc(nextFrameSrc)
        setMessage('实时画面已连接。')
      } catch {
        if (!cancelled) {
          revokeFrameUrl()
          setFrameSrc('')
          setMessage('画面读取失败：请确认 AiVision 后端已启动、摄像头运行中，并且该检测功能已启用。')
        }
      } finally {
        if (requestTimeoutId) {
          clearTimeout(requestTimeoutId)
          requestTimeoutId = undefined
        }
        if (!cancelled) {
          const elapsed = performance.now() - startedAt
          timeoutId = window.setTimeout(loadFrame, Math.max(0, FRAME_REFRESH_MS - elapsed))
        }
      }
    }

    setFrameSrc('')
    setMessage('正在读取实时画面...')
    loadFrame()

    return () => {
      cancelled = true
      controller?.abort()
      if (timeoutId) window.clearTimeout(timeoutId)
      if (requestTimeoutId) clearTimeout(requestTimeoutId)
      revokeFrameUrl()
    }
  }, [feature, isPageVisible, revokeFrameUrl, selectedCamera])

  const frameContent = (
    <>
      {selectedCamera ? (
        frameSrc ? (
          <img
            key={`${selectedCamera}-${feature}`}
            src={frameSrc}
            alt={`${title}实时画面`}
            className="h-full w-full object-contain"
            onLoad={(event) => {
              const image = event.currentTarget
              const frameCoordinateSize = frameCoordinateSizeRef.current
              setImageSize(
                frameCoordinateSize || {
                  width: image.naturalWidth || fallbackImageSize.width,
                  height: image.naturalHeight || fallbackImageSize.height,
                },
              )
            }}
            onError={() => setMessage('画面渲染失败：请刷新后重试。')}
          />
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">
            正在读取实时画面...
          </div>
        )
      ) : (
        <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">
          {loading ? '正在读取摄像头...' : message}
        </div>
      )}
      {frameSrc && (overlay.polygons.length > 0 || overlay.lines.length > 0) ? (
        <svg
          viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
          className="pointer-events-none absolute inset-0 h-full w-full"
          preserveAspectRatio="xMidYMid meet"
        >
          {overlay.polygons.map((polygon, index) => (
            <polygon
              key={`roi-${index}`}
              points={polygon.map((point) => `${point.x},${point.y}`).join(' ')}
              fill="rgba(14, 165, 233, 0.16)"
              stroke="rgb(14, 165, 233)"
              strokeWidth="4"
            />
          ))}
          {overlay.lines.map(([start, end], index) => (
            <line
              key={`line-${index}`}
              x1={start.x}
              y1={start.y}
              x2={end.x}
              y2={end.y}
              stroke="rgb(239, 68, 68)"
              strokeWidth="5"
              strokeLinecap="round"
            />
          ))}
        </svg>
      ) : null}
      {loading && <Skeleton className="absolute inset-4 bg-slate-800/70" />}
    </>
  )

  if (presentation === 'logistics-single-person') {
    return (
      <LogisticsSinglePersonMonitorView
        cameras={cameras}
        selectedCamera={selectedCamera}
        selectedCameraInfo={selectedCameraInfo}
        loading={loading}
        message={message}
        frameConnected={Boolean(frameSrc)}
        frameContent={frameContent}
        featureValue={featureValue}
        status={logisticsMonitor.status}
        events={logisticsMonitor.events}
        todayAlarmCount={logisticsMonitor.todayAlarmCount}
        onSelectCamera={handleSelectCamera}
        onRefreshCameras={refreshCameras}
      />
    )
  }

  return (
    <Card className="overflow-hidden border-white/80 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92">
      <CardHeader className="flex flex-col gap-4 border-b border-slate-100 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] lg:flex-row lg:items-center lg:justify-between dark:border-slate-800 dark:bg-slate-900">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_12px_24px_rgba(0,27,67,0.22)] dark:bg-blue-600">
            <Video className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <CardTitle className="truncate text-lg font-black text-[#071d3d] dark:text-slate-100">{title}</CardTitle>
            <p className="mt-1 truncate text-sm font-medium text-slate-500 dark:text-slate-400">{selectedCameraInfo ? selectedCameraInfo.name : message}</p>
          </div>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="w-full min-w-0 space-y-2 sm:w-72 sm:min-w-60">
            <Label htmlFor={`${feature}-monitor-camera`}>摄像头</Label>
            <Select
              value={selectedCamera}
              onValueChange={handleSelectCamera}
              disabled={loading || cameras.length === 0}
            >
              <SelectTrigger id={`${feature}-monitor-camera`} className="w-full bg-white">
                <SelectValue placeholder={loading ? '正在读取摄像头' : '选择摄像头'} />
              </SelectTrigger>
              <SelectContent>
                {cameras.map((camera) => {
                  const key = getAiVisionCameraKey(camera)
                  return (
                    <SelectItem key={key} value={key}>
                      {camera.name}
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" className="gap-2" onClick={refreshCameras} disabled={loading}>
              <RefreshCw className="h-4 w-4" />
              {loading ? '读取中' : '刷新'}
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="bg-[#f8fbff] p-4 dark:bg-slate-950/30">
        <div className="relative overflow-hidden rounded-2xl border border-slate-900/10 bg-slate-950 shadow-[0_18px_42px_rgba(2,8,23,0.18)]">
          <div className="absolute left-4 top-4 z-[1] flex items-center gap-2 rounded-full border border-white/10 bg-slate-950/72 px-3 py-1.5 text-xs font-semibold text-slate-200 backdrop-blur">
            <Activity className="h-3.5 w-3.5 text-emerald-400" />
            实时检测
          </div>
          <div className="relative aspect-video w-full">
            {frameContent}
        </div>
        </div>
        <div className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">{message}</div>
      </CardContent>
    </Card>
  )
}
