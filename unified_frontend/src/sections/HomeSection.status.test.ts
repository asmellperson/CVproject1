import { getServiceStatusText } from './HomeSection.status'

function assertEqual(actual: unknown, expected: unknown) {
  if (actual !== expected) {
    throw new Error(`expected ${expected}, got ${actual}`)
  }
}

assertEqual(
  getServiceStatusText({
    online: true,
    running: false,
    hasError: true,
    cameraCount: 2,
  }),
  '服务在线，状态获取异常',
)

assertEqual(
  getServiceStatusText({
    online: true,
    running: false,
    hasError: false,
    cameraCount: 2,
  }),
  '已连接，未开始检测',
)

