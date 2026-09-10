import { clientPointToImagePoint, pixelsToNormalizedPoints, normalizedPointsToPixels, parseNormalizedRoi } from './AiVisionRoiEditor.geometry'

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


const originalSize = { width: 2560, height: 1440 }
const pixels = [{ x: 640, y: 360 }, { x: 1920, y: 360 }, { x: 1920, y: 1080 }, { x: 640, y: 1080 }]
const saved = parseNormalizedRoi(JSON.stringify(pixelsToNormalizedPoints(pixels, originalSize)))
assertDeepEqual(saved, [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]])
assertDeepEqual(normalizedPointsToPixels(saved, originalSize), pixels)
assertDeepEqual(normalizedPointsToPixels(saved, { width: 640, height: 360 }), [
  { x: 160, y: 90 }, { x: 480, y: 90 }, { x: 480, y: 270 }, { x: 160, y: 270 },
])
const [[normalizedX, normalizedY]] = pixelsToNormalizedPoints([point], { width: 800, height: 600 })
assertPoint({ x: normalizedX, y: normalizedY }, { x: 0.5, y: 0.5 })
assertDeepEqual(parseNormalizedRoi('[]'), [])
for (const invalid of [
  '[[100,100],[500,100],[500,500]]', '[[[0,0],[1,0],[1,1]]]', '[0,0,1,1]',
  '[[0,0],[1,1]]', '[[0,0],[0.5,0.5],[1,1]]', '[[true,0],[1,0],[1,1]]',
]) assertThrows(() => parseNormalizedRoi(invalid))
assertThrows(() => pixelsToNormalizedPoints(pixels, { width: 0, height: 0 }))
assertThrows(() => parseNormalizedRoi('[[0.5,0.5],[0.5,0.5]]', 'line'))
assertDeepEqual(parseNormalizedRoi('[[0,0],[1,1]]', 'line'), [[0,0],[1,1]])


function assertDeepEqual(actual: unknown, expected: unknown) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`)
  }
}

function assertThrows(action: () => unknown) {
  try {
    action()
  } catch {
    return
  }
  throw new Error('Expected invalid ROI to be rejected')
}
