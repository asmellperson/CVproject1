import type { DepartmentId } from '@/auth/permissions'
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUrl } from '@/lib/api'
import type {
  CreateLogisticsChannelPayload,
  LogisticsCameraRoiPayload,
  LogisticsCameraRoiResponse,
  LogisticsCameraInventoryResponse,
  LogisticsChannelAlarmListResponse,
  LogisticsChannelDetail,
  LogisticsChannelListResponse,
  LogisticsChannelMemberPayload,
  LogisticsChannelOkResponse,
  LogisticsChannelRuntimeStatus,
  LogisticsChannelStatistics,
  LogisticsFeatureName,
  UpdateLogisticsChannelPayload,
} from './types'

export const LOGISTICS_CHANNEL_QUERY_INVALIDATED = 'logistics-channel-query-invalidated'

export type LogisticsChannelQueryInvalidation = {
  feature: LogisticsFeatureName
  channelId?: number
}

export const logisticsChannelQueryKeys = {
  all: ['logistics-channels'] as const,
  feature: (feature: LogisticsFeatureName) => ['logistics-channels', feature] as const,
  list: (feature: LogisticsFeatureName, department: DepartmentId) =>
    ['logistics-channels', feature, department] as const,
  detail: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId] as const,
  status: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId, 'status'] as const,
  alarms: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId, 'alarms'] as const,
  statistics: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId, 'statistics'] as const,
}

export function invalidateLogisticsChannelQueries(
  feature: LogisticsFeatureName,
  channelId?: number,
) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent<LogisticsChannelQueryInvalidation>(
    LOGISTICS_CHANNEL_QUERY_INVALIDATED,
    { detail: { feature, channelId } },
  ))
}

const logisticsChannelPath = (feature: LogisticsFeatureName, channelId?: number) => {
  const featurePath = `/logistics-channels/${encodeURIComponent(feature)}`
  return channelId === undefined
    ? featurePath
    : `${featurePath}/${encodeURIComponent(String(channelId))}`
}

export const getLogisticsCameraInventory = (department?: DepartmentId) =>
  apiGet<LogisticsCameraInventoryResponse>(
    `/logistics-channels/inventory${department ? `?department=${encodeURIComponent(department)}` : ''}`,
  )

const memberCameraRoiPath = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
) => `${logisticsChannelPath(feature, channelId)}/cameras/${encodeURIComponent(String(cameraId))}/roi`

function invalidateAfter<T>(
  request: Promise<T>,
  feature: LogisticsFeatureName,
  channelId?: number,
) {
  return request.then((result) => {
    invalidateLogisticsChannelQueries(feature, channelId)
    return result
  })
}

export const listLogisticsChannels = (
  feature: LogisticsFeatureName,
  department: DepartmentId,
  init?: RequestInit,
) => apiGet<LogisticsChannelListResponse>(
  `${logisticsChannelPath(feature)}?department=${encodeURIComponent(department)}`, init,
)

export const getLogisticsChannel = (
  feature: LogisticsFeatureName,
  channelId: number,
  init?: RequestInit,
) => apiGet<LogisticsChannelDetail>(logisticsChannelPath(feature, channelId), init)

export const createLogisticsChannel = (
  feature: LogisticsFeatureName,
  payload: CreateLogisticsChannelPayload,
) => invalidateAfter(
  apiPost<LogisticsChannelDetail>(logisticsChannelPath(feature), payload),
  feature,
)

export const updateLogisticsChannel = (
  feature: LogisticsFeatureName,
  channelId: number,
  payload: UpdateLogisticsChannelPayload,
) => invalidateAfter(
  apiPatch<LogisticsChannelDetail>(logisticsChannelPath(feature, channelId), payload),
  feature,
  channelId,
)

export const deleteLogisticsChannel = (feature: LogisticsFeatureName, channelId: number) =>
  invalidateAfter(
    apiDelete<LogisticsChannelOkResponse>(logisticsChannelPath(feature, channelId)),
    feature,
  )

export const addLogisticsChannelCamera = (
  feature: LogisticsFeatureName,
  channelId: number,
  payload: LogisticsChannelMemberPayload,
) => invalidateAfter(
  apiPost<LogisticsChannelDetail>(`${logisticsChannelPath(feature, channelId)}/cameras`, payload),
  feature,
  channelId,
)

export const moveLogisticsChannelCamera = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
) => invalidateAfter(
  apiPut<LogisticsChannelDetail>(
    `${logisticsChannelPath(feature, channelId)}/cameras/${encodeURIComponent(String(cameraId))}`,
  ),
  feature,
)

export const reorderLogisticsChannelCameras = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraIds: number[],
) => invalidateAfter(
  apiPut<LogisticsChannelDetail>(`${logisticsChannelPath(feature, channelId)}/cameras/order`, {
    camera_ids: cameraIds,
  }),
  feature,
  channelId,
)

export const removeLogisticsChannelCamera = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
) => invalidateAfter(
  apiDelete<LogisticsChannelOkResponse>(
    `${logisticsChannelPath(feature, channelId)}/cameras/${encodeURIComponent(String(cameraId))}`,
  ),
  feature,
  channelId,
)

export const setLogisticsChannelCameraEnabled = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
  enabled: boolean,
) => invalidateAfter(
  apiPut<LogisticsChannelDetail>(
    `${logisticsChannelPath(feature, channelId)}/cameras/${encodeURIComponent(String(cameraId))}/enabled`,
    { enabled },
  ),
  feature,
  channelId,
)

export const getLogisticsChannelStatus = (
  feature: LogisticsFeatureName,
  channelId: number,
  init?: RequestInit,
) => apiGet<LogisticsChannelRuntimeStatus>(
  `${logisticsChannelPath(feature, channelId)}/status`,
  init,
)

export const getLogisticsChannelAlarms = (
  feature: LogisticsFeatureName,
  channelId: number,
  limit = 200,
  init?: RequestInit,
) => apiGet<LogisticsChannelAlarmListResponse>(
  `${logisticsChannelPath(feature, channelId)}/alarms?limit=${encodeURIComponent(String(limit))}`,
  init,
)

export const getLogisticsChannelStatistics = (
  feature: LogisticsFeatureName,
  channelId: number,
  days = 7,
  init?: RequestInit,
) => apiGet<LogisticsChannelStatistics>(
  `${logisticsChannelPath(feature, channelId)}/statistics?days=${encodeURIComponent(String(days))}`,
  init,
)

export type LogisticsChannelFrameOptions = {
  quality?: number
  maxWidth?: number
  maxHeight?: number
  nonce?: number
}

export function logisticsChannelFrameUrl(
  feature: LogisticsFeatureName,
  channelId: number,
  options: LogisticsChannelFrameOptions = {},
) {
  const query = new URLSearchParams()
  if (options.quality !== undefined) query.set('quality', String(options.quality))
  if (options.maxWidth !== undefined) query.set('max_width', String(options.maxWidth))
  if (options.maxHeight !== undefined) query.set('max_height', String(options.maxHeight))
  if (options.nonce !== undefined) query.set('t', String(options.nonce))
  const suffix = query.toString()
  return apiUrl(`${logisticsChannelPath(feature, channelId)}/frame.jpg${suffix ? `?${suffix}` : ''}`)
}

export async function fetchLogisticsChannelFrame(
  feature: LogisticsFeatureName,
  channelId: number,
  signal?: AbortSignal,
  options: LogisticsChannelFrameOptions = {},
) {
  const response = await fetch(logisticsChannelFrameUrl(feature, channelId, options), {
    credentials: 'include',
    cache: 'no-store',
    signal,
  })
  if (response.status === 401 && typeof window !== 'undefined') {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!response.ok) {
    throw new Error(`GET logistics channel frame failed: ${response.status} ${response.statusText}`)
  }
  return response.blob()
}

export function replaceLogisticsChannelFrameObjectUrl(blob: Blob, previousUrl?: string | null) {
  if (previousUrl) URL.revokeObjectURL(previousUrl)
  return URL.createObjectURL(blob)
}

export function revokeLogisticsChannelFrameObjectUrl(objectUrl?: string | null) {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
}

export const getLogisticsCameraRoi = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
  init?: RequestInit,
) => apiGet<LogisticsCameraRoiResponse>(
  memberCameraRoiPath(feature, channelId, cameraId),
  init,
)

export const updateLogisticsCameraRoi = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
  payload: LogisticsCameraRoiPayload,
) => invalidateAfter(
  apiPut<LogisticsCameraRoiResponse>(memberCameraRoiPath(feature, channelId, cameraId), payload),
  feature,
  channelId,
)
