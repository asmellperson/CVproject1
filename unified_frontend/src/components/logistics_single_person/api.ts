// 文件说明：实现接口访问的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { apiDelete, apiGet, apiPost, apiPut, apiUrl } from '@/lib/api'
import type {
  CreateLogisticsChannelPayload,
  LogisticsCameraConfigPayload,
  LogisticsCameraConfigResponse,
  LogisticsChannelAlarmListResponse,
  LogisticsChannelConfigPayload,
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
  /**
   * 功能：实现 `feature` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  feature: (feature: LogisticsFeatureName) => ['logistics-channels', feature] as const,
  /**
   * 功能：实现 `detail` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
   *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  detail: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId] as const,
  /**
   * 功能：实现 `status` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
   *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  status: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId, 'status'] as const,
  /**
   * 功能：实现 `alarms` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
   *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  alarms: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId, 'alarms'] as const,
  /**
   * 功能：实现 `statistics` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
   *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：`AiVision/integrations/guard_room/tests/test_site_api.py` 的
   *         `test_site_api_routes_expose_runtime_controls_and_read_models` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  statistics: (feature: LogisticsFeatureName, channelId: number) =>
    ['logistics-channels', feature, channelId, 'statistics'] as const,
}

/**
 * 功能：实现 `invalidateLogisticsChannelQueries` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId?`（number）：`channelId` 对应业务对象的唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/api.ts` 的 `invalidateAfter` 调用本符号
 *   - 内部调用：`dispatchEvent`、`CustomEvent`、`LogisticsChannelQueryInvalidation`。
 * 副作用/注意事项：会读取或修改浏览器全局对象/DOM 状态。
 */
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

/**
 * 功能：实现 `logisticsChannelPath` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId?`（number）：`channelId` 对应业务对象的唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/api.ts` 的 `memberCameraConfigPath`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/api.ts` 的 `listLogisticsChannels`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/api.ts` 的 `getLogisticsChannel`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/api.ts` 的 `createLogisticsChannel` 调用本符号；另有 12 处静态调用
 *   - 内部调用：`encodeURIComponent`、`String`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const logisticsChannelPath = (feature: LogisticsFeatureName, channelId?: number) => {
  const featurePath = `/v2/logistics-channels/${encodeURIComponent(feature)}`
  return channelId === undefined
    ? featurePath
    : `${featurePath}/${encodeURIComponent(String(channelId))}`
}

/**
 * 功能：实现 `memberCameraConfigPath` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `cameraId`（number）：摄像头唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/api.ts` 的 `getLogisticsCameraConfig`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/api.ts` 的 `updateLogisticsCameraConfig` 调用本符号
 *   - 内部调用：`logisticsChannelPath`、`encodeURIComponent`、`String`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const memberCameraConfigPath = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
) => `${logisticsChannelPath(feature, channelId)}/cameras/${encodeURIComponent(String(cameraId))}/config`

/**
 * 功能：实现 `invalidateAfter` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `request`（Promise<T>）：当前 HTTP 请求及上下文
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId?`（number）：`channelId` 对应业务对象的唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/api.ts` 的 `createLogisticsChannel`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/api.ts` 的 `updateLogisticsChannel`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/api.ts` 的 `updateLogisticsChannelConfig`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/api.ts` 的 `deleteLogisticsChannel` 调用本符号；另有 6 处静态调用
 *   - 内部调用：`then`、`invalidateLogisticsChannelQueries`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：读取或查询 `listLogisticsChannels` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannels` 调用本符号
 *   - 内部调用：`apiGet`、`logisticsChannelPath`、`LogisticsChannelListResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const listLogisticsChannels = (feature: LogisticsFeatureName, init?: RequestInit) =>
  apiGet<LogisticsChannelListResponse>(logisticsChannelPath(feature), init)

/**
 * 功能：读取或查询 `getLogisticsChannel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannels`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的
 *         `LogisticsChannelConfigView` 调用本符号
 *   - 内部调用：`apiGet`、`logisticsChannelPath`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getLogisticsChannel = (
  feature: LogisticsFeatureName,
  channelId: number,
  init?: RequestInit,
) => apiGet<LogisticsChannelDetail>(logisticsChannelPath(feature, channelId), init)

/**
 * 功能：创建或构建 `createLogisticsChannel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `payload`（CreateLogisticsChannelPayload）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiPost`、`logisticsChannelPath`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const createLogisticsChannel = (
  feature: LogisticsFeatureName,
  payload: CreateLogisticsChannelPayload,
) => invalidateAfter(
  apiPost<LogisticsChannelDetail>(logisticsChannelPath(feature), payload),
  feature,
)

/**
 * 功能：更新或保存 `updateLogisticsChannel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `payload`（UpdateLogisticsChannelPayload）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelRuntimeControl.tsx` 的
 *         `LogisticsChannelRuntimeControl`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的
 *         `LogisticsChannelConfigView` 调用本符号
 *   - 内部调用：`invalidateAfter`、`apiPut`、`logisticsChannelPath`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const updateLogisticsChannel = (
  feature: LogisticsFeatureName,
  channelId: number,
  payload: UpdateLogisticsChannelPayload,
) => invalidateAfter(
  apiPut<LogisticsChannelDetail>(logisticsChannelPath(feature, channelId), payload),
  feature,
  channelId,
)

/**
 * 功能：更新或保存 `updateLogisticsChannelConfig` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `payload`（LogisticsChannelConfigPayload）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`invalidateAfter`、`apiPut`、`logisticsChannelPath`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const updateLogisticsChannelConfig = (
  feature: LogisticsFeatureName,
  channelId: number,
  payload: LogisticsChannelConfigPayload,
) => invalidateAfter(
  apiPut<LogisticsChannelDetail>(`${logisticsChannelPath(feature, channelId)}/config`, payload),
  feature,
  channelId,
)

/**
 * 功能：删除或清理 `deleteLogisticsChannel` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiDelete`、`logisticsChannelPath`、`LogisticsChannelOkResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const deleteLogisticsChannel = (feature: LogisticsFeatureName, channelId: number) =>
  invalidateAfter(
    apiDelete<LogisticsChannelOkResponse>(logisticsChannelPath(feature, channelId)),
    feature,
  )

/**
 * 功能：创建或构建 `addLogisticsChannelCamera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `payload`（LogisticsChannelMemberPayload）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiPost`、`logisticsChannelPath`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const addLogisticsChannelCamera = (
  feature: LogisticsFeatureName,
  channelId: number,
  payload: LogisticsChannelMemberPayload,
) => invalidateAfter(
  apiPost<LogisticsChannelDetail>(`${logisticsChannelPath(feature, channelId)}/cameras`, payload),
  feature,
  channelId,
)

/**
 * 功能：实现 `moveLogisticsChannelCamera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `cameraId`（number）：摄像头唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiPut`、`logisticsChannelPath`、`encodeURIComponent`、`String`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：实现 `reorderLogisticsChannelCameras` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `cameraIds`（number[]）：`cameraIds` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiPut`、`logisticsChannelPath`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：删除或清理 `removeLogisticsChannelCamera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `cameraId`（number）：摄像头唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiDelete`、`logisticsChannelPath`、`encodeURIComponent`、`String`、`LogisticsChannelOkResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：更新或保存 `setLogisticsChannelCameraEnabled` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `cameraId`（number）：摄像头唯一标识
 *   - `enabled`（boolean）：是否启用相应能力
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiPut`、`logisticsChannelPath`、`encodeURIComponent`、`String`、`LogisticsChannelDetail`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：读取或查询 `getLogisticsChannelStatus` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus` 调用本符号
 *   - 内部调用：`apiGet`、`logisticsChannelPath`、`LogisticsChannelRuntimeStatus`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getLogisticsChannelStatus = (
  feature: LogisticsFeatureName,
  channelId: number,
  init?: RequestInit,
) => apiGet<LogisticsChannelRuntimeStatus>(
  `${logisticsChannelPath(feature, channelId)}/status`,
  init,
)

/**
 * 功能：读取或查询 `getLogisticsChannelAlarms` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `limit`（未显式标注）：返回或处理的最大记录数；声明包含默认值 `200`
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus` 调用本符号
 *   - 内部调用：`apiGet`、`logisticsChannelPath`、`encodeURIComponent`、`String`、`LogisticsChannelAlarmListResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getLogisticsChannelAlarms = (
  feature: LogisticsFeatureName,
  channelId: number,
  limit = 200,
  init?: RequestInit,
) => apiGet<LogisticsChannelAlarmListResponse>(
  `${logisticsChannelPath(feature, channelId)}/alarms?limit=${encodeURIComponent(String(limit))}`,
  init,
)

/**
 * 功能：读取或查询 `getLogisticsChannelStatistics` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `days`（未显式标注）：`days` 对应的业务输入值；声明包含默认值 `7`
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus` 调用本符号
 *   - 内部调用：`apiGet`、`logisticsChannelPath`、`encodeURIComponent`、`String`、`LogisticsChannelStatistics`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：实现 `logisticsChannelFrameUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `options`（LogisticsChannelFrameOptions）：`options` 对应的业务输入值；声明包含默认值 `{}`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/api.ts` 的 `fetchLogisticsChannelFrame` 调用本符号
 *   - 内部调用：`URLSearchParams`、`set`、`String`、`toString`、`apiUrl`、`logisticsChannelPath`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
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

/**
 * 功能：读取或查询 `fetchLogisticsChannelFrame` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `signal?`（AbortSignal）：用于取消异步请求的 AbortSignal
 *   - `options`（LogisticsChannelFrameOptions）：`options` 对应的业务输入值；声明包含默认值 `{}`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus` 调用本符号
 *   - 内部调用：`fetch`、`logisticsChannelFrameUrl`、`dispatchEvent`、`Event`、`Error`、`blob`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
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

/**
 * 功能：实现 `replaceLogisticsChannelFrameObjectUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `blob`（Blob）：`blob` 对应的业务输入值
 *   - `previousUrl?`（string | null）：`previousUrl` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus` 调用本符号
 *   - 内部调用：`revokeObjectURL`、`createObjectURL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function replaceLogisticsChannelFrameObjectUrl(blob: Blob, previousUrl?: string | null) {
  if (previousUrl) URL.revokeObjectURL(previousUrl)
  return URL.createObjectURL(blob)
}

/**
 * 功能：实现 `revokeLogisticsChannelFrameObjectUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `objectUrl?`（string | null）：`objectUrl` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus` 调用本符号
 *   - 内部调用：`revokeObjectURL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function revokeLogisticsChannelFrameObjectUrl(objectUrl?: string | null) {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
}

/**
 * 功能：读取或查询 `getLogisticsCameraConfig` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `cameraId`（number）：摄像头唯一标识
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`apiGet`、`memberCameraConfigPath`、`LogisticsCameraConfigResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getLogisticsCameraConfig = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
  init?: RequestInit,
) => apiGet<LogisticsCameraConfigResponse>(
  memberCameraConfigPath(feature, channelId, cameraId),
  init,
)

/**
 * 功能：更新或保存 `updateLogisticsCameraConfig` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（LogisticsFeatureName）：`feature` 对应的业务输入值
 *   - `channelId`（number）：`channelId` 对应业务对象的唯一标识
 *   - `cameraId`（number）：摄像头唯一标识
 *   - `payload`（LogisticsCameraConfigPayload）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/LogisticsChannelConfigView.tsx` 的 `LogisticsChannelConfigView`
 *         调用本符号
 *   - 内部调用：`invalidateAfter`、`apiPut`、`memberCameraConfigPath`、`LogisticsCameraConfigResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const updateLogisticsCameraConfig = (
  feature: LogisticsFeatureName,
  channelId: number,
  cameraId: number,
  payload: LogisticsCameraConfigPayload,
) => invalidateAfter(
  apiPut<LogisticsCameraConfigResponse>(memberCameraConfigPath(feature, channelId, cameraId), payload),
  feature,
  channelId,
)
