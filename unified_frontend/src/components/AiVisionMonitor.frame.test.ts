import {
  buildAiVisionPreviewFrameUrl,
  readFrameCoordinateSize,
  scheduleFrameRequestAbort,
} from './AiVisionMonitor.frame'

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
