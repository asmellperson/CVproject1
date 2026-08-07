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
    [feature: LogisticsFeatureName, shmName: string, init?: RequestInit]
  >>,
  AssertTrue<Equal<
    ReturnType<typeof getLogisticsCameraConfig>,
    Promise<LogisticsCameraConfigResponse>
  >>,
  AssertTrue<Equal<
    Parameters<typeof updateLogisticsCameraConfig>,
    [feature: LogisticsFeatureName, shmName: string, payload: LogisticsCameraConfigPayload]
  >>,
]
