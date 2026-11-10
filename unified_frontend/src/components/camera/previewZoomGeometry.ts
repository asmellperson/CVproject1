export type PreviewSize = { width: number; height: number }
export type PreviewPoint = { x: number; y: number }
export const DEFAULT_PREVIEW_CENTER: PreviewPoint = { x: 0.5, y: 0.5 }
export const LOCAL_ZOOM_MIN = 1
export const LOCAL_ZOOM_MAX = 8

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

export function previewZoomTransform(viewport: PreviewSize, source: PreviewSize, zoom: number, center: PreviewPoint) {
  const scale = clamp(zoom, LOCAL_ZOOM_MIN, LOCAL_ZOOM_MAX)
  const fit = source.width > 0 && source.height > 0
    ? Math.min(viewport.width / source.width, viewport.height / source.height) : 1
  const width = source.width > 0 ? source.width * fit : viewport.width
  const height = source.height > 0 ? source.height * fit : viewport.height
  const content = { x: (viewport.width - width) / 2, y: (viewport.height - height) / 2, width, height }
  const axis = (length: number, origin: number, extent: number, point: number) => {
    const desired = length / 2 - scale * (origin + clamp(point, 0, 1) * extent)
    // 边缘取景限制在真实画面内；某一轴仍有黑边时保持该轴居中。
    return scale * extent <= length ? length / 2 - scale * (origin + extent / 2)
      : clamp(desired, length - scale * (origin + extent), -scale * origin)
  }
  return { scale, content,
    x: axis(viewport.width, content.x, width, center.x),
    y: axis(viewport.height, content.y, height, center.y) }
}

export function previewPointAt(point: PreviewPoint, viewport: PreviewSize, source: PreviewSize, zoom: number, center: PreviewPoint): PreviewPoint | null {
  if (viewport.width <= 0 || viewport.height <= 0 || source.width <= 0 || source.height <= 0) return null
  const transform = previewZoomTransform(viewport, source, zoom, center)
  // 点击已放大的画面时先逆变换，避免把屏幕坐标当成原图坐标。
  const x = ((point.x - transform.x) / transform.scale - transform.content.x) / transform.content.width
  const y = ((point.y - transform.y) / transform.scale - transform.content.y) / transform.content.height
  if (x < 0 || x > 1 || y < 0 || y > 1) return null
  return { x: clamp(x, 0, 1), y: clamp(y, 0, 1) }
}
