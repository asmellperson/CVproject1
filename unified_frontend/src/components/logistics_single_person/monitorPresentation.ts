// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type {
  LogisticsChannelReason,
  LogisticsChannelRuntimeStatus,
} from './types'

export type LogisticsChannelStatusEvent = {
  id: string
  reason: Exclude<LogisticsChannelReason, 'unknown' | 'unconfigured' | 'inactive'>
  occurredAt: string
}

/**
 * 功能：实现 `appendLogisticsStatusEvent` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `events`（LogisticsChannelStatusEvent[]）：`events` 对应的业务输入值
 *   - `previousReason`（LogisticsChannelReason | null）：`previousReason` 对应的业务输入值
 *   - `status`（Pick<LogisticsChannelRuntimeStatus, 'reason'>）：当前或目标状态值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus` 调用本符号
 *   - 内部调用：`Date`、`toISOString`、`slice`、`LogisticsChannelRuntimeStatus`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function appendLogisticsStatusEvent(
  events: LogisticsChannelStatusEvent[],
  previousReason: LogisticsChannelReason | null,
  status: Pick<LogisticsChannelRuntimeStatus, 'reason'>,
) {
  if (
    previousReason === null
    || status.reason === previousReason
    || status.reason === 'unknown'
    || status.reason === 'unconfigured'
    || status.reason === 'inactive'
  ) return events

  const occurredAt = new Date().toISOString()
  return [
    { id: `${occurredAt}-${status.reason}`, reason: status.reason, occurredAt },
    ...events,
  ].slice(0, 8)
}

export type LogisticsFramePresentation = {
  state: 'live' | 'stale' | 'error' | 'waiting'
  label: string
  showFrame: boolean
  errorMessage: string | null
}

/**
 * 功能：读取或查询 `getLogisticsFramePresentation` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `frameUrl`（string | null）：`frameUrl` 对应的业务输入值
 *   - `frameError`（string | null）：`frameError` 对应的业务输入值
 * 返回：LogisticsFramePresentation；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelMonitorView.tsx` 的 `LogisticsChannelMonitorView`
 *         调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function getLogisticsFramePresentation(
  frameUrl: string | null,
  frameError: string | null,
): LogisticsFramePresentation {
  if (frameError && frameUrl) {
    return {
      state: 'stale',
      label: '画面异常 / 最近帧',
      showFrame: true,
      errorMessage: frameError,
    }
  }
  if (frameError) {
    return {
      state: 'error',
      label: '画面异常',
      showFrame: false,
      errorMessage: frameError,
    }
  }
  if (frameUrl) {
    return {
      state: 'live',
      label: '画面在线',
      showFrame: true,
      errorMessage: null,
    }
  }
  return {
    state: 'waiting',
    label: '等待画面',
    showFrame: false,
    errorMessage: null,
  }
}
