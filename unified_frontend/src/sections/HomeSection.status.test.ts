import { getRecognitionAbilityText, getServiceStatusText } from './HomeSection.status'

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

assertEqual(getRecognitionAbilityText({ modelLoaded: true, running: true }), '已启用')

assertEqual(getRecognitionAbilityText({ modelLoaded: true, running: false }), '已就绪')

assertEqual(getRecognitionAbilityText({ modelLoaded: false, running: true }), '待确认')
