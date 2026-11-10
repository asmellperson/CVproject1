import { useEffect, useRef, useState, type ReactNode, type SyntheticEvent } from 'react'
import { Crosshair, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { DEFAULT_PREVIEW_CENTER, LOCAL_ZOOM_MAX, LOCAL_ZOOM_MIN, previewPointAt, previewZoomTransform, type PreviewSize } from './previewZoomGeometry'

export function CameraLocalPreview({ children, connected }: { children: ReactNode; connected: boolean }) {
  const viewport = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<PreviewSize>({ width: 0, height: 0 })
  const [source, setSource] = useState<PreviewSize>({ width: 0, height: 0 })
  const [zoom, setZoom] = useState(LOCAL_ZOOM_MIN)
  const [center, setCenter] = useState(DEFAULT_PREVIEW_CENTER)
  const transform = previewZoomTransform(size, source, zoom, center)
  const markerX = transform.x + transform.scale * (transform.content.x + center.x * transform.content.width)
  const markerY = transform.y + transform.scale * (transform.content.y + center.y * transform.content.height)

  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const measure = () => {
      const { width, height } = element.getBoundingClientRect()
      setSize((current) => current.width === width && current.height === height ? current : { width, height })
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    measure()
    return () => observer.disconnect()
  }, [])

  const measureSource = (event: SyntheticEvent<HTMLDivElement>) => {
    const media = event.target
    const dimensions = media instanceof HTMLVideoElement ? { width: media.videoWidth, height: media.videoHeight }
      : media instanceof HTMLImageElement ? { width: media.naturalWidth, height: media.naturalHeight } : null
    if (dimensions?.width && dimensions.height) {
      setSource((current) => current.width === dimensions.width && current.height === dimensions.height ? current : dimensions)
    }
  }
  const reset = () => { setZoom(LOCAL_ZOOM_MIN); setCenter(DEFAULT_PREVIEW_CENTER) }

  return <section className="space-y-3" aria-label="局部查看">
    <div ref={viewport} role="button" tabIndex={connected ? 0 : -1} aria-label="点击画面选择局部查看中心"
      aria-disabled={!connected} className="relative aspect-video cursor-crosshair overflow-hidden rounded-xl bg-slate-950 outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      onLoadCapture={measureSource} onLoadedMetadataCapture={measureSource} onPlayingCapture={measureSource}
      onClick={(event) => {
        if (!connected) return
        const rect = event.currentTarget.getBoundingClientRect()
        const point = previewPointAt({ x: event.clientX - rect.left, y: event.clientY - rect.top }, size, source, zoom, center)
        if (point) setCenter(point)
      }}
      onKeyDown={(event) => {
        if (!connected) return
        const delta = { ArrowLeft: [-0.05, 0], ArrowRight: [0.05, 0], ArrowUp: [0, -0.05], ArrowDown: [0, 0.05] }[event.key]
        if (event.key === 'Home') { event.preventDefault(); reset() }
        else if (delta) { event.preventDefault(); setCenter((point) => ({ x: Math.min(1, Math.max(0, point.x + delta[0])), y: Math.min(1, Math.max(0, point.y + delta[1])) })) }
        else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setCenter(DEFAULT_PREVIEW_CENTER) }
      }}>
      <div data-local-zoom={zoom} data-center-x={center.x} data-center-y={center.y} className="h-full w-full"
        style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`, transformOrigin: '0 0' }}>
        {children}
      </div>
      {connected && <span aria-hidden="true" className="pointer-events-none absolute text-cyan-300 drop-shadow-md"
        style={{ left: markerX, top: markerY, transform: 'translate(-50%, -50%)' }}><Crosshair className="h-6 w-6" /></span>}
    </div>
    <div className="space-y-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold">局部查看 <span className="font-normal text-slate-500 dark:text-slate-400">数字放大</span></p>
        <div className="flex items-center gap-3"><output aria-live="polite" className="text-sm tabular-nums">{zoom.toFixed(1)}×</output>
          <Button type="button" size="sm" variant="outline" disabled={zoom === 1 && center.x === 0.5 && center.y === 0.5} onClick={reset}><RotateCcw className="h-4 w-4" />重置查看</Button></div>
      </div>
      <Slider aria-label="局部查看放大倍数" min={LOCAL_ZOOM_MIN} max={LOCAL_ZOOM_MAX} step={0.1} value={[zoom]}
        disabled={!connected} onValueChange={([value]) => setZoom(value)} />
      <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">点击画面选择中心，拖动滑条放大查看；边缘取景自动限制在原图内。仅调整当前预览，摄像头镜头和 AI 检测视野不变。</p>
    </div>
  </section>
}
