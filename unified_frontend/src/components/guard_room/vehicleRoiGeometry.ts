export type Size = {
  width: number
  height: number
}

export type Rect = Size & {
  left: number
  top: number
}

export type ImagePoint = {
  x: number
  y: number
}

export type VehicleRoiPoint = [number, number]

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function roundRatio(value: number) {
  return Math.round(value * 1_000_000) / 1_000_000
}

export function safeImageSize(size: Size): Size {
  return {
    width: Math.max(1, Number.isFinite(size.width) ? size.width : 1),
    height: Math.max(1, Number.isFinite(size.height) ? size.height : 1),
  }
}

export function normalizeVehicleRoi(points: VehicleRoiPoint[] | undefined): VehicleRoiPoint[] {
  return (points || [])
    .filter((point) => Array.isArray(point) && point.length >= 2)
    .map(([x, y]) => [clamp(Number(x) || 0, 0, 1), clamp(Number(y) || 0, 0, 1)] as VehicleRoiPoint)
}

export function vehicleRoiToImagePoints(points: VehicleRoiPoint[] | undefined, size: Size): ImagePoint[] {
  const imageSize = safeImageSize(size)
  return normalizeVehicleRoi(points).map(([x, y]) => ({
    x: Math.round(x * imageSize.width),
    y: Math.round(y * imageSize.height),
  }))
}

export function imagePointsToVehicleRoi(points: ImagePoint[], size: Size): VehicleRoiPoint[] {
  const imageSize = safeImageSize(size)
  return points.map((point) => [
    roundRatio(clamp(point.x / imageSize.width, 0, 1)),
    roundRatio(clamp(point.y / imageSize.height, 0, 1)),
  ])
}

export function parseVehicleRoiText(text: string): VehicleRoiPoint[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [xRaw, yRaw] = line.split(',').map((item) => Number(item.trim()))
      return [xRaw, yRaw] as VehicleRoiPoint
    })
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1)
}

export function formatVehicleRoiText(points: VehicleRoiPoint[] | undefined): string {
  return normalizeVehicleRoi(points)
    .map(([x, y]) => `${x},${y}`)
    .join('\n')
}

export function polygonArea(points: ImagePoint[]) {
  if (points.length < 3) return 0
  const area = points.reduce((sum, point, index) => {
    const next = points[(index + 1) % points.length]
    return sum + point.x * next.y - next.x * point.y
  }, 0)
  return Math.abs(area) / 2
}

export function pointDistance(a: ImagePoint, b: ImagePoint) {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

export function containedImageBox(overlayRect: Rect, imageSize: Size): Rect {
  const safeSize = safeImageSize(imageSize)
  const scale = Math.min(
    overlayRect.width / safeSize.width,
    overlayRect.height / safeSize.height,
  )
  const width = safeSize.width * scale
  const height = safeSize.height * scale

  return {
    left: overlayRect.left + (overlayRect.width - width) / 2,
    top: overlayRect.top + (overlayRect.height - height) / 2,
    width,
    height,
  }
}

export function clientPointToImagePoint({
  clientX,
  clientY,
  overlayRect,
  imageSize,
}: {
  clientX: number
  clientY: number
  overlayRect: Rect
  imageSize: Size
}): ImagePoint {
  const safeSize = safeImageSize(imageSize)
  const imageBox = containedImageBox(overlayRect, safeSize)

  return {
    x: clamp((clientX - imageBox.left) * (safeSize.width / Math.max(1, imageBox.width)), 0, safeSize.width),
    y: clamp((clientY - imageBox.top) * (safeSize.height / Math.max(1, imageBox.height)), 0, safeSize.height),
  }
}

export function imagePixelsPerRenderedPixel(overlayRect: Rect, imageSize: Size) {
  const safeSize = safeImageSize(imageSize)
  const imageBox = containedImageBox(overlayRect, safeSize)
  return safeSize.width / Math.max(1, imageBox.width)
}
