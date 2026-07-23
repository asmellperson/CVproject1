import { buildAiVisionPreviewFrameUrl, scheduleFrameRequestAbort } from './AiVisionMonitor.frame'

function assertEqual(actual: unknown, expected: unknown) {
  if (actual !== expected) {
    throw new Error(`expected ${String(expected)}, got ${String(actual)}`)
  }
}

assertEqual(
  buildAiVisionPreviewFrameUrl('logistics camera', 'detect_logistics_single_person', 123),
  '/api/aivision/cameras/logistics%20camera/frame.jpg?feature=detect_logistics_single_person&t=123&max_width=960&quality=72',
)

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
