import type {
  getLogisticsCameraConfig,
  updateLogisticsCameraConfig,
} from './api'
import type {
  LogisticsCameraConfigPayload,
  LogisticsCameraConfigResponse,
  LogisticsCameraDetectionValue,
  LogisticsFeatureName,
} from './types'

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? true
    : false

type AssertTrue<Value extends true> = Value

export type LogisticsCameraConfigApiAssertions = [
  AssertTrue<Equal<keyof LogisticsCameraConfigPayload, 'enable' | 'value'>>,
  AssertTrue<Equal<keyof LogisticsCameraDetectionValue,
    'roi_pos' | 'IOU_THR' | 'MIN_BOX_AREA' | 'ASPECT_RATIO_RANGE' | 'cap_interval'>>,
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
