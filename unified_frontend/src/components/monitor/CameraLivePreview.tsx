import { useCallback, useEffect, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { aiVisionFrameUrl } from '@/lib/aivision'
import { AiVisionVideoPreview } from '../AiVisionVideoPreview'
import type { VideoPreviewState } from '../AiVisionVideoPreview.mse'
import { createPreviewFrameBuffer, previewRefreshMs } from '../AiVisionMonitor.frame'
import { useCameraVideoPreview } from '../useCameraVideoPreview'
import { CameraRegionsOverlay } from './CameraRegionsOverlay'
import { previewRegions } from './previewRegions'
import { useCameraPreviewConfig } from './useCameraPreviewConfig'

type Props = { cameraKey: string; feature: string; department: string; enabled?: boolean; fps?: number
  value?: Record<string, unknown> | null; onConnectionChange?: (connected: boolean, message: string) => void }

export function CameraLivePreview(props: Props) {
  // 切换摄像头或启停时销毁旧会话，旧图片、尺寸和异步回调均不能进入新画面。
  return <LivePreview key={`${props.department}:${props.feature}:${props.cameraKey}:${props.enabled ?? true}`} {...props} />
}

function LivePreview({ cameraKey, feature, department, enabled = true, fps, value, onConnectionChange }: Props) {
  const [visible, setVisible] = useState(() => !document.hidden)
  const preview = useCameraVideoPreview({ cameraKey, feature, department, enabled: enabled && visible })
  const denyAccess = preview.onAccessDenied
  const config = useCameraPreviewConfig(cameraKey, feature, enabled && value === undefined)
  const regions = previewRegions(feature, value === undefined ? config.value : value)
  const [frame, setFrame] = useState('')
  const [jpegConnected, setJpegConnected] = useState(false)
  const [videoState, setVideoState] = useState<VideoPreviewState>('connecting')
  const [error, setError] = useState('')
  const [imageDimensions, setImageDimensions] = useState({ width: 0, height: 0 })
  const [videoDimensions, setVideoDimensions] = useState({ width: 0, height: 0 })
  const buffer = useRef<ReturnType<typeof createPreviewFrameBuffer> | null>(null)
  const active = useRef(true)
  const frameEpoch = useRef(0)
  const videoPlaying = preview.mode === 'mse' && videoState === 'playing'
  const show = enabled && visible && preview.mode !== 'denied'
  const jpeg = show && !videoPlaying
  const onVideoStateChange = useCallback((state: VideoPreviewState) => {
    setVideoState(state)
    if (state === 'playing') {
      // 视频接管后丢弃首图及在途图片，重连时也不能展示很早之前的首图。
      frameEpoch.current += 1
      buffer.current?.clear()
      setFrame(''); setJpegConnected(false); setError('')
    }
  }, [])
  const onAccessDenied = useCallback(() => {
    frameEpoch.current += 1
    buffer.current?.clear()
    setFrame(''); setJpegConnected(false)
    denyAccess()
  }, [denyAccess])
  useEffect(() => {
    active.current = true
    const currentBuffer = createPreviewFrameBuffer()
    buffer.current = currentBuffer
    const sync = () => {
      frameEpoch.current += 1
      currentBuffer.clear()
      setFrame(''); setJpegConnected(false); setError(''); setVideoState('connecting')
      setVisible(!document.hidden)
    }
    document.addEventListener('visibilitychange', sync)
    return () => { active.current = false; document.removeEventListener('visibilitychange', sync); currentBuffer.dispose(); buffer.current = null }
  }, [])
  useSerialPoll(async (signal) => {
    const currentBuffer = buffer.current
    if (!currentBuffer) return
    const epoch = frameEpoch.current
    try {
      const response = await fetch(aiVisionFrameUrl(cameraKey, feature, Date.now(), { raw: true, maxWidth: 1280, quality: 85 }),
        { credentials: 'include', cache: 'no-store', signal })
      if (signal.aborted || !active.current) return
      if (response.status === 401 || response.status === 403) {
        if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
        onAccessDenied()
      }
      if (epoch !== frameEpoch.current) return
      if (!response.ok) throw new Error(`原始画面读取失败（${response.status}）`)
      const blob = await response.blob()
      if (signal.aborted || !active.current || epoch !== frameEpoch.current) return
      const url = await currentBuffer.prepare(blob, signal)
      if (signal.aborted || !active.current || epoch !== frameEpoch.current) return
      setFrame(url); setJpegConnected(true); setError('')
    } catch (cause) {
      if (active.current && epoch === frameEpoch.current && (!signal.aborted || signal.reason?.name === 'TimeoutError')) {
        setJpegConnected(false)
        setError(signal.aborted ? '原始画面读取超时，正在重试' : cause instanceof Error ? cause.message : String(cause))
      }
      throw cause
    }
  }, { enabled: jpeg && !!cameraKey, intervalMs: previewRefreshMs(fps), intervalMode: 'from-start', timeoutMs: 5000 })
  const connected = show && (videoPlaying || jpegConnected)
  const message = !enabled ? '摄像头已停用' : !visible ? '页面不可见，已暂停画面'
    : preview.mode === 'denied' ? '无权访问当前摄像头或检测功能'
    : error && preview.mode === 'jpeg' ? error : connected ? '' : '正在连接原始画面…'
  useEffect(() => { onConnectionChange?.(connected, message) }, [connected, message, onConnectionChange])
  const mse = show && preview.mode === 'mse' && preview.url
  const showImage = jpeg && !!frame
  const dimensions = videoPlaying ? videoDimensions : imageDimensions
  return <div className="relative h-full w-full overflow-hidden bg-slate-950">
    {mse && <div className="absolute inset-0" aria-hidden={showImage}><AiVisionVideoPreview url={mse} cameraKey={cameraKey} feature={feature} department={department}
      onFallback={preview.onFallback} onAccessDenied={onAccessDenied} onStateChange={onVideoStateChange}
      onDimensions={(width, height) => setVideoDimensions({ width, height })} /></div>}
    {showImage && <img src={frame} alt="实时原始画面" className="absolute inset-0 h-full w-full bg-slate-950 object-contain"
      onLoad={(event) => { buffer.current?.displayed(event.currentTarget.src); setImageDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight }) }} />}
    {!mse && !showImage && <div className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-300">{message}</div>}
    {show && connected && <CameraRegionsOverlay regions={regions} {...dimensions} />}
    {show && jpeg && (error || preview.fallbackReason) && <p role="status" className="absolute bottom-2 left-2 right-2 rounded bg-slate-950/80 p-2 text-xs text-slate-200">{error || preview.fallbackReason}</p>}
    {show && value === undefined && config.error && <p role="status" className="absolute left-2 right-2 top-2 rounded bg-slate-950/80 p-2 text-xs text-amber-300">{config.error}</p>}
  </div>
}
