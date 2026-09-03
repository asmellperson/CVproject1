// 文件说明：包含监控展示、视频帧的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import {
  buildAiVisionPreviewFrameUrl,
  readFrameCoordinateSize,
  scheduleFrameRequestAbort,
} from './AiVisionMonitor.frame'

/**
 * 功能：实现 `assertEqual` 对应的监控展示、视频帧逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（unknown）：`actual` 对应的业务输入值
 *   - `expected`（unknown）：`expected` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Error`、`String`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertEqual(actual: unknown, expected: unknown) {
  if (actual !== expected) {
    throw new Error(`expected ${String(expected)}, got ${String(actual)}`)
  }
}

assertEqual(
  buildAiVisionPreviewFrameUrl('logistics camera', 'detect_logistics_single_person', 123),
  '/api/cameras/logistics%20camera/frame.jpg?feature=detect_logistics_single_person&t=123&max_width=960&quality=72',
)

const frameHeaders = new Headers({
  'x-frame-width': '960',
  'x-frame-height': '540',
  'x-frame-coordinate-width': '2560',
  'x-frame-coordinate-height': '1440',
})
assertEqual(
  JSON.stringify(readFrameCoordinateSize(frameHeaders)),
  JSON.stringify({ width: 2560, height: 1440 }),
)
assertEqual(
  JSON.stringify(readFrameCoordinateSize(new Headers({
    'x-frame-width': '1920',
    'x-frame-height': '1080',
  }))),
  JSON.stringify({ width: 1920, height: 1080 }),
)
assertEqual(readFrameCoordinateSize(new Headers()), null)

const controller = new AbortController()
let scheduledDelay = 0
let scheduledCallback: (() => void) | undefined
scheduleFrameRequestAbort(controller, 5000, (callback, delay) => {
  scheduledCallback = callback
  scheduledDelay = delay
  return 1 as unknown as ReturnType<typeof setTimeout>
})

assertEqual(scheduledDelay, 5000)
assertEqual(controller.signal.aborted, false)
scheduledCallback?.()
assertEqual(controller.signal.aborted, true)
