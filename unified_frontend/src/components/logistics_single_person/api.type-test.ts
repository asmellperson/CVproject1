// 文件说明：实现接口访问的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type {
  getLogisticsCameraConfig,
  updateLogisticsCameraConfig,
} from './api'
import type {
  LogisticsCameraConfigPayload,
  LogisticsCameraConfigResponse,
  LogisticsFeatureName,
} from './types'

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? true
    : false

type AssertTrue<Value extends true> = Value

export type LogisticsCameraConfigApiAssertions = [
  AssertTrue<Equal<
    Parameters<typeof getLogisticsCameraConfig>,
    [feature: LogisticsFeatureName, channelId: number, cameraId: number, init?: RequestInit]
  >>,
  AssertTrue<Equal<
    ReturnType<typeof getLogisticsCameraConfig>,
    Promise<LogisticsCameraConfigResponse>
  >>,
  AssertTrue<Equal<
    Parameters<typeof updateLogisticsCameraConfig>,
    [feature: LogisticsFeatureName, channelId: number, cameraId: number, payload: LogisticsCameraConfigPayload]
  >>,
]
