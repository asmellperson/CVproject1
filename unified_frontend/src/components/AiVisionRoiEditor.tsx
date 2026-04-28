import { useEffect, useMemo, useState, type PointerEvent } from 'react'
import { MousePointer2, RefreshCw, RotateCcw, Save, Trash2, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { aiVisionFrameUrl } from '@/lib/aivision'

type Point = {
  x: number
  y: number
}

type RoiMode = 'polygon' | 'rect'

type AiVisionRoiEditorProps = {
  title: string
  cameraKey: string
  feature?: string
  mode?: RoiMode
  roiJson: string
  regionJson?: string
  disabled?: boolean
  saving?: boolean
  message?: string
  onChange: (roiJson: string) => void
  onRegionChange?: (regionJson: string) => void
  onSave: () => void
}

const fallbackSize = { width: 1920, height: 1080 }
const DRAG_THRESHOLD_PX = 8

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

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
  feature,
  mode = 'polygon',
  roiJson,
  regionJson,
  disabled,
  saving,
  message,
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
    () => (cameraKey ? aiVisionFrameUrl(cameraKey, feature, nonce) : ''),
    [cameraKey, feature, nonce],
  )
  const valid = mode === 'rect' ? points.length === 4 : points.length >= 3

  useEffect(() => {
    // Keep the editable draft in sync when a different camera/config is loaded.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
    onChange(JSON.stringify(nextPoints.map(roundPoint)))
  }

  const getPoint = (event: PointerEvent<SVGSVGElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect()
    return {
      x: clamp((event.clientX - rect.left) * (imageSize.width / rect.width), 0, imageSize.width),
      y: clamp((event.clientY - rect.top) * (imageSize.height / rect.height), 0, imageSize.height),
    }
  }

  const getHitRadius = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return Math.max(12, 14 * (imageSize.width / Math.max(1, rect.width)))
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
    const dragged = pointDistance(dragStart, draftPoint) > DRAG_THRESHOLD_PX * (imageSize.width / Math.max(1, event.currentTarget.getBoundingClientRect().width))
    if (dragged || mode === 'rect') {
      commitPoints(rectToPoints(pointsToRect([dragStart, draftPoint])))
    } else if (mode === 'polygon') {
      commitPoints([...points, dragStart])
    }
    setDragStart(null)
    setDraftPoint(null)
  }

  const displayPoints = dragPointIndex === null && dragStart && draftPoint && pointDistance(dragStart, draftPoint) > 0
    ? rectToPoints(pointsToRect([dragStart, draftPoint]))
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
    <Card className="border-slate-200 bg-white/95">
      <CardHeader className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <CardTitle className="flex items-center gap-2 text-lg">
          <MousePointer2 className="h-5 w-5 text-slate-700" />
          {title}
        </CardTitle>
        <Button variant="outline" size="sm" className="gap-2" onClick={() => setNonce(Date.now())} disabled={!cameraKey}>
          <RefreshCw className="h-4 w-4" />
          刷新画面
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-950">
          <div className="relative mx-auto max-h-[68vh] w-full">
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

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="min-w-0 text-sm text-slate-600">
            <div>{message || 'ROI 修改后点击保存配置生效。'}</div>
            <div className="mt-1 font-mono text-xs text-slate-500">
              {bbox.length === 4
                ? `区域: [${bbox.join(', ')}]`
                : mode === 'polygon'
                  ? `顶点数: ${points.length}`
                  : '未绘制区域'}
            </div>
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
            <Button variant="outline" className="gap-2" onClick={useFullFrame} disabled={disabled || !cameraKey}>
              <RotateCcw className="h-4 w-4" />
              全画面
            </Button>
            <Button className="gap-2" onClick={onSave} disabled={disabled || saving || !valid}>
              <Save className="h-4 w-4" />
              {saving ? '保存中' : '保存ROI'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
