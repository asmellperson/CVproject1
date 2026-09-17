import {
  imagePointsToVehicleRoi,
  vehicleRoiToImagePoints,
} from './vehicleRoiGeometry'

function assertDeepEqual(actual: unknown, expected: unknown) {
  const actualText = JSON.stringify(actual)
  const expectedText = JSON.stringify(expected)
  if (actualText !== expectedText) {
    throw new Error(`expected ${expectedText}, got ${actualText}`)
  }
}

assertDeepEqual(
  vehicleRoiToImagePoints(
    [
      [0.25, 0.5],
      [1, 1],
    ],
    { width: 1920, height: 1080 },
  ),
  [
    { x: 480, y: 540 },
    { x: 1920, y: 1080 },
  ],
)

assertDeepEqual(
  imagePointsToVehicleRoi(
    [
      { x: 480, y: 540 },
      { x: 2500, y: -10 },
    ],
    { width: 1920, height: 1080 },
  ),
  [
    [0.25, 0.5],
    [1, 0],
  ],
)
