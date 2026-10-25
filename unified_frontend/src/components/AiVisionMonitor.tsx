import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import type { DepartmentId } from '@/auth/permissions'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  getAiVisionCameraKey,
  getAiVisionCameras,
  getAiVisionFeatureConfig,
  type AiVisionCamera,
} from '@/lib/aivision'
import {
  buildAiVisionPreviewFrameUrl,
  createPreviewFrameBuffer,
  FRAME_REQUEST_TIMEOUT_MS,
  previewRefreshMs,
  scheduleFrameRequestAbort,
} from './AiVisionMonitor.frame'
import { LogisticsSinglePersonMonitorView } from './logistics_single_person/LogisticsSinglePersonMonitorView'
import { useLogisticsSinglePersonMonitor } from './logistics_single_person/useLogisticsSinglePersonMonitor'
import { HumanDwellMonitorView } from './human_dwell/HumanDwellMonitorView'
import { useHumanDwellMonitor } from './human_dwell/useHumanDwellMonitor'
import { FeatureDashboardMonitorView } from './feature_dashboard/FeatureDashboardMonitorView'
import {
  isFeatureDashboardKey,
  resolveCameraFeatureValue,
  type CameraFeatureValueState,
} from './feature_dashboard/monitorState'
import { useFeatureDashboardAlarms } from './feature_dashboard/useFeatureDashboardAlarms'
import { FaceRecognitionMonitorView } from './face_recognition/FaceRecognitionMonitorView'
import { VisualLanguageMonitorView } from './visual_language_detection/VisualLanguageMonitorView'
import { FenceMonitorView } from './security_fence/FenceMonitorView'
import { TailgatingMonitorView } from './tailgating/TailgatingMonitorView'
import { createPreviewPerformanceRecorder, type PreviewPerformanceReport } from './AiVisionMonitor.performance'
import { AiVisionVideoPreview } from './AiVisionVideoPreview'
import { useCameraVideoPreview } from './useCameraVideoPreview'
import type { VideoPreviewState } from './AiVisionVideoPreview.performance'

type AiVisionMonitorProps = {
  title: string
  feature: string
  department: DepartmentId
  rawPreview?: boolean
  presentation?: 'default' | 'logistics-single-person' | 'human-dwell' | 'feature-dashboard' | 'face-identity' | 'visual-language' | 'security-fence' | 'tailgating'
}

export function AiVisionMonitor({ title, feature, department, presentation = 'default', rawPreview = false }: AiVisionMonitorProps) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [selectedCamera, setSelectedCamera] = useState('')
  const [loading, setLoading] = useState(true)
  const [frameState, setFrameState] = useState<{ key: string; src: string; connected: boolean } | null>(null)
  const [videoState, setVideoState] = useState<{ key: string; state: VideoPreviewState } | null>(null)
  const [message, setMessage] = useState('正在读取摄像头列表...')
  const [featureValueState, setFeatureValueState] = useState<CameraFeatureValueState | null>(null)
  const [isPageVisible, setIsPageVisible] = useState(() => (typeof document === 'undefined' ? true : !document.hidden))
  const selectedCameraRef = useRef('')
  const frameBufferRef = useRef<ReturnType<typeof createPreviewFrameBuffer> | null>(null)
  const framePerformanceRef = useRef<ReturnType<typeof createPreviewPerformanceRecorder> | null>(null)
  const frameKey = `${department}:${feature}:${selectedCamera}:${rawPreview}`
  const frameSrc = frameState?.key === frameKey ? frameState.src : ''
  const needsFeatureValue = ['logistics-single-person', 'human-dwell', 'feature-dashboard'].includes(presentation)
  const videoPreview = useCameraVideoPreview({
    cameraKey: selectedCamera, feature, department, enabled: !!selectedCamera && isPageVisible,
  })
  const frameConnected = videoPreview.mode === 'mse'
    ? videoState?.key === frameKey && videoState.state === 'playing'
    : videoPreview.mode === 'jpeg' && frameState?.key === frameKey && frameState.connected

  const selectedCameraInfo = useMemo(
    () => cameras.find((camera) => getAiVisionCameraKey(camera) === selectedCamera || camera.shm_name === selectedCamera),
    [cameras, selectedCamera],
  )
  const frameRefreshMs = previewRefreshMs(selectedCameraInfo?.fps)
  const featureValue = resolveCameraFeatureValue(featureValueState, selectedCamera)
  const logisticsMonitor = useLogisticsSinglePersonMonitor({
    enabled: presentation === 'logistics-single-person',
    feature,
    selectedCamera,
    selectedCameraName: selectedCameraInfo?.name || '',
  })
  const humanDwellMonitor = useHumanDwellMonitor({
    enabled: presentation === 'human-dwell',
    feature,
    selectedCamera,
    selectedCameraName: selectedCameraInfo?.name || '',
  })
  const featureDashboardKey = isFeatureDashboardKey(feature) ? feature : 'blocks'
  const featureDashboardAlarms = useFeatureDashboardAlarms({
    enabled: presentation === 'feature-dashboard' && isFeatureDashboardKey(feature),
    feature: featureDashboardKey,
    selectedCamera,
    selectedCameraName: selectedCameraInfo?.name || '',
  })

  const refreshCameras = useCallback(async () => {
    setLoading(true)
    setMessage('正在读取摄像头列表...')
    try {
      const items = await getAiVisionCameras(department)
      const featureCameras = getEnabledFeatureCameras(items, feature, department)
      setCameras(featureCameras)
      const currentCamera = selectedCameraRef.current
      const selectedStillEnabled = featureCameras.some((camera) => getAiVisionCameraKey(camera) === currentCamera)
      const nextCamera = selectedStillEnabled ? currentCamera : featureCameras[0] ? getAiVisionCameraKey(featureCameras[0]) : ''
      selectedCameraRef.current = nextCamera
      setSelectedCamera(nextCamera)
      setMessage(nextCamera ? '正在读取实时画面...' : items.length ? '当前功能未添加摄像头，请先在配置管理中添加。' : '当前事业部暂未配置摄像头')
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
    if (!selectedCamera || !needsFeatureValue) {
      setFeatureValueState(null)
      return
    }

    let cancelled = false
    getAiVisionFeatureConfig(feature, selectedCamera)
      .then((payload) => {
        if (!cancelled) setFeatureValueState({ cameraKey: selectedCamera, value: payload.config.value || {} })
      })
      .catch(() => {
        if (!cancelled) setFeatureValueState(null)
      })

    return () => {
      cancelled = true
    }
  }, [feature, needsFeatureValue, selectedCamera])

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
      setFrameState(null)
      return
    }

    if (!isPageVisible) {
      setFrameState(null)
      setMessage('页面不可见，已暂停实时画面刷新。')
      return
    }

    // 持续视频与逐帧 JPEG 共用同一画面位置，试播期间不再并行拉取图片。
    if (videoPreview.mode !== 'jpeg') {
      setFrameState(null)
      return
    }

    let cancelled = false
    let timeoutId: number | undefined
    let requestTimeoutId: ReturnType<typeof setTimeout> | undefined
    let controller: AbortController | null = null
    let hasFrame = false
    const buffer = createPreviewFrameBuffer()
    frameBufferRef.current = buffer
    let lastReport: PreviewPerformanceReport | undefined
    const diagnostics = createPreviewPerformanceRecorder({
      cameraKey: selectedCamera, feature: rawPreview ? '' : feature, department, refreshMs: frameRefreshMs,
      onReport(report) {
        lastReport = report
        window.aivisionPreviewDiagnostics = report
        console.debug('[预览性能]', report)
      },
    })
    framePerformanceRef.current = diagnostics

    const loadFrame = async () => {
      const startedAt = performance.now()
      controller = new AbortController()
      requestTimeoutId = scheduleFrameRequestAbort(controller, FRAME_REQUEST_TIMEOUT_MS)
      try {
        const response = await fetch(
          // 请求触发型检测使用实时原始画面，预览不依赖推理任务或上次检测帧。
          buildAiVisionPreviewFrameUrl(selectedCamera, rawPreview ? '' : feature, Date.now()),
          { cache: 'no-store', credentials: 'include', signal: controller.signal },
        )
        const headersReceivedAt = performance.now()
        if (cancelled) return
        if (response.status === 401) {
          window.dispatchEvent(new Event('aicv:unauthorized'))
        }
        if (response.status === 401 || response.status === 403) {
          buffer.clear()
          hasFrame = false
          setFrameState(null)
        }
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`)
        }

        const blob = await response.blob()
        const bodyReceivedAt = performance.now()
        const nextFrameSrc = await buffer.prepare(blob, controller.signal)
        if (cancelled) return
        diagnostics.completed({
          startedAt, headersReceivedAt, bodyReceivedAt, decodedAt: performance.now(),
          bytes: blob.size, headers: response.headers, src: nextFrameSrc,
        })

        hasFrame = true
        setFrameState({ key: frameKey, src: nextFrameSrc, connected: true })
        setMessage('实时画面已连接。')
      } catch {
        if (!cancelled) {
          diagnostics.failed()
          setFrameState((current) => current?.key === frameKey ? { ...current, connected: false } : current)
          setMessage(hasFrame ? '画面刷新暂不可用，当前显示上一帧，正在重试。'
            : '画面暂不可用，正在重试。请检查摄像头及检测功能运行状态。')
        }
      } finally {
        if (requestTimeoutId) {
          clearTimeout(requestTimeoutId)
          requestTimeoutId = undefined
        }
        if (!cancelled) {
          const elapsed = performance.now() - startedAt
          timeoutId = window.setTimeout(loadFrame, Math.max(0, frameRefreshMs - elapsed))
        }
      }
    }

    setMessage('正在读取实时画面...')
    loadFrame()

    return () => {
      cancelled = true
      controller?.abort()
      if (timeoutId) window.clearTimeout(timeoutId)
      if (requestTimeoutId) clearTimeout(requestTimeoutId)
      buffer.dispose()
      diagnostics.dispose()
      if (frameBufferRef.current === buffer) frameBufferRef.current = null
      if (framePerformanceRef.current === diagnostics) framePerformanceRef.current = null
      if (lastReport && window.aivisionPreviewDiagnostics === lastReport) delete window.aivisionPreviewDiagnostics
    }
  }, [department, feature, frameKey, frameRefreshMs, isPageVisible, rawPreview, selectedCamera, videoPreview.mode])

  const frameContent = (
    <>
      {selectedCamera && videoPreview.mode === 'mse' && videoPreview.url ? (
        <AiVisionVideoPreview key={frameKey} url={videoPreview.url} cameraKey={selectedCamera}
          department={department} feature={feature} onFallback={videoPreview.onFallback}
          onAccessDenied={videoPreview.onAccessDenied} onStateChange={(state) => {
            setVideoState({ key: frameKey, state })
            setMessage(state === 'playing' ? '原始视频已连接，未叠加检测框。' : '正在连接实时原始视频...')
          }} />
      ) : selectedCamera && videoPreview.mode === 'denied' ? (
        <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">
          无权访问当前摄像头或检测功能，请检查登录状态与权限。
        </div>
      ) : selectedCamera && videoPreview.mode === 'checking' ? (
        <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">
          正在连接实时画面...
        </div>
      ) : selectedCamera ? (
        frameSrc ? (
          <img
            key={`${selectedCamera}-${feature}`}
            src={frameSrc}
            alt={`${title}实时画面`}
            className="h-full w-full object-contain"
            onLoad={(event) => {
              frameBufferRef.current?.displayed(event.currentTarget.src)
              framePerformanceRef.current?.displayed(event.currentTarget.src)
            }}
            onError={() => {
              setFrameState((current) => current?.key === frameKey ? { ...current, connected: false } : current)
              setMessage('画面渲染失败，正在等待下一帧。')
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">
            {message}
          </div>
        )
      ) : (
        <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">
          {loading ? '正在读取摄像头...' : message}
        </div>
      )}
      {videoPreview.mode === 'jpeg' && videoPreview.fallbackReason && (
        <div className="absolute bottom-3 left-3 right-3 rounded bg-slate-950/80 px-3 py-1 text-xs text-slate-200">
          {videoPreview.fallbackReason}
        </div>
      )}
      {loading && <Skeleton className="absolute inset-4 bg-slate-800/70" />}
    </>
  )

  if (presentation === 'face-identity') {
    return <FaceRecognitionMonitorView
        department={department}
      cameras={cameras} selectedCamera={selectedCamera} loading={loading} message={message}
      frameConnected={frameConnected} frameContent={frameContent}
      onSelectCamera={handleSelectCamera} onRefreshCameras={refreshCameras}
    />
  }

  if (presentation === 'tailgating') {
    return <TailgatingMonitorView department={department}
      cameras={cameras} selectedCamera={selectedCamera} loading={loading} message={message}
      frameConnected={frameConnected} frameContent={frameContent}
      onSelectCamera={handleSelectCamera} onRefreshCameras={refreshCameras}
    />
  }

  if (presentation === 'security-fence') {
    return <FenceMonitorView department={department}
      cameras={cameras} selectedCamera={selectedCamera} loading={loading} message={message}
      frameConnected={frameConnected} frameContent={frameContent}
      onSelectCamera={handleSelectCamera} onRefreshCameras={refreshCameras}
    />
  }

  if (presentation === 'visual-language') {
    return <VisualLanguageMonitorView key={`${department}:${selectedCamera}`} department={department}
      cameras={cameras} selectedCamera={selectedCamera} loading={loading} message={message}
      frameConnected={frameConnected} frameContent={frameContent}
      onSelectCamera={handleSelectCamera} onRefreshCameras={refreshCameras} />
  }

  if (presentation === 'logistics-single-person') {
    return (
      <LogisticsSinglePersonMonitorView
        title={title}
        cameras={cameras}
        selectedCamera={selectedCamera}
        selectedCameraInfo={selectedCameraInfo}
        loading={loading}
        message={message}
        frameConnected={frameConnected}
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

  if (presentation === 'human-dwell') {
    return (
      <HumanDwellMonitorView
        cameras={cameras}
        selectedCamera={selectedCamera}
        selectedCameraInfo={selectedCameraInfo}
        loading={loading}
        message={message}
        frameConnected={frameConnected}
        frameContent={frameContent}
        featureValue={featureValue}
        status={humanDwellMonitor.status}
        events={humanDwellMonitor.events}
        todayAlarmCount={humanDwellMonitor.todayAlarmCount}
        latestAlarmAt={humanDwellMonitor.latestAlarmAt}
        onSelectCamera={handleSelectCamera}
        onRefreshCameras={refreshCameras}
      />
    )
  }

  if (presentation === 'feature-dashboard' && isFeatureDashboardKey(feature)) {
    return (
      <FeatureDashboardMonitorView
        feature={feature}
        cameras={cameras}
        selectedCamera={selectedCamera}
        selectedCameraInfo={selectedCameraInfo}
        loading={loading}
        message={message}
        frameConnected={frameConnected}
        frameContent={frameContent}
        featureValue={featureValue}
        alarms={featureDashboardAlarms.recent}
        todayAlarmCount={featureDashboardAlarms.todayCount}
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
          <div className="relative aspect-video w-full">
            {frameContent}
        </div>
        </div>
        <div className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">{message}</div>
      </CardContent>
    </Card>
  )
}
