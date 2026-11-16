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
import { clientPointToImagePoint, imagePixelsPerRenderedPixel, normalizedPointsToPixels, parseNormalizedPoints, pixelsToNormalizedPoints } from './AiVisionRoiEditor.geometry'

type Point = {
  x: number
  y: number
}

type RoiMode = 'polygon' | 'rect' | 'line'

type AiVisionRoiEditorProps = {
  title: string
  cameraKey: string
  mode?: RoiMode
  lineLabel?: string
  roiJson: string
  disabled?: boolean
  saving?: boolean
  message?: string
  emptyRoiLabel?: string
  minRoiArea?: number
  frameUrl?: string
  regionLabel?: string
  description?: string
  minPoints?: number
  maxPoints?: number
  allowFullFrame?: boolean
  showSaveButton?: boolean
  onValidityChange?: (valid: boolean) => void
  onChange: (roiJson: string) => void
  onSave: () => void
}

const DRAG_THRESHOLD_PX = 8
const DEFAULT_MIN_ROI_AREA = 2500

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

export function AiVisionRoiEditor({
  title,
  cameraKey,
  mode = 'polygon',
  lineLabel = '警戒线',
  roiJson,
  disabled,
  saving,
  message,
  emptyRoiLabel = '全画面检测（未限定 ROI）',
  minRoiArea = DEFAULT_MIN_ROI_AREA,
  frameUrl: sourceFrameUrl,
  regionLabel = 'ROI',
  description,
  minPoints = 3,
  maxPoints = Infinity,
  allowFullFrame = true,
  showSaveButton = true,
  onValidityChange,
  onChange,
  onSave,
}: AiVisionRoiEditorProps) {
  const [points, setPoints] = useState<Point[]>([])
  const [coordinateError, setCoordinateError] = useState('')
  const [loadedImage, setLoadedImage] = useState<{ frameUrl: string; width: number; height: number } | null>(null)
  const [nonce, setNonce] = useState(0)
  const [dragStart, setDragStart] = useState<Point | null>(null)
  const [draftPoint, setDraftPoint] = useState<Point | null>(null)
  const [dragPointIndex, setDragPointIndex] = useState<number | null>(null)

  const frameUrl = useMemo(
    () => sourceFrameUrl ? `${sourceFrameUrl}${sourceFrameUrl.includes('?') ? '&' : '?'}_frame=${nonce}` : (cameraKey ? aiVisionFrameUrl(cameraKey, undefined, nonce) : ''),
    [cameraKey, nonce, sourceFrameUrl],
  )
  const imageSize = loadedImage?.frameUrl === frameUrl ? loadedImage : null
  const valid = mode === 'line' ? points.length === 2 : mode === 'rect' ? points.length === 4 : points.length >= minPoints && points.length <= maxPoints
  const outOfBounds = points.some(
    (point) => point.x < 0 || point.y < 0 || point.x > (imageSize?.width ?? 0) || point.y > (imageSize?.height ?? 0),
  )
  const roiArea = valid && mode !== 'line' ? polygonArea(points) : 0
  const areaTooSmall = valid && mode !== 'line' && roiArea < minRoiArea
  const canSave = Boolean(imageSize) && !coordinateError && (points.length === 0 || valid) && !outOfBounds && !areaTooSmall

  useEffect(() => { onValidityChange?.(canSave) }, [canSave, onValidityChange])

  useEffect(() => {
    try {
      const normalized = parseNormalizedPoints(roiJson)
      setPoints(imageSize ? normalizedPointsToPixels(normalized, imageSize) : [])
      setCoordinateError('')
    } catch (error) {
      setPoints([])
      setCoordinateError(error instanceof Error ? error.message : 'ROI 坐标无效')
    }
  }, [mode, roiJson, imageSize])

  useEffect(() => {
    setDragStart(null)
    setDraftPoint(null)
    setDragPointIndex(null)
  }, [mode, imageSize])

  const commitPoints = (nextPoints: Point[]) => {
    if (!imageSize) return
    setPoints(nextPoints)
    setCoordinateError('')
    const normalized = pixelsToNormalizedPoints(mode === 'line' ? nextPoints.slice(0, 2) : nextPoints, imageSize)
    onChange(JSON.stringify(normalized))
  }

  const getPoint = (event: PointerEvent<SVGSVGElement>): Point => {
    if (!imageSize) throw new Error('请先加载摄像头实际画面')
    const rect = event.currentTarget.getBoundingClientRect()
    return clientPointToImagePoint({
      clientX: event.clientX,
      clientY: event.clientY,
      overlayRect: rect,
      imageSize,
    })
  }

  const getHitRadius = (event: PointerEvent<SVGSVGElement>) => {
    if (!imageSize) return 0
    const rect = event.currentTarget.getBoundingClientRect()
    return Math.max(12, 14 * imagePixelsPerRenderedPixel(rect, imageSize))
  }

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (disabled || !cameraKey || !imageSize) return
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
    if (disabled || !cameraKey || !imageSize || !dragStart) return
    const point = getPoint(event)
    if (dragPointIndex !== null) {
      const nextPoints = points.map((existing, index) => (index === dragPointIndex ? point : existing))
      commitPoints(nextPoints)
      return
    }
    setDraftPoint(point)
  }

  const handlePointerUp = (event: PointerEvent<SVGSVGElement>) => {
    if (!imageSize) return
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
      if (points.length < maxPoints) commitPoints([...points, dragStart])
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
  const BoundaryShape = displayPoints.length > 2 ? 'polygon' : 'polyline'
  const handleSize = imageSize ? Math.max(imageSize.width, imageSize.height) * 0.012 : 10

  const useFullFrame = () => {
    if (!imageSize) return
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
        description={description}
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
                key={frameUrl}
                src={frameUrl}
                alt=""
                className="block h-auto max-h-[68vh] w-full object-contain"
                onLoad={(event) => {
                  const image = event.currentTarget
                  if (image.naturalWidth > 0 && image.naturalHeight > 0) {
                    setLoadedImage({ frameUrl, width: image.naturalWidth, height: image.naturalHeight })
                  }
                }}
                onError={() => setLoadedImage(null)}
              />
            ) : (
              <div className="aspect-video w-full" />
            )}
            {imageSize && <svg
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
                  <BoundaryShape points={polyline} fill={displayPoints.length > 2 ? 'rgba(34, 211, 238, 0.08)' : 'none'}
                    stroke="rgba(15, 23, 42, 0.7)" strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  <BoundaryShape points={polyline} fill="none" stroke="rgb(34, 211, 238)" strokeWidth="2"
                    strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                  {displayPoints.map((point, index) => (
                    <g key={`${point.x}-${point.y}-${index}`}>
                      <rect x={point.x - handleSize / 2} y={point.y - handleSize / 2} width={handleSize} height={handleSize}
                        rx={handleSize * 0.16} fill="rgb(34, 211, 238)" stroke="rgb(224, 242, 254)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
                      <text x={point.x + handleSize} y={point.y - handleSize * 0.7} fontSize={handleSize * 1.25}
                        fill="white" stroke="rgb(15, 23, 42)" strokeWidth={handleSize * 0.24} strokeLinejoin="round" paintOrder="stroke">
                        {index + 1}
                      </text>
                    </g>
                  ))}
                </>
              ) : null}
            </svg>}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div className="min-w-0 text-sm text-slate-600">
            {message && <div>{message}</div>}
            <div className="mt-1 font-mono text-xs text-slate-500">
              {mode === 'line'
                ? points.length === 2
                  ? `${lineLabel}: [${Math.round(points[0].x)}, ${Math.round(points[0].y)}] -> [${Math.round(points[1].x)}, ${Math.round(points[1].y)}]`
                  : `端点数: ${points.length}/2`
                : points.length === 0 && !coordinateError
                ? emptyRoiLabel
                : bbox.length === 4
                ? `区域: [${bbox.join(', ')}] · 面积: ${Math.round(roiArea)} px²`
                : mode === 'polygon'
                  ? `顶点数: ${points.length}${Number.isFinite(maxPoints) ? ` / ${maxPoints}` : ''}`
                  : '未绘制区域'}
            </div>
            {!imageSize ? <div className="mt-2 text-amber-700">请先加载摄像头画面后再编辑和保存。</div> : null}
            {coordinateError ? <div role="alert" className="mt-2 text-rose-600">{coordinateError}</div> : null}
            {outOfBounds || areaTooSmall ? (
              <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  {outOfBounds ? <div>坐标超出当前画面范围，请调整到 0-{imageSize?.width} / 0-{imageSize?.height} 内。</div> : null}
                  {areaTooSmall ? <div>{regionLabel}面积过小，当前 {Math.round(roiArea)} px²，至少需要 {minRoiArea} px²。</div> : null}
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
            {mode !== 'line' && allowFullFrame ? (
              <Button variant="outline" className="gap-2" onClick={useFullFrame} disabled={disabled || !cameraKey || !imageSize}>
                <RotateCcw className="h-4 w-4" />
                全画面
              </Button>
            ) : null}
            {showSaveButton && <Button className="gap-2" onClick={onSave} disabled={disabled || saving || !canSave}>
              <Save className="h-4 w-4" />
              {saving ? '保存中' : mode === 'line' ? `保存${lineLabel}` : `保存${regionLabel}`}
            </Button>}
          </div>
        </div>
      </DetectionConfigCardContent>
    </Card>
  )
}
