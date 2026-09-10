type Size = {
  width: number
  height: number
}

type Rect = Size & {
  left: number
  top: number
}

type Point = {
  x: number
  y: number
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function containedImageBox(overlayRect: Rect, imageSize: Size): Rect {
  const scale = Math.min(
    overlayRect.width / Math.max(1, imageSize.width),
    overlayRect.height / Math.max(1, imageSize.height),
  )
  const width = imageSize.width * scale
  const height = imageSize.height * scale

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
}): Point {
  const imageBox = containedImageBox(overlayRect, imageSize)

  return {
    x: clamp((clientX - imageBox.left) * (imageSize.width / Math.max(1, imageBox.width)), 0, imageSize.width),
    y: clamp((clientY - imageBox.top) * (imageSize.height / Math.max(1, imageBox.height)), 0, imageSize.height),
  }
}

export function imagePixelsPerRenderedPixel(overlayRect: Rect, imageSize: Size) {
  const imageBox = containedImageBox(overlayRect, imageSize)
  return imageSize.width / Math.max(1, imageBox.width)
}

export type NormalizedRoiPoint = [number, number]
export type NormalizedRoi = NormalizedRoiPoint[]

export function parseNormalizedPoints(raw: string): NormalizedRoi {
  const value: unknown = JSON.parse(raw)
  if (!Array.isArray(value) || !value.every((point) => (
    Array.isArray(point) && point.length === 2
    && point.every((coordinate) => typeof coordinate === 'number'
      && Number.isFinite(coordinate) && coordinate >= 0 && coordinate <= 1)
  ))) throw new Error('坐标必须是 0~1 的单个点集 [[x,y], ...]')
  return value as NormalizedRoi
}

export function parseNormalizedRoi(raw: string, mode: 'polygon' | 'line' = 'polygon'): NormalizedRoi {
  const points = parseNormalizedPoints(raw)
  if (!points.length) return points
  if (mode === 'line') {
    if (points.length !== 2 || points[0].every((value, index) => value === points[1][index])) {
      throw new Error('警戒线需要两个不同的端点')
    }
  } else {
    if (points.length < 3) throw new Error('ROI 至少需要三个顶点')
    const twiceArea = points.reduce((area, point, index) => {
      const next = points[(index + 1) % points.length]
      return area + point[0] * next[1] - next[0] * point[1]
    }, 0)
    if (Math.abs(twiceArea) <= 1e-12) throw new Error('ROI 面积必须大于零')
  }
  return points
}

export function normalizedPointsToPixels(points: NormalizedRoi, imageSize: Size): Point[] {
  return points.map(([x, y]) => ({ x: x * imageSize.width, y: y * imageSize.height }))
}

export function pixelsToNormalizedPoints(points: Point[], imageSize: Size): NormalizedRoi {
  if (imageSize.width <= 0 || imageSize.height <= 0) throw new Error('请先加载摄像头实际画面')
  return points.map(({ x, y }) => [x / imageSize.width, y / imageSize.height])
}
