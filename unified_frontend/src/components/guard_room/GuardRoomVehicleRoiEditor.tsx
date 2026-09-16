import type { DepartmentId } from '@/auth/permissions'
import { useEffect, useMemo, useState, type PointerEvent } from 'react'
import { AlertTriangle, Eye, MousePointer2, RefreshCw, RotateCcw, Save, Trash2, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { guardRoomSiteCameraFrameUrl } from '@/lib/api'
import {
  clientPointToImagePoint,
  imagePixelsPerRenderedPixel,
  imagePointsToVehicleRoi,
  pointDistance,
  polygonArea,
  safeImageSize,
  vehicleRoiToImagePoints,
  type ImagePoint,
  type Size,
  type VehicleRoiPoint,
} from './vehicleRoiGeometry'

type GuardRoomVehicleRoiEditorProps = {
  siteId: number | null
  department: DepartmentId
  cameraId: string
  cameraLabel?: string
  roi: VehicleRoiPoint[]
  fallbackSize: Size
  disabled?: boolean
  saving?: boolean
  message?: string
  minRoiArea?: number
  onChange: (roi: VehicleRoiPoint[]) => void
  onSave: () => void
}

const DRAG_THRESHOLD_PX = 8
const DEFAULT_MIN_ROI_AREA = 2500

function roundPoint(point: ImagePoint) {
  return {
    x: Math.round(point.x),
    y: Math.round(point.y),
  }
}

function pointsToRect(points: ImagePoint[]) {
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  return [
    Math.round(Math.min(...xs)),
    Math.round(Math.min(...ys)),
    Math.round(Math.max(...xs)),
    Math.round(Math.max(...ys)),
  ]
}

function rectToPoints(rect: number[]): ImagePoint[] {
  const [x1, y1, x2, y2] = rect
  return [
    { x: x1, y: y1 },
    { x: x2, y: y1 },
    { x: x2, y: y2 },
    { x: x1, y: y2 },
  ]
}

export function GuardRoomVehicleRoiEditor({
  siteId,
  department,
  cameraId,
  cameraLabel,
  roi,
  fallbackSize,
  disabled,
  saving,
  message,
  minRoiArea = DEFAULT_MIN_ROI_AREA,
  onChange,
  onSave,
}: GuardRoomVehicleRoiEditorProps) {
  const fallbackWidth = fallbackSize.width
  const fallbackHeight = fallbackSize.height
  const [imageSize, setImageSize] = useState(() => safeImageSize(fallbackSize))
  const [points, setPoints] = useState<ImagePoint[]>(() => vehicleRoiToImagePoints(roi, safeImageSize(fallbackSize)))
  const [nonce, setNonce] = useState(0)
  const [dragStart, setDragStart] = useState<ImagePoint | null>(null)
  const [draftPoint, setDraftPoint] = useState<ImagePoint | null>(null)
  const [dragPointIndex, setDragPointIndex] = useState<number | null>(null)

  const frameUrl = useMemo(() => {
    if (!siteId || !cameraId) return ''
    return guardRoomSiteCameraFrameUrl(siteId, cameraId, nonce, department)
  }, [cameraId, department, nonce, siteId])

  useEffect(() => {
    const nextSize = safeImageSize({ width: fallbackWidth, height: fallbackHeight })
    setImageSize((current) => (
      current.width === nextSize.width && current.height === nextSize.height ? current : nextSize
    ))
  }, [fallbackHeight, fallbackWidth])

  useEffect(() => {
    setPoints(vehicleRoiToImagePoints(roi, imageSize))
  }, [imageSize, roi])

  const commitPoints = (nextPoints: ImagePoint[]) => {
    const roundedPoints = nextPoints.map(roundPoint)
    setPoints(roundedPoints)
    onChange(imagePointsToVehicleRoi(roundedPoints, imageSize))
  }

  const getPoint = (event: PointerEvent<SVGSVGElement>): ImagePoint => {
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
    if (disabled || !siteId || !cameraId) return
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
    if (disabled || !siteId || !cameraId || !dragStart) return
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
    if (dragged) {
      commitPoints(rectToPoints(pointsToRect([dragStart, draftPoint])))
    } else {
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
  const roiArea = displayPoints.length >= 3 ? polygonArea(displayPoints) : 0
  const valid = points.length >= 3
  const outOfBounds = points.some(
    (point) => point.x < 0 || point.y < 0 || point.x > imageSize.width || point.y > imageSize.height,
  )
  const areaTooSmall = valid && roiArea < minRoiArea
  const canSave = valid && !outOfBounds && !areaTooSmall

  const useFullFrame = () => {
    commitPoints(rectToPoints([0, 0, imageSize.width, imageSize.height]))
  }

  const clear = () => {
    commitPoints([])
  }

  const undo = () => {
    commitPoints(points.slice(0, -1))
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3 text-lg font-black text-[#10264d]">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500 text-white shadow-amber-500/20">
            <MousePointer2 className="h-5 w-5" />
          </span>
          <div>
            <div>车辆检测 ROI 绘制</div>
            <div className="mt-1 text-xs font-semibold text-slate-500">
              {cameraId}{cameraLabel ? ` · ${cameraLabel}` : ''}
            </div>
          </div>
        </div>
        <Button variant="outline" size="sm" className="gap-2" onClick={() => setNonce(Date.now())} disabled={!siteId || !cameraId}>
          <RefreshCw className="h-4 w-4" />
          刷新画面
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-900/10 bg-slate-950 shadow-[0_18px_42px_rgba(2,8,23,0.16)]">
        <div className="relative mx-auto max-h-[70dvh] w-full">
          <div className="absolute left-3 top-3 z-10 flex items-center gap-2 rounded-md bg-slate-950/75 px-2.5 py-1.5 text-xs font-semibold text-white shadow-sm">
            <Eye className="h-3.5 w-3.5" />
            单路画面
          </div>
          {frameUrl ? (
            <img
              src={frameUrl}
              alt=""
              className="block h-auto max-h-[70dvh] w-full object-contain"
              onLoad={(event) => {
                const image = event.currentTarget
                setImageSize(safeImageSize({
                  width: image.naturalWidth || fallbackSize.width,
                  height: image.naturalHeight || fallbackSize.height,
                }))
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
                  <polygon points={polyline} fill="rgba(245, 158, 11, 0.24)" stroke="rgb(217, 119, 6)" strokeWidth="4" />
                ) : (
                  <polyline points={polyline} fill="none" stroke="rgb(217, 119, 6)" strokeWidth="4" />
                )}
                {displayPoints.map((point, index) => (
                  <g key={`${point.x}-${point.y}-${index}`}>
                    <circle cx={point.x} cy={point.y} r="9" fill="rgb(217, 119, 6)" stroke="white" strokeWidth="3" />
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

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-100 bg-amber-50/60 px-4 py-4">
        <div className="min-w-0 text-sm text-slate-600">
          <div>{message || '车辆 ROI 修改后点击保存配置生效。'}</div>
          <div className="mt-1 font-mono text-xs text-slate-500">
            {bbox.length === 4 ? `区域: [${bbox.join(', ')}] · 面积: ${Math.round(roiArea)} px² · 顶点数: ${points.length}` : `顶点数: ${points.length}`}
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
          <Button variant="outline" className="gap-2" onClick={useFullFrame} disabled={disabled || !siteId || !cameraId}>
            <RotateCcw className="h-4 w-4" />
            全画面
          </Button>
          <Button className="gap-2 bg-amber-600 hover:bg-amber-700" onClick={onSave} disabled={disabled || saving || !canSave || !siteId || !cameraId}>
            <Save className="h-4 w-4" />
            {saving ? '保存中' : '保存ROI'}
          </Button>
        </div>
      </div>
    </div>
  )
}
