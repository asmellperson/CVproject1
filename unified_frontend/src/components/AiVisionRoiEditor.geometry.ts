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
