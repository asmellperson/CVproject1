import type {
  getLogisticsCameraRoi,
  updateLogisticsCameraRoi,
} from './api'
import type {
  LogisticsCameraRoiPayload,
  LogisticsCameraRoiResponse,
  LogisticsFeatureName,
} from './types'

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? true
    : false

type AssertTrue<Value extends true> = Value

export type LogisticsCameraRoiApiAssertions = [
  AssertTrue<Equal<keyof LogisticsCameraRoiPayload, 'roi_pos'>>,
  AssertTrue<Equal<keyof LogisticsCameraRoiResponse, 'camera' | 'roi_pos'>>,
  AssertTrue<Equal<
    Parameters<typeof getLogisticsCameraRoi>,
    [feature: LogisticsFeatureName, channelId: number, cameraId: number, init?: RequestInit]
  >>,
  AssertTrue<Equal<
    ReturnType<typeof getLogisticsCameraRoi>,
    Promise<LogisticsCameraRoiResponse>
  >>,
  AssertTrue<Equal<
    Parameters<typeof updateLogisticsCameraRoi>,
    [feature: LogisticsFeatureName, channelId: number, cameraId: number, payload: LogisticsCameraRoiPayload]
  >>,
]
