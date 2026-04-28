import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { RefreshCw, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  aiVisionFrameUrl,
  getAiVisionCameraKey,
  getAiVisionCameras,
  isAiVisionFeatureEnabled,
  type AiVisionCamera,
} from '@/lib/aivision'

type AiVisionMonitorProps = {
  title: string
  feature: string
}

const FRAME_REFRESH_MS = 200
const PREVIEW_MAX_WIDTH = 960
const PREVIEW_QUALITY = 72

export function AiVisionMonitor({ title, feature }: AiVisionMonitorProps) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [selectedCamera, setSelectedCamera] = useState('')
  const [loading, setLoading] = useState(true)
  const [frameSrc, setFrameSrc] = useState('')
  const [message, setMessage] = useState('正在读取摄像头列表...')
  const selectedCameraRef = useRef('')
  const objectUrlRef = useRef<string | null>(null)

  const selectedCameraInfo = useMemo(
    () => cameras.find((camera) => getAiVisionCameraKey(camera) === selectedCamera || camera.shm_name === selectedCamera),
    [cameras, selectedCamera],
  )

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
      const items = await getAiVisionCameras()
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
  }, [feature])

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

  useEffect(() => {
    if (!selectedCamera) {
      revokeFrameUrl()
      setFrameSrc('')
      return
    }

    let cancelled = false
    let timeoutId: number | undefined
    let controller: AbortController | null = null

    const loadFrame = async () => {
      const startedAt = performance.now()
      controller = new AbortController()
      try {
        const response = await fetch(
          aiVisionFrameUrl(selectedCamera, feature, Date.now(), {
            maxWidth: PREVIEW_MAX_WIDTH,
            quality: PREVIEW_QUALITY,
          }),
          { cache: 'no-store', credentials: 'include', signal: controller.signal },
        )
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
        setMessage('实时画面已连接。')
      } catch (error) {
        if (!cancelled && !(error instanceof DOMException && error.name === 'AbortError')) {
          setMessage('画面读取失败：请确认 AiVision 后端已启动、摄像头运行中，并且该检测功能已启用。')
        }
      } finally {
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
      revokeFrameUrl()
    }
  }, [feature, revokeFrameUrl, selectedCamera])

  return (
    <Card className="overflow-hidden border-slate-200 bg-white/95">
      <CardHeader className="flex flex-col gap-4 border-b bg-slate-50/80 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Video className="h-5 w-5 text-slate-700" />
            {title}
          </CardTitle>
          <p className="mt-1 text-sm text-slate-500">{selectedCameraInfo ? selectedCameraInfo.name : message}</p>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="w-full min-w-0 space-y-2 sm:w-72 sm:min-w-60">
            <Label htmlFor={`${feature}-monitor-camera`}>摄像头</Label>
            <Select
              value={selectedCamera}
              onValueChange={(value) => {
                selectedCameraRef.current = value
                setSelectedCamera(value)
                setMessage('正在读取实时画面...')
              }}
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

      <CardContent className="p-0">
        <div className="relative aspect-video w-full bg-slate-950">
          {selectedCamera ? (
            frameSrc ? (
              <img
                key={`${selectedCamera}-${feature}`}
                src={frameSrc}
                alt={`${title}实时画面`}
                className="h-full w-full object-contain"
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
          {loading && <Skeleton className="absolute inset-4 bg-slate-800/70" />}
        </div>
        <div className="border-t bg-slate-50 px-4 py-3 text-sm text-slate-600">{message}</div>
      </CardContent>
    </Card>
  )
}
