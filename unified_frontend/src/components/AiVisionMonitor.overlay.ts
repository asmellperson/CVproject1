export type OverlayPoint = {
  x: number
  y: number
}

export type OverlayShape = {
  polygons: OverlayPoint[][]
  lines: [OverlayPoint, OverlayPoint][]
}

type ImageSize = {
  width: number
  height: number
}

function toNumber(value: unknown) {
  const next = Number(value)
  return Number.isFinite(next) ? next : 0
}

function pointFromUnknown(value: unknown, imageSize?: ImageSize): OverlayPoint | null {
  if (!Array.isArray(value) || value.length < 2) return null
  let x = toNumber(value[0])
  let y = toNumber(value[1])
  if (imageSize && x >= 0 && x <= 1 && y >= 0 && y <= 1) {
    x *= imageSize.width
    y *= imageSize.height
  }
  return { x, y }
}

function rectToPolygon(rect: unknown[]): OverlayPoint[] {
  const [x1, y1, x2, y2] = rect.map(toNumber)
  return [
    { x: x1, y: y1 },
    { x: x2, y: y1 },
    { x: x2, y: y2 },
    { x: x1, y: y2 },
  ]
}

function normalizePolygons(value: unknown): OverlayPoint[][] {
  if (!Array.isArray(value) || value.length === 0) return []
  if (value.length >= 4 && value.every((item) => typeof item === 'number')) {
    return [rectToPolygon(value)]
  }

  const first = value[0]
  const polygonInputs = Array.isArray(first) && first.length >= 2 && typeof first[0] === 'number' ? [value] : value
  if (!Array.isArray(polygonInputs)) return []

  return polygonInputs
    .map((polygon) => {
      if (!Array.isArray(polygon)) return []
      return polygon.map((point) => pointFromUnknown(point)).filter((point): point is OverlayPoint => Boolean(point))
    })
    .filter((polygon) => polygon.length >= 2)
}

function normalizeLine(value: unknown, imageSize?: ImageSize): [OverlayPoint, OverlayPoint][] {
  if (!Array.isArray(value) || value.length === 0) return []
  if (value.length >= 4 && value.slice(0, 4).every((item) => typeof item === 'number')) {
    const p1 = pointFromUnknown([value[0], value[1]], imageSize)
    const p2 = pointFromUnknown([value[2], value[3]], imageSize)
    return p1 && p2 ? [[p1, p2]] : []
  }
  if (value.length < 2) return []
  const p1 = pointFromUnknown(value[0], imageSize)
  const p2 = pointFromUnknown(value[1], imageSize)
  return p1 && p2 ? [[p1, p2]] : []
}

export function buildAiVisionMonitorOverlay({
  feature,
  value,
  imageSize,
}: {
  feature: string
  value: Record<string, unknown> | null | undefined
  imageSize?: ImageSize
}): OverlayShape {
  const configValue = value || {}
  const region = configValue.region
  const roiPos = configValue.roi_pos
  const roiPolygons = normalizePolygons(roiPos)
  const polygons = feature === 'detect_logistics_single_person'
    ? []
    : feature === 'detect_human' && roiPolygons.length === 0 && Array.isArray(region) && region.length >= 4
      ? normalizePolygons(region)
      : roiPolygons

  return {
    polygons,
    lines: feature === 'blocks' ? normalizeLine(configValue.line_points, imageSize) : [],
  }
}
