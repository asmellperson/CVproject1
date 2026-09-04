import { clientPointToImagePoint } from './AiVisionRoiEditor.geometry'

function assertPoint(actual: { x: number; y: number }, expected: { x: number; y: number }) {
  if (Math.abs(actual.x - expected.x) > 0.000001 || Math.abs(actual.y - expected.y) > 0.000001) {
    throw new Error(`expected (${expected.x}, ${expected.y}), got (${actual.x}, ${actual.y})`)
  }
}

const point = clientPointToImagePoint({
  clientX: 500,
  clientY: 250,
  overlayRect: { left: 0, top: 0, width: 1000, height: 500 },
  imageSize: { width: 800, height: 600 },
})

assertPoint(point, { x: 400, y: 300 })

const clamped = clientPointToImagePoint({
  clientX: 50,
  clientY: 250,
  overlayRect: { left: 0, top: 0, width: 1000, height: 500 },
  imageSize: { width: 800, height: 600 },
})

assertPoint(clamped, { x: 0, y: 300 })
