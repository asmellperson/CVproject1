import type {
  getLogisticsCameraRoi,
  updateLogisticsCameraRoi,
  updateLogisticsChannel,
} from './api'
import type {
  LogisticsCameraRoiPayload,
  LogisticsCameraRoiResponse,
  LogisticsChannelAlarmConfig,
  LogisticsChannelConfig,
  LogisticsChannelConfigPatch,
  LogisticsChannelDetectionConfig,
  LogisticsChannelDetail,
  LogisticsFeatureName,
  UpdateLogisticsChannelPayload,
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

export type LogisticsChannelPatchApiAssertions = [
  AssertTrue<Equal<LogisticsChannelConfigPatch, Partial<LogisticsChannelConfig>>>,
  AssertTrue<Equal<NonNullable<LogisticsChannelConfigPatch['alarm']>, LogisticsChannelAlarmConfig>>,
  AssertTrue<Equal<NonNullable<UpdateLogisticsChannelPayload['config']>, LogisticsChannelConfigPatch>>,
  AssertTrue<Equal<keyof LogisticsChannelDetectionConfig,
    | 'detection_start' | 'detection_end' | 'confidence_threshold'
    | 'model_iou_threshold' | 'min_box_area' | 'min_aspect_ratio' | 'max_aspect_ratio'
    | 'cap_interval' | 'empty_grace_seconds' | 'multi_grace_seconds'
  >>,
  AssertTrue<Equal<
    Parameters<typeof updateLogisticsChannel>,
    [feature: LogisticsFeatureName, channelId: number, payload: UpdateLogisticsChannelPayload]
  >>,
  AssertTrue<Equal<ReturnType<typeof updateLogisticsChannel>, Promise<LogisticsChannelDetail>>>,
]
