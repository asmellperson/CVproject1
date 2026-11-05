export type RegionPoint = [number, number]
export type PreviewRegion = { label: string; points: RegionPoint[]; line?: boolean; directions?: number[] }

function points(value: unknown): RegionPoint[] {
  if (!Array.isArray(value)) return []
  return value.every((point) => Array.isArray(point) && point.length === 2
    && point.every((coordinate) => typeof coordinate === 'number' && Number.isFinite(coordinate) && coordinate >= 0 && coordinate <= 1))
    ? value as RegionPoint[] : []
}

export function previewRegions(feature: string, value: Record<string, unknown> | null): PreviewRegion[] {
  if (!value) return []
  const rawPolygon = feature === 'guard_behavior' ? value.vehicle_roi_pos : value.roi_pos
  const polygon = points(rawPolygon)
  const regions: PreviewRegion[] = polygon.length >= 3
    ? [{ label: feature === 'guard_behavior' ? '车辆检测区域' : '检测区域', points: polygon }]
    : []
  const line = points(value.line_points)
  if (line.length === 2) {
    const direction = Number(feature === 'blocks' ? value.alarm_side : value.direction)
    regions.push({ label: feature === 'blocks' ? '警戒线' : '过闸判定线', points: line, line: true,
      directions: feature === 'tailgating' && direction === 0 ? [-1, 1] : [direction < 0 ? -1 : 1] })
  }
  return regions
}

export function regionDirection(points: RegionPoint[], width: number, height: number, direction: number) {
  const [[x1, y1], [x2, y2]] = points
  const dx = (x2 - x1) * width
  const dy = (y2 - y1) * height
  const length = Math.hypot(dx, dy)
  if (!length) return null
  const distance = Math.min(width, height) * 0.045
  const cx = (x1 + x2) * width / 2
  const cy = (y1 + y2) * height / 2
  const nx = -dy / length * direction
  const ny = dx / length * direction
  return { x1: cx + nx * distance * 0.3, y1: cy + ny * distance * 0.3,
    x2: cx + nx * distance, y2: cy + ny * distance }
}
