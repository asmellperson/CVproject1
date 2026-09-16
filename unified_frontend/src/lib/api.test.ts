import { guardRoomSiteCameraFrameUrl, guardRoomSitesPath } from './api'

function assertEndsWith(actual: string, expected: string) {
  if (!actual.endsWith(expected)) {
    throw new Error(`expected ${actual} to end with ${expected}`)
  }
}

assertEndsWith(
  guardRoomSiteCameraFrameUrl(12, 'cam2', 123, 'fulida_company'),
  '/api/sites/12/cameras/cam2/frame.jpg?t=123&department=fulida_company',
)

assertEndsWith(
  guardRoomSiteCameraFrameUrl(12, 'cam 2', undefined, 'research_institute'),
  '/api/sites/12/cameras/cam%202/frame.jpg?department=research_institute',
)

if (guardRoomSitesPath('electronics_electrician') !== '/sites?department=electronics_electrician') {
  throw new Error('expected electronics department site path to include department query')
}
