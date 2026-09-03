// 文件说明：实现监控展示、视频帧的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { aiVisionFrameUrl } from '../lib/aivision'

export const PREVIEW_MAX_WIDTH = 960
export const PREVIEW_QUALITY = 72
export const FRAME_REQUEST_TIMEOUT_MS = 5000

export type FrameCoordinateSize = {
  width: number
  height: number
}

type ScheduleTimeout = (callback: () => void, delay: number) => ReturnType<typeof setTimeout>

/**
 * 功能：创建或构建 `buildAiVisionPreviewFrameUrl` 对应的监控展示、视频帧逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `feature`（string）：`feature` 对应的业务输入值
 *   - `nonce`（number）：`nonce` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`aiVisionFrameUrl`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function buildAiVisionPreviewFrameUrl(cameraKey: string, feature: string, nonce: number) {
  return aiVisionFrameUrl(cameraKey, feature, nonce, {
    maxWidth: PREVIEW_MAX_WIDTH,
    quality: PREVIEW_QUALITY,
  })
}

/**
 * 功能：读取或查询 `readFrameCoordinateSize` 对应的监控展示、视频帧逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `headers`（Pick<Headers, 'get'>）：`headers` 对应的业务输入值
 * 返回：FrameCoordinateSize | null；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`Number`、`get`、`isFinite`、`Headers`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function readFrameCoordinateSize(headers: Pick<Headers, 'get'>): FrameCoordinateSize | null {
  const width = Number(
    headers.get('x-frame-coordinate-width') ?? headers.get('x-frame-width'),
  )
  const height = Number(
    headers.get('x-frame-coordinate-height') ?? headers.get('x-frame-height'),
  )
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
    return null
  }
  return { width, height }
}

/**
 * 功能：实现 `scheduleFrameRequestAbort` 对应的监控展示、视频帧逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `controller`（AbortController）：`controller` 对应的业务输入值
 *   - `timeoutMs`（未显式标注）：`timeoutMs` 对应的时间间隔或时长；声明包含默认值 `FRAME_REQUEST_TIMEOUT_MS`
 *   - `schedule`（ScheduleTimeout）：`schedule` 对应的业务输入值；声明包含默认值 `setTimeout`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`schedule`、`abort`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function scheduleFrameRequestAbort(
  controller: AbortController,
  timeoutMs = FRAME_REQUEST_TIMEOUT_MS,
  schedule: ScheduleTimeout = setTimeout,
) {
  return schedule(() => controller.abort(), timeoutMs)
}
