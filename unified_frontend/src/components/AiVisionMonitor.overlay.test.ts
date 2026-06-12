import { buildAiVisionMonitorOverlay } from './AiVisionMonitor.overlay'

function assertEqual(actual: unknown, expected: unknown) {
  const actualJson = JSON.stringify(actual)
  const expectedJson = JSON.stringify(expected)
  if (actualJson !== expectedJson) {
    throw new Error(`expected ${expectedJson}, got ${actualJson}`)
  }
}

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'detect_phone',
    value: { roi_pos: [[[10, 20], [110, 20], [110, 120], [10, 120]]] },
  }),
  {
    polygons: [[{ x: 10, y: 20 }, { x: 110, y: 20 }, { x: 110, y: 120 }, { x: 10, y: 120 }]],
    lines: [],
  },
)

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'detect_human',
    value: {
      roi_pos: [[10, 20], [110, 20], [70, 120]],
      region: [10, 20, 110, 120],
    },
  }),
  {
    polygons: [[{ x: 10, y: 20 }, { x: 110, y: 20 }, { x: 70, y: 120 }]],
    lines: [],
  },
)

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'detect_human',
    value: { roi_pos: [], region: [10, 20, 110, 120] },
  }),
  {
    polygons: [[{ x: 10, y: 20 }, { x: 110, y: 20 }, { x: 110, y: 120 }, { x: 10, y: 120 }]],
    lines: [],
  },
)

assertEqual(
  buildAiVisionMonitorOverlay({
    feature: 'blocks',
    value: { line_points: [[0.25, 0.5], [0.75, 0.5]] },
    imageSize: { width: 800, height: 600 },
  }),
  {
    polygons: [],
    lines: [[{ x: 200, y: 300 }, { x: 600, y: 300 }]],
  },
)
