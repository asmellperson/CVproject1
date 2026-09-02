// 文件说明：实现接口访问相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type {
  AppConfigPayload,
  BackendStatus,
  ControlResponse,
  GuardRoomCamera,
  GuardRoomSite,
  StatisticsResponse,
} from '@/types'
import { notifyPlatformCamerasChanged } from '@/lib/camera-events'
import { notifyPlatformRuntimeChanged } from '@/lib/runtime-events'

/**
 * 功能：实现 `trimTrailingSlash` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `value`（string）：待转换、校验或写入的值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`replace`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, '')
}

/**
 * 功能：实现 `joinUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `base`（string）：`base` 对应的业务输入值
 *   - `path`（string）：目标路径
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `apiUrl` 调用本符号
 *   - 内部调用：`startsWith`、`trimTrailingSlash`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function joinUrl(base: string, path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return base ? `${trimTrailingSlash(base)}${normalizedPath}` : normalizedPath
}

/**
 * 功能：转换或规范化 `toWsBase` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `base`（string）：`base` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`startsWith`、`slice`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function toWsBase(base: string) {
  if (base.startsWith('https://')) return `wss://${base.slice('https://'.length)}`
  if (base.startsWith('http://')) return `ws://${base.slice('http://'.length)}`
  return base
}

const PUBLIC_ORIGIN = trimTrailingSlash((import.meta.env.VITE_PUBLIC_ORIGIN as string | undefined) || '')
const API_BASE = trimTrailingSlash((import.meta.env.VITE_API_BASE as string | undefined) || PUBLIC_ORIGIN)
const WS_BASE = trimTrailingSlash((import.meta.env.VITE_WS_BASE as string | undefined) || toWsBase(API_BASE))

export const API_PREFIX = joinUrl(API_BASE, '/api')
export const WS_PREFIX = joinUrl(WS_BASE, '/ws')

/**
 * 功能：实现 `apiUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`joinUrl`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const apiUrl = (path: string) => joinUrl(API_PREFIX, path)

/**
 * 功能：发送或分发 `notifyUnauthorized` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `response`（Response）：待读取或更新的 HTTP 响应
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `apiGet` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `apiPost`
 *         调用本符号；`unified_frontend/src/lib/api.ts` 的 `apiPut` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `apiDelete` 调用本符号
 *   - 内部调用：`dispatchEvent`、`Event`。
 * 副作用/注意事项：会读取或修改浏览器全局对象/DOM 状态。
 */
function notifyUnauthorized(response: Response) {
  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
}

/**
 * 功能：读取或查询 `apiGet` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：Promise<T>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `getStatus` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `getPlatformStatus`
 *         调用本符号；`unified_frontend/src/lib/api.ts` 的 `getStatistics` 调用本符号；`unified_frontend/src/lib/api.ts` 的
 *         `getGuardRoomStatistics` 调用本符号；另有 3 处静态调用
 *   - 内部调用：`fetch`、`notifyUnauthorized`、`Error`、`json`、`T`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'GET',
    credentials: 'include',
    headers: {
      ...(init?.headers || {}),
    },
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status} ${response.statusText}`)
  }

  return response.json() as Promise<T>
}

/**
 * 功能：实现 `apiPost` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `body?`（unknown）：`body` 对应的业务输入值
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：Promise<T>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `saveConfig` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `startRuntime`
 *         调用本符号；`unified_frontend/src/lib/api.ts` 的 `stopRuntime` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `restartRuntime`
 *         调用本符号；另有 2 处静态调用
 *   - 内部调用：`fetch`、`stringify`、`notifyUnauthorized`、`text`、`Error`、`json`、`T`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function apiPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`POST ${path} failed: ${response.status} ${response.statusText} ${detail}`)
  }

  return response.json() as Promise<T>
}

/**
 * 功能：更新或保存 `apiPut` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `body?`（unknown）：`body` 对应的业务输入值
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：Promise<T>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `updateGuardRoomSite` 调用本符号
 *   - 内部调用：`fetch`、`stringify`、`notifyUnauthorized`、`text`、`Error`、`json`、`T`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function apiPut<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'PUT',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`PUT ${path} failed: ${response.status} ${response.statusText} ${detail}`)
  }

  return response.json() as Promise<T>
}

/**
 * 功能：删除或清理 `apiDelete` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：Promise<T>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `deleteGuardRoomSite` 调用本符号
 *   - 内部调用：`fetch`、`notifyUnauthorized`、`text`、`Error`、`json`、`T`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function apiDelete<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'DELETE',
    credentials: 'include',
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`DELETE ${path} failed: ${response.status} ${response.statusText} ${detail}`)
  }

  return response.json() as Promise<T>
}

/**
 * 功能：读取或查询 `getStatus` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiGet`、`BackendStatus`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getStatus = () => apiGet<BackendStatus>('/status')

export type PlatformServiceStatus = {
  name: string
  url: string
  online: boolean
  running?: boolean
  latency_ms?: number | null
  error?: string | null
  camera_count?: number
  enabled_camera_count?: number
  online_camera_count?: number
  offline_camera_count?: number
  last_frame_age_sec?: number | null
  fps?: number | null
  frame_count?: number | null
  running_cameras?: string[]
  running_models?: string[]
  running_consumers?: string[]
  feature_status?: Record<string, {
    camera_count?: number
    enabled_camera_count?: number
    online_camera_count?: number
    offline_camera_count?: number
  }>
  model_status?: {
    loaded?: boolean
    running_count?: number
    pose_enabled?: boolean
    vlm_ok?: boolean
  }
  worker_status?: Record<string, unknown>
  stats?: Record<string, unknown>
}

export type PlatformStatus = {
  ok: boolean
  level: 'healthy' | 'degraded' | 'down' | string
  generated_at: number
  summary: {
    service_total: number
    service_online: number
    service_running: number
    camera_total: number
    camera_online: number
    camera_offline: number
    model_loaded: Record<string, boolean>
  }
  services: {
    guard_room: PlatformServiceStatus
    aivision: PlatformServiceStatus
    security_vlm: PlatformServiceStatus
  }
}

export const PLATFORM_STATUS_POLL_INTERVAL_MS = 30_000
export const PLATFORM_STATUS_REQUEST_TIMEOUT_MS = 8_000
/**
 * 功能：读取或查询 `getPlatformStatus` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/hooks/use-platform-status.ts` 的 `usePlatformStatus` 调用本符号
 *   - 内部调用：`apiGet`、`PlatformStatus`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getPlatformStatus = (init?: RequestInit) => apiGet<PlatformStatus>('/platform/status', init)

// api.ts
export type AlarmEvent = {
  id: string
  source?: 'aivision' | 'guard_room' | 'security_vlm'
  source_id?: string
  site_id?: number
  site_name?: string
  event_type: 'absent' | 'phone_use' | 'prone_sleep' | string
  event_label?: string
  violation_type?: number
  camera_no?: string
  camera_name?: string
  reason: string
  confidence: number
  created_at?: string
  frame_index?: number
  track_id?: number | null
  image_path?: string
  image_url?: string
  video_path?: string | null
  video_url?: string | null
  video_status?: 'pending' | 'ready' | 'failed'
  disposition_status?: AlarmDispositionStatus
  disposition_note?: string
  disposition_updated_at?: string
  disposition_updated_by?: AlarmDispositionActor | null
}

type AlarmsResponse = {
  items?: AlarmEvent[]
}

export type AlarmDispositionStatus = 'pending' | 'acknowledged' | 'resolved' | 'false_positive'

export type AlarmDispositionActor = {
  employee_id: string
  name: string
}

export type AlarmDisposition = {
  alarm_id: string
  status: AlarmDispositionStatus
  note: string
  updated_at: string
  updated_by?: AlarmDispositionActor | null
}

type AlarmDispositionsResponse = {
  items?: AlarmDisposition[]
}

/**
 * 功能：读取或查询 `getAlarmDispositions` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：Promise<AlarmDisposition[]>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`async`、`apiGet`、`AlarmDisposition`、`AlarmDispositionsResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getAlarmDispositions = async (): Promise<AlarmDisposition[]> => {
  const data = await apiGet<AlarmDispositionsResponse>('/alarm-dispositions')
  return data.items || []
}

/**
 * 功能：更新或保存 `updateAlarmDisposition` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarmId`（string）：`alarmId` 对应业务对象的唯一标识
 *   - `status`（AlarmDispositionStatus）：当前或目标状态值
 *   - `note`（未显式标注）：`note` 对应的业务输入值；声明包含默认值 `''`
 * 返回：Promise<AlarmDisposition>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AlarmsSection.tsx` 的 `AlarmsSection` 调用本符号
 *   - 内部调用：`async`、`apiPost`、`AlarmDisposition`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const updateAlarmDisposition = async (
  alarmId: string,
  status: AlarmDispositionStatus,
  note = '',
): Promise<AlarmDisposition> => {
  const data = await apiPost<{ success: boolean; item: AlarmDisposition }>('/alarm-dispositions', {
    alarm_id: alarmId,
    status,
    note,
  })
  return data.item
}

/**
 * 功能：读取或查询 `eventTypesQuery` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `eventTypes?`（readonly string[] | null）：`eventTypes` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `getAlarms` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `getStatistics` 调用本符号
 *   - 内部调用：`encodeURIComponent`、`join`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function eventTypesQuery(eventTypes?: readonly string[] | null) {
  return eventTypes && eventTypes.length > 0 ? `&event_types=${encodeURIComponent(eventTypes.join(','))}` : ''
}

/**
 * 功能：读取或查询 `queryString` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `params`（Record<string, string | number | undefined | null>）：`params` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `withQuery` 调用本符号
 *   - 内部调用：`URLSearchParams`、`entries`、`forEach`、`String`、`trim`、`set`、`toString`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function queryString(params: Record<string, string | number | undefined | null>) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) {
      query.set(key, String(value))
    }
  })
  const text = query.toString()
  return text ? `?${text}` : ''
}

/**
 * 功能：读取或查询 `withQuery` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `params`（Record<string, string | number | undefined | null>）：`params` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `guardRoomSitesPath` 调用本符号；`unified_frontend/src/lib/api.ts` 的
 *         `getGuardRoomSiteConfig` 调用本符号；`unified_frontend/src/lib/api.ts` 的 `getGuardRoomSiteStatus`
 *         调用本符号；`unified_frontend/src/lib/api.ts` 的 `getGuardRoomSiteCameras` 调用本符号；另有 2 处静态调用
 *   - 内部调用：`queryString`、`includes`、`slice`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function withQuery(path: string, params: Record<string, string | number | undefined | null>) {
  const query = queryString(params)
  if (!query) return path
  return `${path}${path.includes('?') ? `&${query.slice(1)}` : query}`
}

/**
 * 功能：读取或查询 `getAlarms` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `limit`（未显式标注）：返回或处理的最大记录数；声明包含默认值 `100`
 *   - `eventTypes?`（readonly string[] | null）：`eventTypes` 对应的业务输入值
 * 返回：Promise<AlarmEvent[]>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/human_dwell/useHumanDwellMonitor.ts` 的 `useHumanDwellMonitor`
 *         调用本符号；`unified_frontend/src/sections/AlarmsSection.tsx` 的 `AlarmsSection`
 *         调用本符号；`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection::loadOverview` 调用本符号
 *   - 内部调用：`async`、`apiGet`、`eventTypesQuery`、`isArray`、`AlarmEvent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getAlarms = async (limit = 100, eventTypes?: readonly string[] | null): Promise<AlarmEvent[]> => {
  const data = await apiGet<AlarmEvent[] | AlarmsResponse>(`/alarms?limit=${limit}${eventTypesQuery(eventTypes)}`)
  return Array.isArray(data) ? data : (data?.items || [])
}

/**
 * 功能：读取或查询 `getStatistics` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `eventTypes?`（readonly string[] | null）：`eventTypes` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/Sidebar.tsx` 的 `Sidebar` 调用本符号；`unified_frontend/src/sections/StatisticsSection.tsx` 的
 *         `StatisticsSection` 调用本符号
 *   - 内部调用：`async`、`apiGet`、`eventTypesQuery`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常。
 */
export const getStatistics = async (eventTypes?: readonly string[] | null) =>
  apiGet(`/statistics?days=7${eventTypesQuery(eventTypes)}`)
/**
 * 功能：读取或查询 `getGuardRoomStatistics` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiGet`、`StatisticsResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getGuardRoomStatistics = () => apiGet<StatisticsResponse>('/statistics')
/**
 * 功能：读取或查询 `getConfig` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiGet`、`AppConfigPayload`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getConfig = () => apiGet<AppConfigPayload>('/config')
/**
 * 功能：更新或保存 `saveConfig` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `payload`（Partial<AppConfigPayload>）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiPost`、`AppConfigPayload`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const saveConfig = (payload: Partial<AppConfigPayload>) => apiPost<{ ok: boolean; restarted: boolean; config: AppConfigPayload }>('/config', payload)
/**
 * 功能：启动或执行 `startRuntime` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiPost`、`ControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const startRuntime = () => apiPost<ControlResponse>('/control/start')
/**
 * 功能：停止并释放 `stopRuntime` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiPost`、`ControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const stopRuntime = () => apiPost<ControlResponse>('/control/stop')
/**
 * 功能：实现 `restartRuntime` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiPost`、`ControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const restartRuntime = () => apiPost<ControlResponse>('/control/restart')
/**
 * 功能：实现 `streamUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const streamUrl = () => `${API_PREFIX}/stream.mjpg`
/**
 * 功能：实现 `frameUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const frameUrl = () => `${API_PREFIX}/frame.jpg`
/**
 * 功能：实现 `alarmImageUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarmId`（string）：`alarmId` 对应业务对象的唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AlarmsSection.tsx` 的 `AlarmsSection` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const alarmImageUrl = (alarmId: string) => `/api/alarms/${alarmId}/image`
/**
 * 功能：实现 `alarmVideoUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `alarmId`（string）：`alarmId` 对应业务对象的唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/AlarmsSection.tsx` 的 `AlarmsSection` 调用本符号
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const alarmVideoUrl = (alarmId: string) => `/api/alarms/${alarmId}/video`

type GuardRoomSitesResponse = {
  items?: GuardRoomSite[]
}

type GuardRoomCamerasResponse = {
  items?: GuardRoomCamera[]
}

export type CreateGuardRoomSitePayload = {
  name: string
  department?: string
  enabled?: boolean
  description?: string | null
  sort_order?: number
}

export type UpdateGuardRoomSitePayload = Partial<CreateGuardRoomSitePayload>

export type CreateGuardRoomCameraPayload = {
  name: string
  rtsp_url: string
  enabled?: boolean
  sort_order?: number
}

export type UpdateGuardRoomCameraPayload = Partial<CreateGuardRoomCameraPayload>

/**
 * 功能：实现 `guardRoomSitesPath` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department?`（string | null）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/api.ts` 的 `getGuardRoomSites` 调用本符号
 *   - 内部调用：`withQuery`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const guardRoomSitesPath = (department?: string | null) =>
  withQuery('/sites', { department })

/**
 * 功能：读取或查询 `getGuardRoomSites` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department?`（string | null）：业务部门名称或标识
 * 返回：Promise<GuardRoomSite[]>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/GuardBehaviorSection.tsx` 的 `GuardBehaviorSection`
 *         调用本符号；`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`async`、`apiGet`、`guardRoomSitesPath`、`GuardRoomSite`、`GuardRoomSitesResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getGuardRoomSites = async (department?: string | null): Promise<GuardRoomSite[]> => {
  const data = await apiGet<GuardRoomSitesResponse>(guardRoomSitesPath(department))
  return data.items || []
}

/**
 * 功能：创建或构建 `createGuardRoomSite` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `payload`（CreateGuardRoomSitePayload）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/GuardBehaviorSection.tsx` 的 `GuardBehaviorSection` 调用本符号
 *   - 内部调用：`apiPost`、`GuardRoomSite`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const createGuardRoomSite = (payload: CreateGuardRoomSitePayload) =>
  apiPost<GuardRoomSite>('/sites', payload)

/**
 * 功能：更新或保存 `updateGuardRoomSite` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `payload`（UpdateGuardRoomSitePayload）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`apiPut`、`GuardRoomSite`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const updateGuardRoomSite = (siteId: number, payload: UpdateGuardRoomSitePayload) =>
  apiPut<GuardRoomSite>(`/sites/${siteId}`, payload)

/**
 * 功能：删除或清理 `deleteGuardRoomSite` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/GuardBehaviorSection.tsx` 的 `GuardBehaviorSection` 调用本符号
 *   - 内部调用：`apiDelete`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const deleteGuardRoomSite = (siteId: number) =>
  apiDelete<{ success: boolean }>(`/sites/${siteId}`)

/**
 * 功能：读取或查询 `getGuardRoomSiteConfig` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `department?`（string | null）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection` 调用本符号
 *   - 内部调用：`apiGet`、`withQuery`、`AppConfigPayload`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getGuardRoomSiteConfig = (siteId: number, department?: string | null) =>
  apiGet<AppConfigPayload>(withQuery(`/sites/${siteId}/config`, { department }))

/**
 * 功能：更新或保存 `saveGuardRoomSiteConfig` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `payload`（Partial<AppConfigPayload>）：接口或事件携带的业务数据
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection` 调用本符号
 *   - 内部调用：`apiPost`、`AppConfigPayload`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const saveGuardRoomSiteConfig = (siteId: number, payload: Partial<AppConfigPayload>) =>
  apiPost<{ success: boolean; config: AppConfigPayload }>(`/sites/${siteId}/config`, payload)

/**
 * 功能：读取或查询 `getGuardRoomSiteStatus` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `department?`（string | null）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/guard_room/GuardRoomRuntimeControl.tsx` 的 `GuardRoomRuntimeControl`
 *         调用本符号；`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection::waitUntilRunning`
 *         调用本符号；`unified_frontend/src/sections/MonitorSection.tsx` 的 `MonitorSection` 调用本符号
 *   - 内部调用：`apiGet`、`withQuery`、`BackendStatus`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getGuardRoomSiteStatus = (siteId: number, department?: string | null) =>
  apiGet<BackendStatus>(withQuery(`/sites/${siteId}/status`, { department }))

/**
 * 功能：启动或执行 `startGuardRoomSiteRuntime` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/guard_room/GuardRoomRuntimeControl.tsx` 的 `GuardRoomRuntimeControl` 调用本符号
 *   - 内部调用：`async`、`apiPost`、`notifyPlatformRuntimeChanged`、`ControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const startGuardRoomSiteRuntime = async (siteId: number) => {
  const result = await apiPost<ControlResponse>(`/sites/${siteId}/control/start`)
  notifyPlatformRuntimeChanged()
  return result
}

/**
 * 功能：停止并释放 `stopGuardRoomSiteRuntime` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/guard_room/GuardRoomRuntimeControl.tsx` 的 `GuardRoomRuntimeControl` 调用本符号
 *   - 内部调用：`async`、`apiPost`、`notifyPlatformRuntimeChanged`、`ControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const stopGuardRoomSiteRuntime = async (siteId: number) => {
  const result = await apiPost<ControlResponse>(`/sites/${siteId}/control/stop`)
  notifyPlatformRuntimeChanged()
  return result
}

/**
 * 功能：实现 `restartGuardRoomSiteRuntime` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection` 调用本符号
 *   - 内部调用：`async`、`apiPost`、`notifyPlatformRuntimeChanged`、`ControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const restartGuardRoomSiteRuntime = async (siteId: number) => {
  const result = await apiPost<ControlResponse>(`/sites/${siteId}/control/restart`)
  notifyPlatformRuntimeChanged()
  return result
}

/**
 * 功能：读取或查询 `getGuardRoomSiteCameras` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `department?`（string | null）：业务部门名称或标识
 * 返回：Promise<GuardRoomCamera[]>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`async`、`apiGet`、`withQuery`、`GuardRoomCamera`、`GuardRoomCamerasResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getGuardRoomSiteCameras = async (siteId: number, department?: string | null): Promise<GuardRoomCamera[]> => {
  const data = await apiGet<GuardRoomCamerasResponse>(withQuery(`/sites/${siteId}/cameras`, { department }))
  return data.items || []
}

/**
 * 功能：创建或构建 `createGuardRoomSiteCamera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `payload`（CreateGuardRoomCameraPayload）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection` 调用本符号；`unified_frontend/src/sections/HomeSection.tsx`
 *         的 `HomeSection` 调用本符号
 *   - 内部调用：`async`、`apiPost`、`notifyPlatformCamerasChanged`、`GuardRoomCamera`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const createGuardRoomSiteCamera = async (siteId: number, payload: CreateGuardRoomCameraPayload) => {
  const camera = await apiPost<GuardRoomCamera>(`/sites/${siteId}/cameras`, payload)
  notifyPlatformCamerasChanged()
  return camera
}

/**
 * 功能：更新或保存 `updateGuardRoomCamera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraId`（number）：摄像头唯一标识
 *   - `payload`（UpdateGuardRoomCameraPayload）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`async`、`apiPut`、`notifyPlatformCamerasChanged`、`GuardRoomCamera`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const updateGuardRoomCamera = async (cameraId: number, payload: UpdateGuardRoomCameraPayload) => {
  const camera = await apiPut<GuardRoomCamera>(`/cameras/${cameraId}`, payload)
  notifyPlatformCamerasChanged()
  return camera
}

/**
 * 功能：删除或清理 `deleteGuardRoomCamera` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraId`（number）：摄像头唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/ConfigSection.tsx` 的 `ConfigSection` 调用本符号
 *   - 内部调用：`async`、`apiDelete`、`notifyPlatformCamerasChanged`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const deleteGuardRoomCamera = async (cameraId: number) => {
  const result = await apiDelete<{ success: boolean }>(`/cameras/${cameraId}`)
  notifyPlatformCamerasChanged()
  return result
}

/**
 * 功能：实现 `guardRoomSiteFrameUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `department?`（string | null）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/MonitorSection.tsx` 的 `MonitorSection` 调用本符号
 *   - 内部调用：`withQuery`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const guardRoomSiteFrameUrl = (siteId: number, department?: string | null) =>
  `${API_PREFIX}${withQuery(`/sites/${siteId}/frame.jpg`, { department })}`
/**
 * 功能：实现 `guardRoomSiteCameraFrameUrl` 对应的接口访问逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `siteId`（number）：保安室站点唯一标识
 *   - `cameraId`（string）：摄像头唯一标识
 *   - `nonce?`（number）：`nonce` 对应的业务输入值
 *   - `department?`（string | null）：业务部门名称或标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`withQuery`、`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const guardRoomSiteCameraFrameUrl = (siteId: number, cameraId: string, nonce?: number, department?: string | null) => {
  return `${API_PREFIX}${withQuery(`/sites/${siteId}/cameras/${encodeURIComponent(cameraId)}/frame.jpg`, { t: nonce, department })}`
}
