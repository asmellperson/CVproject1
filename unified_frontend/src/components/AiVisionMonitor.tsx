import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import type { DepartmentId } from '@/auth/permissions'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  getAiVisionCameraKey,
  getAiVisionCameras,
  type AiVisionCamera,
} from '@/lib/aivision'
import { CameraLivePreview } from './monitor/CameraLivePreview'
import { useCameraPreviewConfig } from './monitor/useCameraPreviewConfig'
import { LogisticsSinglePersonMonitorView } from './logistics_single_person/LogisticsSinglePersonMonitorView'
import { useLogisticsSinglePersonMonitor } from './logistics_single_person/useLogisticsSinglePersonMonitor'
import { HumanDwellMonitorView } from './human_dwell/HumanDwellMonitorView'
import { useHumanDwellMonitor } from './human_dwell/useHumanDwellMonitor'
import { FeatureDashboardMonitorView } from './feature_dashboard/FeatureDashboardMonitorView'
import { isFeatureDashboardKey } from './feature_dashboard/monitorState'
import { useFeatureDashboardAlarms } from './feature_dashboard/useFeatureDashboardAlarms'
import { FaceRecognitionMonitorView } from './face_recognition/FaceRecognitionMonitorView'
import { VisualLanguageMonitorView } from './visual_language_detection/VisualLanguageMonitorView'
import { FenceMonitorView } from './security_fence/FenceMonitorView'
import { TailgatingMonitorView } from './tailgating/TailgatingMonitorView'
import { SmokeMonitorView } from './smoke_detection/SmokeMonitorView'

type AiVisionMonitorProps = {
  title: string
  feature: string
  department: DepartmentId
  presentation?: 'default' | 'logistics-single-person' | 'human-dwell' | 'feature-dashboard' | 'face-identity' | 'visual-language' | 'security-fence' | 'tailgating' | 'smoke'
}

export function AiVisionMonitor({ title, feature, department, presentation = 'default' }: AiVisionMonitorProps) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [selectedCamera, setSelectedCamera] = useState('')
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('正在读取摄像头列表...')
  const [connection, setConnection] = useState<{ key: string; connected: boolean } | null>(null)
  const selectedCameraRef = useRef('')
  const frameKey = `${department}:${feature}:${selectedCamera}`
  const frameConnected = connection?.key === frameKey && connection.connected
  const config = useCameraPreviewConfig(selectedCamera, feature)
  const selectedCameraInfo = useMemo(
    () => cameras.find((camera) => getAiVisionCameraKey(camera) === selectedCamera || camera.shm_name === selectedCamera),
    [cameras, selectedCamera],
  )
  const featureValue = config.value
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
    refreshCameras()
    const handleCamerasChanged = () => {
      refreshCameras()
    }
    window.addEventListener('aivision:cameras-changed', handleCamerasChanged)
    return () => window.removeEventListener('aivision:cameras-changed', handleCamerasChanged)
  }, [refreshCameras])

  const handleConnectionChange = useCallback((connected: boolean, nextMessage: string) => {
    setConnection({ key: frameKey, connected })
    setMessage(nextMessage)
  }, [frameKey])
  const frameContent = <>
    {selectedCamera ? <CameraLivePreview cameraKey={selectedCamera} feature={feature} department={department}
      fps={selectedCameraInfo?.fps} value={featureValue} onConnectionChange={handleConnectionChange} />
      : <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">{message}</div>}
    {config.error && <p role="status" className="absolute left-2 right-2 top-2 rounded bg-slate-950/80 p-2 text-xs text-amber-300">{config.error}</p>}
  </>

  if (presentation === 'face-identity') {
    return <FaceRecognitionMonitorView
        department={department}
      cameras={cameras} selectedCamera={selectedCamera} loading={loading} message={message}
      frameConnected={frameConnected} frameContent={frameContent}
      onSelectCamera={handleSelectCamera} onRefreshCameras={refreshCameras}
    />
  }

  if (presentation === 'smoke') {
    return <SmokeMonitorView key={`${department}:${selectedCamera}`} department={department}
      cameras={cameras} selectedCamera={selectedCamera} loading={loading} message={message}
      frameConnected={frameConnected} frameContent={frameContent}
      onSelectCamera={handleSelectCamera} onRefreshCameras={refreshCameras} />
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
        error={humanDwellMonitor.error}
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
        {message && <div className="mt-4 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">{message}</div>}
      </CardContent>
    </Card>
  )
}
