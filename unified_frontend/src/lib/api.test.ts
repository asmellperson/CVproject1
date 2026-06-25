import { guardRoomSiteCameraFrameUrl } from './api'

function assertEndsWith(actual: string, expected: string) {
  if (!actual.endsWith(expected)) {
    throw new Error(`expected ${actual} to end with ${expected}`)
  }
}

assertEndsWith(
  guardRoomSiteCameraFrameUrl(12, 'cam2', 123),
  '/api/sites/12/cameras/cam2/frame.jpg?t=123',
)

assertEndsWith(
  guardRoomSiteCameraFrameUrl(12, 'cam 2'),
  '/api/sites/12/cameras/cam%202/frame.jpg',
)
