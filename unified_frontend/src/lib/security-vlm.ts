// 文件说明：实现`security-vlm` 模块相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { notifyPlatformCamerasChanged } from '@/lib/camera-events'

/**
 * 功能：读取或查询 `readError` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `response`（Response）：待读取或更新的 HTTP 响应
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`text`、`then`、`parse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function readError(response: Response) {
  return response.text().then((text) => {
    if (!text) return `${response.status} ${response.statusText}`
    try {
      const parsed = JSON.parse(text) as { detail?: string; message?: string }
      return parsed.detail || parsed.message || text
    } catch {
      return text
    }
  })
}

/**
 * 功能：实现 `securityVlmRequest` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `method`（'GET' | 'POST' | 'PUT' | 'DELETE'）：`method` 对应的业务输入值
 *   - `path`（string）：目标路径
 *   - `body?`（unknown）：`body` 对应的业务输入值
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：Promise<T>；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/security-vlm.ts` 的 `securityVlmGet` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的
 *         `securityVlmPost` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `securityVlmPut`
 *         调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `securityVlmDelete` 调用本符号
 *   - 内部调用：`fetch`、`stringify`、`dispatchEvent`、`Event`、`Error`、`readError`、`json`、`T`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
async function securityVlmRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/security-vlm${path}`, {
    ...init,
    method,
    credentials: 'include',
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<T>
}

/**
 * 功能：读取或查询 `securityVlmGet` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/security-vlm.ts` 的 `getSecurityVlmHealth` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的
 *         `getSecurityVlmHistory` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `getSecurityVlmCameras`
 *         调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `getSecurityVlmCameraCredentials` 调用本符号；另有 2 处静态调用
 *   - 内部调用：`securityVlmRequest`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const securityVlmGet = <T>(path: string, init?: RequestInit) =>
  securityVlmRequest<T>('GET', path, undefined, init)
/**
 * 功能：实现 `securityVlmPost` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `body?`（unknown）：`body` 对应的业务输入值
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/security-vlm.ts` 的 `testSecurityVlmCamera` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的
 *         `controlSecurityVlmCamera` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `startAllSecurityVlmCameras`
 *         调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `stopAllSecurityVlmCameras` 调用本符号；另有 5 处静态调用
 *   - 内部调用：`securityVlmRequest`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const securityVlmPost = <T>(path: string, body?: unknown, init?: RequestInit) =>
  securityVlmRequest<T>('POST', path, body, init)
/**
 * 功能：更新或保存 `securityVlmPut` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `body?`（unknown）：`body` 对应的业务输入值
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`securityVlmRequest`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const securityVlmPut = <T>(path: string, body?: unknown, init?: RequestInit) =>
  securityVlmRequest<T>('PUT', path, body, init)
/**
 * 功能：删除或清理 `securityVlmDelete` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（string）：目标路径
 *   - `init?`（RequestInit）：请求初始化选项
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`securityVlmRequest`、`T`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const securityVlmDelete = <T>(path: string, init?: RequestInit) =>
  securityVlmRequest<T>('DELETE', path, undefined, init)

export const SECURITY_VLM_DEPARTMENTS = [
  'general_electric',
  'electronics_electrician',
  'electrical_components',
  'precious_metal_recycling',
] as const

export type SecurityVlmDepartment = typeof SECURITY_VLM_DEPARTMENTS[number]

/**
 * 功能：实现 `departmentApi` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/security-vlm.ts` 的 `getSecurityVlmHealth` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的
 *         `getSecurityVlmHistory` 调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `getSecurityVlmCameras`
 *         调用本符号；`unified_frontend/src/lib/security-vlm.ts` 的 `getSecurityVlmCameraCredentials` 调用本符号；另有 10 处静态调用
 *   - 内部调用：`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const departmentApi = (department: SecurityVlmDepartment) =>
  `/api/departments/${encodeURIComponent(department)}`

export type SecurityVlmWorkerStatus = {
  ok?: boolean
  width?: number
  height?: number
  fps?: number
  [key: string]: unknown
}

export type SecurityVlmStats = {
  total?: number
  compliant?: number
  non_compliant?: number
  error?: number
  rate?: number
  queue?: number
  budget?: {
    spent_yuan?: number
    daily_limit_yuan?: number
  }
}

export type SecurityVlmHistoryItem = {
  time?: string
  session_id?: string
  camera_id?: string
  camera_name?: string
  roi_name?: string
  duration_sec?: number
  status?: 'compliant' | 'non_compliant' | 'error' | string
  upper_checked?: boolean | null
  middle_checked?: boolean | null
  lower_checked?: boolean | null
  arms_open?: boolean | null
  reason?: string
  error?: string
}

export type SecurityVlmRoiPoint = [number, number]
export type SecurityVlmRoiPolygon = SecurityVlmRoiPoint[]
export type SecurityVlmLegacyRoiRect = [number, number, number, number]
export type SecurityVlmRoiValue = SecurityVlmRoiPolygon | SecurityVlmLegacyRoiRect
export type SecurityVlmRoiMap = Record<string, SecurityVlmRoiValue>

export type SecurityVlmCamera = {
  camera_id: string
  name: string
  rtsp_url: string
  has_rtsp_url: boolean
  running: boolean
  desired_running?: boolean
  workers?: Record<string, boolean>
  last_error?: string
  restart_at?: number | null
  capture?: SecurityVlmWorkerStatus
  detector?: SecurityVlmWorkerStatus
  session?: SecurityVlmWorkerStatus
  staff_rois?: SecurityVlmRoiMap
}

export type SecurityVlmCameraCredentials = Pick<
  SecurityVlmCamera,
  'camera_id' | 'name' | 'rtsp_url'
>

export type SecurityVlmHealth = {
  running?: boolean
  ts?: number
  capture?: SecurityVlmWorkerStatus
  detector?: SecurityVlmWorkerStatus
  session?: SecurityVlmWorkerStatus
  vlm?: SecurityVlmWorkerStatus
  stats?: SecurityVlmStats
  history?: SecurityVlmHistoryItem[]
  staff_rois?: SecurityVlmRoiMap
  cameras?: SecurityVlmCamera[]
}

export type SecurityVlmRoisResponse = {
  staff_rois: SecurityVlmRoiMap
  available_slots: string[]
  video_id?: string
  camera_id?: string
  ok?: boolean
}

export type SecurityVlmControlResponse = {
  ok?: boolean
  success?: boolean
  camera_id?: string
  running?: boolean
  desired_running?: boolean
  message?: string
  results?: Record<string, SecurityVlmControlResponse>
}

/**
 * 功能：读取或查询 `getSecurityVlmHealth` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmGet`、`departmentApi`、`SecurityVlmHealth`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getSecurityVlmHealth = (department: SecurityVlmDepartment) =>
  securityVlmGet<SecurityVlmHealth>(`${departmentApi(department)}/health`)

/**
 * 功能：读取或查询 `getSecurityVlmHistory` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `limit`（未显式标注）：返回或处理的最大记录数；声明包含默认值 `100`
 *   - `cameraId?`（string）：摄像头唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`URLSearchParams`、`String`、`set`、`securityVlmGet`、`departmentApi`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getSecurityVlmHistory = (
  department: SecurityVlmDepartment,
  limit = 100,
  cameraId?: string,
) => {
  const query = new URLSearchParams({ limit: String(limit) })
  if (cameraId) query.set('camera_id', cameraId)
  return securityVlmGet<{ date?: string; stats?: SecurityVlmStats; history?: SecurityVlmHistoryItem[] }>(
    `${departmentApi(department)}/history?${query}`,
  )
}

/**
 * 功能：读取或查询 `getSecurityVlmCameras` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`securityVlmGet`、`departmentApi`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getSecurityVlmCameras = (department: SecurityVlmDepartment) =>
  securityVlmGet<{ cameras: SecurityVlmCamera[] }>(
    `${departmentApi(department)}/cameras`,
  )

/**
 * 功能：读取或查询 `getSecurityVlmCameraCredentials` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `cameraId`（string）：摄像头唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmGet`、`departmentApi`、`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getSecurityVlmCameraCredentials = (
  department: SecurityVlmDepartment,
  cameraId: string,
) =>
  securityVlmGet<{ camera: SecurityVlmCameraCredentials }>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/credentials`,
  )

/**
 * 功能：创建或构建 `createSecurityVlmCamera` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `name`（string）：业务对象名称
 *   - `rtspUrl`（string）：`rtspUrl` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection`
 *         调用本符号；`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`async`、`securityVlmPost`、`departmentApi`、`notifyPlatformCamerasChanged`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const createSecurityVlmCamera = async (
  department: SecurityVlmDepartment,
  name: string,
  rtspUrl: string,
) => {
  const result = await securityVlmPost<{ ok: boolean; camera: SecurityVlmCamera }>(
    `${departmentApi(department)}/cameras`,
    { name, rtsp_url: rtspUrl },
  )
  notifyPlatformCamerasChanged()
  return result
}

/**
 * 功能：更新或保存 `updateSecurityVlmCamera` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `cameraId`（string）：摄像头唯一标识
 *   - `name`（string）：业务对象名称
 *   - `rtspUrl`（string）：`rtspUrl` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`async`、`securityVlmPut`、`departmentApi`、`encodeURIComponent`、`notifyPlatformCamerasChanged`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const updateSecurityVlmCamera = async (
  department: SecurityVlmDepartment,
  cameraId: string,
  name: string,
  rtspUrl: string,
) => {
  const result = await securityVlmPut<{ ok: boolean; camera: SecurityVlmCamera }>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}`,
    { name, rtsp_url: rtspUrl },
  )
  notifyPlatformCamerasChanged()
  return result
}

/**
 * 功能：删除或清理 `deleteSecurityVlmCamera` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `cameraId`（string）：摄像头唯一标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`async`、`securityVlmDelete`、`departmentApi`、`encodeURIComponent`、`notifyPlatformCamerasChanged`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const deleteSecurityVlmCamera = async (
  department: SecurityVlmDepartment,
  cameraId: string,
) => {
  const result = await securityVlmDelete<{ ok: boolean; camera: SecurityVlmCamera }>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}`,
  )
  notifyPlatformCamerasChanged()
  return result
}

/**
 * 功能：验证 `testSecurityVlmCamera` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `rtspUrl`（string）：`rtspUrl` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmPost`、`departmentApi`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const testSecurityVlmCamera = (
  department: SecurityVlmDepartment,
  rtspUrl: string,
) =>
  securityVlmPost<{ ok: boolean; codec_name: string; width: number; height: number }>(
    `${departmentApi(department)}/cameras/test`,
    { rtsp_url: rtspUrl },
  )

/**
 * 功能：实现 `controlSecurityVlmCamera` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `cameraId`（string）：摄像头唯一标识
 *   - `action`（'start' | 'stop' | 'restart'）：`action` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmPost`、`departmentApi`、`encodeURIComponent`、`SecurityVlmControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const controlSecurityVlmCamera = (
  department: SecurityVlmDepartment,
  cameraId: string,
  action: 'start' | 'stop' | 'restart',
) =>
  securityVlmPost<SecurityVlmControlResponse>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/control/${action}`,
  )

/**
 * 功能：启动或执行 `startAllSecurityVlmCameras` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmPost`、`departmentApi`、`SecurityVlmControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const startAllSecurityVlmCameras = (department: SecurityVlmDepartment) =>
  securityVlmPost<SecurityVlmControlResponse>(
    `${departmentApi(department)}/cameras/control/start-all`,
  )

/**
 * 功能：停止并释放 `stopAllSecurityVlmCameras` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmPost`、`departmentApi`、`SecurityVlmControlResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const stopAllSecurityVlmCameras = (department: SecurityVlmDepartment) =>
  securityVlmPost<SecurityVlmControlResponse>(
    `${departmentApi(department)}/cameras/control/stop-all`,
  )

/**
 * 功能：读取或查询 `getSecurityVlmCameraRois` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `cameraId`（string）：摄像头唯一标识
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmGet`、`departmentApi`、`encodeURIComponent`、`SecurityVlmRoisResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getSecurityVlmCameraRois = (
  department: SecurityVlmDepartment,
  cameraId: string,
) =>
  securityVlmGet<SecurityVlmRoisResponse>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/rois`,
  )

/**
 * 功能：更新或保存 `saveSecurityVlmCameraRois` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `cameraId`（string）：摄像头唯一标识
 *   - `staffRois`（Record<string, SecurityVlmRoiPolygon>）：`staffRois` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`securityVlmPost`、`departmentApi`、`encodeURIComponent`、`SecurityVlmRoisResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const saveSecurityVlmCameraRois = (
  department: SecurityVlmDepartment,
  cameraId: string,
  staffRois: Record<string, SecurityVlmRoiPolygon>,
) =>
  securityVlmPost<SecurityVlmRoisResponse>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/rois`,
    { staff_rois: staffRois },
  )

/**
 * 功能：读取或查询 `getSecurityVlmRois` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`securityVlmGet`、`SecurityVlmRoisResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const getSecurityVlmRois = () => securityVlmGet<SecurityVlmRoisResponse>('/api/rois')

/**
 * 功能：更新或保存 `saveSecurityVlmRois` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `staff_rois`（Record<string, SecurityVlmRoiPolygon>）：`staff_rois` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`securityVlmPost`、`SecurityVlmRoisResponse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const saveSecurityVlmRois = (
  staff_rois: Record<string, SecurityVlmRoiPolygon>,
) =>
  securityVlmPost<SecurityVlmRoisResponse>('/api/rois', { staff_rois })

/**
 * 功能：启动或执行 `startSecurityVlmRuntime` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`securityVlmPost`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const startSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/start')

/**
 * 功能：停止并释放 `stopSecurityVlmRuntime` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`securityVlmPost`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const stopSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/stop')

/**
 * 功能：实现 `restartSecurityVlmRuntime` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`securityVlmPost`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const restartSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/restart')

/**
 * 功能：实现 `securityVlmVideoUrl` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `kind`（'original' | 'rule'）：`kind` 对应的业务输入值
 *   - `nonce?`（number）：`nonce` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const securityVlmVideoUrl = (kind: 'original' | 'rule', nonce?: number) =>
  `/security-vlm/video/${kind}${nonce ? `?t=${nonce}` : ''}`

/**
 * 功能：实现 `securityVlmCameraVideoUrl` 对应的`security-vlm` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department`（SecurityVlmDepartment）：业务部门名称或标识
 *   - `cameraId`（string）：摄像头唯一标识
 *   - `kind`（'original' | 'rule'）：`kind` 对应的业务输入值
 *   - `nonce?`（number）：`nonce` 对应的业务输入值
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/security-vlm/SecurityVideoPanel.tsx` 的 `SecurityVideoPanel`
 *         调用本符号；`unified_frontend/src/sections/SecurityVlmSection.tsx` 的 `SecurityVlmSection` 调用本符号
 *   - 内部调用：`departmentApi`、`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export const securityVlmCameraVideoUrl = (
  department: SecurityVlmDepartment,
  cameraId: string,
  kind: 'original' | 'rule',
  nonce?: number,
) =>
  `/security-vlm${departmentApi(department)}/video/${encodeURIComponent(cameraId)}/${kind}${nonce ? `?t=${nonce}` : ''}`
