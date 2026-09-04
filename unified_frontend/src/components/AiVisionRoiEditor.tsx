import { useEffect, useMemo, useState, type PointerEvent } from 'react'
import { AlertTriangle, Eye, MousePointer2, RefreshCw, RotateCcw, Save, Trash2, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DETECTION_CONFIG_CARD_CLASS,
  DetectionConfigCardContent,
  DetectionConfigCardHeader,
} from '@/components/detection/DetectionConfigUi'
import { aiVisionFrameUrl } from '@/lib/aivision'
import { clientPointToImagePoint, imagePixelsPerRenderedPixel } from './AiVisionRoiEditor.geometry'

type Point = {
  x: number
  y: number
}

type RoiMode = 'polygon' | 'rect' | 'line'

type AiVisionRoiEditorProps = {
  title: string
  cameraKey: string
  mode?: RoiMode
  roiJson: string
  regionJson?: string
  disabled?: boolean
  saving?: boolean
  message?: string
  minRoiArea?: number
  onChange: (roiJson: string) => void
  onRegionChange?: (regionJson: string) => void
  onSave: () => void
}

const fallbackSize = { width: 1920, height: 1080 }
const DRAG_THRESHOLD_PX = 8
const DEFAULT_MIN_ROI_AREA = 2500

function roundPoint(point: Point) {
  return [Math.round(point.x), Math.round(point.y)]
}

function rectToPoints(rect: number[]): Point[] {
  const [x1, y1, x2, y2] = rect
  return [
    { x: x1, y: y1 },
    { x: x2, y: y1 },
    { x: x2, y: y2 },
    { x: x1, y: y2 },
  ]
}

function pointsToRect(points: Point[]) {
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  return [
    Math.round(Math.min(...xs)),
    Math.round(Math.min(...ys)),
    Math.round(Math.max(...xs)),
    Math.round(Math.max(...ys)),
  ]
}

function polygonArea(points: Point[]) {
  if (points.length < 3) return 0
  const area = points.reduce((sum, point, index) => {
    const next = points[(index + 1) % points.length]
    return sum + point.x * next.y - next.x * point.y
  }, 0)
  return Math.abs(area) / 2
}

function pointDistance(a: Point, b: Point) {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

function parseRoiPoints(raw: string): Point[] {
  try {
    const parsed = JSON.parse(raw || '[]')
    if (!Array.isArray(parsed) || parsed.length === 0) return []

    if (parsed.length >= 4 && parsed.every((item) => typeof item === 'number')) {
      return rectToPoints(parsed.slice(0, 4) as number[])
    }

    const polygon = Array.isArray(parsed[0]?.[0]) ? parsed[0] : parsed
    if (!Array.isArray(polygon)) return []

    return polygon
      .filter((point) => Array.isArray(point) && point.length >= 2)
      .map((point) => ({ x: Number(point[0]) || 0, y: Number(point[1]) || 0 }))
  } catch {
    return []
  }
}

export function AiVisionRoiEditor({
  title,
  cameraKey,
  mode = 'polygon',
  roiJson,
  regionJson,
  disabled,
  saving,
  message,
  minRoiArea = DEFAULT_MIN_ROI_AREA,
  onChange,
  onRegionChange,
  onSave,
}: AiVisionRoiEditorProps) {
  const [points, setPoints] = useState<Point[]>(() => parseRoiPoints(regionJson || roiJson))
  const [imageSize, setImageSize] = useState(fallbackSize)
  const [nonce, setNonce] = useState(0)
  const [dragStart, setDragStart] = useState<Point | null>(null)
  const [draftPoint, setDraftPoint] = useState<Point | null>(null)
  const [dragPointIndex, setDragPointIndex] = useState<number | null>(null)

  const frameUrl = useMemo(
    () => (cameraKey ? aiVisionFrameUrl(cameraKey, undefined, nonce) : ''),
    [cameraKey, nonce],
  )
  const valid = mode === 'line' ? points.length === 2 : mode === 'rect' ? points.length === 4 : points.length >= 3
  const outOfBounds = points.some(
    (point) => point.x < 0 || point.y < 0 || point.x > imageSize.width || point.y > imageSize.height,
  )
  const roiArea = valid && mode !== 'line' ? polygonArea(points) : 0
  const areaTooSmall = valid && mode !== 'line' && roiArea < minRoiArea
  const canSave = valid && !outOfBounds && !areaTooSmall

  useEffect(() => {
    setPoints(parseRoiPoints(regionJson || roiJson))
  }, [mode, regionJson, roiJson])

  const commitPoints = (nextPoints: Point[]) => {
    setPoints(nextPoints)
    if (mode === 'rect') {
      const rect = nextPoints.length === 4 ? pointsToRect(nextPoints) : []
      const nextJson = JSON.stringify(rect)
      onChange(nextJson)
      onRegionChange?.(nextJson)
      return
    }
    if (mode === 'line') {
      onChange(JSON.stringify(nextPoints.slice(0, 2).map(roundPoint)))
      return
    }
    onChange(JSON.stringify(nextPoints.map(roundPoint)))
  }

  const getPoint = (event: PointerEvent<SVGSVGElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect()
    return clientPointToImagePoint({
      clientX: event.clientX,
      clientY: event.clientY,
      overlayRect: rect,
      imageSize,
    })
  }

  const getHitRadius = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return Math.max(12, 14 * imagePixelsPerRenderedPixel(rect, imageSize))
  }

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (disabled || !cameraKey) return
    const point = getPoint(event)
    event.currentTarget.setPointerCapture(event.pointerId)

    const hitRadius = getHitRadius(event)
    const nearestIndex = points.findIndex((existing) => pointDistance(existing, point) <= hitRadius)
    if (nearestIndex >= 0) {
      setDragPointIndex(nearestIndex)
      setDragStart(point)
      setDraftPoint(null)
      return
    }

    setDragStart(point)
    setDraftPoint(point)
  }

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (disabled || !cameraKey || !dragStart) return
    const point = getPoint(event)
    if (dragPointIndex !== null) {
      const nextPoints = points.map((existing, index) => (index === dragPointIndex ? point : existing))
      commitPoints(nextPoints)
      return
    }
    setDraftPoint(point)
  }

  const handlePointerUp = (event: PointerEvent<SVGSVGElement>) => {
    event.currentTarget.releasePointerCapture(event.pointerId)
    if (dragPointIndex !== null) {
      setDragPointIndex(null)
      setDragStart(null)
      setDraftPoint(null)
      return
    }
    if (!dragStart || !draftPoint) return
    const dragged = pointDistance(dragStart, draftPoint) > DRAG_THRESHOLD_PX * imagePixelsPerRenderedPixel(event.currentTarget.getBoundingClientRect(), imageSize)
    if (mode === 'line') {
      if (dragged) {
        commitPoints([dragStart, draftPoint])
      } else if (points.length === 0) {
        commitPoints([dragStart])
      } else if (points.length === 1) {
        commitPoints([points[0], dragStart])
      } else {
        commitPoints([dragStart])
      }
    } else if (dragged || mode === 'rect') {
      commitPoints(rectToPoints(pointsToRect([dragStart, draftPoint])))
    } else if (mode === 'polygon') {
      commitPoints([...points, dragStart])
    }
    setDragStart(null)
    setDraftPoint(null)
  }

  const displayPoints = dragPointIndex === null && dragStart && draftPoint && pointDistance(dragStart, draftPoint) > 0
    ? mode === 'line'
      ? [dragStart, draftPoint]
      : rectToPoints(pointsToRect([dragStart, draftPoint]))
    : points
  const polyline = displayPoints.map((point) => `${point.x},${point.y}`).join(' ')
  const bbox = displayPoints.length ? pointsToRect(displayPoints) : []

  const useFullFrame = () => {
    commitPoints(rectToPoints([0, 0, imageSize.width, imageSize.height]))
  }

  const clear = () => {
    commitPoints([])
  }

  const undo = () => {
    if (mode === 'rect') {
      clear()
      return
    }
    commitPoints(points.slice(0, -1))
  }

  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader
        icon={MousePointer2}
        tone="rose"
        title={title}
        description="沿用当前摄像头画布、坐标与保存方式，进入本标签后可直接绘制。"
        actions={(
          <Button variant="outline" size="sm" className="gap-2 rounded-xl" onClick={() => setNonce(Date.now())} disabled={!cameraKey}>
            <RefreshCw className="h-4 w-4" />
            刷新画面
          </Button>
        )}
      />
      <DetectionConfigCardContent className="space-y-4">
        <div className="overflow-hidden rounded-2xl border border-slate-900/10 bg-slate-950 shadow-[0_18px_42px_rgba(2,8,23,0.18)]">
          <div className="relative mx-auto max-h-[68vh] w-full">
            <div className="absolute left-3 top-3 z-10 flex items-center gap-2 rounded-md bg-slate-950/75 px-2.5 py-1.5 text-xs font-semibold text-white shadow-sm">
              <Eye className="h-3.5 w-3.5" />
              保存前预览
            </div>
            {frameUrl ? (
              <img
                src={frameUrl}
                alt=""
                className="block h-auto max-h-[68vh] w-full object-contain"
                onLoad={(event) => {
                  const image = event.currentTarget
                  setImageSize({
                    width: image.naturalWidth || fallbackSize.width,
                    height: image.naturalHeight || fallbackSize.height,
                  })
                }}
              />
            ) : (
              <div className="aspect-video w-full" />
            )}
            <svg
              viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
              className="absolute inset-0 h-full w-full touch-none"
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerLeave={() => {
                if (dragPointIndex === null) {
                  setDragStart(null)
                  setDraftPoint(null)
                }
              }}
            >
              {displayPoints.length > 0 ? (
                <>
                  {displayPoints.length > 2 ? (
                    <polygon points={polyline} fill="rgba(14, 165, 233, 0.24)" stroke="rgb(14, 165, 233)" strokeWidth="4" />
                  ) : (
                    <polyline points={polyline} fill="none" stroke="rgb(14, 165, 233)" strokeWidth="4" />
                  )}
                  {displayPoints.map((point, index) => (
                    <g key={`${point.x}-${point.y}-${index}`}>
                      <circle cx={point.x} cy={point.y} r="9" fill="rgb(14, 165, 233)" stroke="white" strokeWidth="3" />
                      <text x={point.x} y={point.y + 4} textAnchor="middle" fontSize="12" fill="white">
                        {index + 1}
                      </text>
                    </g>
                  ))}
                </>
              ) : null}
            </svg>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div className="min-w-0 text-sm text-slate-600">
            <div>{message || (mode === 'line' ? '警戒线修改后点击保存配置生效。' : 'ROI 修改后点击保存配置生效。')}</div>
            <div className="mt-1 font-mono text-xs text-slate-500">
              {mode === 'line'
                ? points.length === 2
                  ? `警戒线: [${Math.round(points[0].x)}, ${Math.round(points[0].y)}] -> [${Math.round(points[1].x)}, ${Math.round(points[1].y)}]`
                  : `端点数: ${points.length}/2`
                : bbox.length === 4
                ? `区域: [${bbox.join(', ')}] · 面积: ${Math.round(roiArea)} px²`
                : mode === 'polygon'
                  ? `顶点数: ${points.length}`
                  : '未绘制区域'}
            </div>
            {outOfBounds || areaTooSmall ? (
              <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  {outOfBounds ? <div>坐标超出当前画面范围，请调整到 0-{imageSize.width} / 0-{imageSize.height} 内。</div> : null}
                  {areaTooSmall ? <div>ROI 面积过小，当前 {Math.round(roiArea)} px²，至少需要 {minRoiArea} px²。</div> : null}
                </div>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="gap-2" onClick={undo} disabled={disabled || points.length === 0}>
              <Undo2 className="h-4 w-4" />
              撤销
            </Button>
            <Button variant="outline" className="gap-2" onClick={clear} disabled={disabled || points.length === 0}>
              <Trash2 className="h-4 w-4" />
              清空
            </Button>
            {mode !== 'line' ? (
              <Button variant="outline" className="gap-2" onClick={useFullFrame} disabled={disabled || !cameraKey}>
                <RotateCcw className="h-4 w-4" />
                全画面
              </Button>
            ) : null}
            <Button className="gap-2" onClick={onSave} disabled={disabled || saving || !canSave}>
              <Save className="h-4 w-4" />
              {saving ? '保存中' : mode === 'line' ? '保存警戒线' : '保存ROI'}
            </Button>
          </div>
        </div>
      </DetectionConfigCardContent>
    </Card>
  )
}
