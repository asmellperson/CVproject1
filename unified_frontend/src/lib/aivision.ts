// 文件说明：实现`aivision` 模块相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { notifyPlatformCamerasChanged } from '@/lib/camera-events'

/**
 * 功能：实现 `trimTrailingSlash` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
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

const PUBLIC_ORIGIN = trimTrailingSlash((import.meta.env.VITE_PUBLIC_ORIGIN as string | undefined) || '')

export const AIVISION_URL =
  (import.meta.env.VITE_AIVISION_URL as string | undefined) ||
  (PUBLIC_ORIGIN ? `${PUBLIC_ORIGIN}/aivision/` : '/aivision/')

export type AiVisionCamera = {
  id: string
  name: string
  shm_name: string
  url?: string
  camera_id: number
  fps?: number
  enabled: boolean
  functions: Record<string, boolean> | string[]
  department?: string | null
}

export type AiVisionDepartment = {
  name: string
  display_name: string
}

export type AiVisionFeatureMeta = {
  name: string
  display_name: string
  required_models: string[]
  violation_type: number
  config_schema: Record<string, unknown>
  departments: string[]
}

export type CreateAiVisionCameraPayload = {
  name: string
  url: string
  shm_name: string
  fps?: number
  max_restart?: number
  enabled?: boolean
  department?: string | null
}

export type CreateAiVisionFeatureCameraPayload = Omit<CreateAiVisionCameraPayload, 'shm_name'> & {
  shm_name?: string
}

export type UpdateAiVisionCameraPayload = Partial<Pick<CreateAiVisionCameraPayload, 'name' | 'url' | 'fps' | 'max_restart' | 'enabled' | 'department'>>

export type AiVisionExceptionAlertSettings = {
  wechat_enable: boolean
  wechat_user: string
  repeat_interval_minutes: number
}

export type AiVisionModel = {
  id: number
  name: string
  type: string
  path: string
  import_path?: string | null
  description?: string | null
  enable: boolean
}

export type CreateAiVisionModelPayload = Pick<AiVisionModel, 'name' | 'type' | 'path'> &
  Partial<Pick<AiVisionModel, 'import_path' | 'description' | 'enable'>>

export type AiVisionFeatureConfig = {
  enable: boolean
  value: Record<string, unknown>
  alarm?: unknown
}

export type AiVisionLogisticsSinglePersonStatus = {
  camera_key: string
  feature: string
  online: boolean
  count: number | null
  alarm: boolean
  reason: 'normal' | 'empty' | 'multiple' | 'unknown'
  updated_at: string | null
}

export type AiVisionHumanDwellStatus = {
  camera_key: string
  feature: string
  online: boolean
  count: number | null
  alarm: boolean
  reason: 'normal' | 'loitering' | 'unknown'
  duration_seconds: number | null
  threshold_seconds: number | null
  updated_at: string | null
}

type AiVisionFeatureConfigResponse = {
  camera: {
    id: number
    name: string
    shm_name: string
    enable: boolean
  }
  feature: string
  config: AiVisionFeatureConfig
}

type AiVisionCamerasResponse = {
  cameras: AiVisionCamera[]
} | AiVisionCamera[]

/**
 * 功能：读取或查询 `readAiVisionError` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `response`（Response）：待读取或更新的 HTTP 响应
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/aivision.ts` 的 `getAiVisionCameras` 调用本符号；`unified_frontend/src/lib/aivision.ts` 的
 *         `getAiVisionLogisticsSinglePersonStatus` 调用本符号；`unified_frontend/src/lib/aivision.ts` 的 `getAiVisionHumanDwellStatus`
 *         调用本符号；`unified_frontend/src/lib/aivision.ts` 的 `getAiVisionDepartments` 调用本符号；另有 14 处静态调用
 *   - 内部调用：`dispatchEvent`、`Event`、`text`、`parse`。
 * 副作用/注意事项：会读取或修改浏览器全局对象/DOM 状态。
 */
async function readAiVisionError(response: Response) {
  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  let detail = await response.text().catch(() => '')
  try {
    const parsed = JSON.parse(detail) as { detail?: string }
    detail = parsed.detail || detail
  } catch {
    // Keep the raw response text when it is not JSON.
  }
  return detail || `${response.status} ${response.statusText}`
}

/**
 * 功能：读取或查询 `getAiVisionCameras` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `department?`（string）：业务部门名称或标识
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor`
 *         调用本符号；`unified_frontend/src/sections/HumanDetectionSection.tsx` 的 `HumanDetectionSection`
 *         调用本符号；`unified_frontend/src/sections/PhoneDetectionSection.tsx` 的 `PhoneDetectionSection`
 *         调用本符号；`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`URLSearchParams`、`set`、`toString`、`fetch`、`Error`、`readAiVisionError`、`json`、`isArray`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionCameras(department?: string) {
  const params = new URLSearchParams()
  if (department) params.set('department', department)
  const query = params.toString()
  const response = await fetch(`/api/aivision/cameras${query ? `?${query}` : ''}`, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const payload = (await response.json()) as AiVisionCamerasResponse
  return Array.isArray(payload) ? payload : payload.cameras || []
}

/**
 * 功能：读取或查询 `getAiVisionLogisticsSinglePersonStatus` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `feature`（string）：`feature` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`fetch`、`encodeURIComponent`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionLogisticsSinglePersonStatus(cameraKey: string, feature: string) {
  const response = await fetch(
    `/api/aivision/cameras/${encodeURIComponent(cameraKey)}/features/${encodeURIComponent(feature)}/status`,
    { credentials: 'include' },
  )
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionLogisticsSinglePersonStatus
}

/**
 * 功能：读取或查询 `getAiVisionHumanDwellStatus` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `feature`（未显式标注）：`feature` 对应的业务输入值；声明包含默认值 `'detect_human'`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/human_dwell/useHumanDwellMonitor.ts` 的 `useHumanDwellMonitor` 调用本符号
 *   - 内部调用：`fetch`、`encodeURIComponent`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionHumanDwellStatus(cameraKey: string, feature = 'detect_human') {
  const response = await fetch(
    `/api/aivision/cameras/${encodeURIComponent(cameraKey)}/features/${encodeURIComponent(feature)}/status`,
    { credentials: 'include' },
  )
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionHumanDwellStatus
}

/**
 * 功能：读取或查询 `getAiVisionDepartments` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`fetch`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionDepartments() {
  const response = await fetch('/api/aivision/departments', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionDepartment[]
}

/**
 * 功能：读取或查询 `getAiVisionDepartmentFeatures` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `departmentName`（string）：`departmentName` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`fetch`、`encodeURIComponent`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionDepartmentFeatures(departmentName: string) {
  const response = await fetch(`/api/aivision/departments/${encodeURIComponent(departmentName)}/features`, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as Array<{ name: string; display_name: string }>
}

/**
 * 功能：读取或查询 `getAiVisionCameraKey` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `camera`（AiVisionCamera）：摄像头配置或实体
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor`
 *         调用本符号；`unified_frontend/src/components/human_dwell/HumanDwellMonitorView.tsx` 的 `HumanDwellMonitorView`
 *         调用本符号；`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`String`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function getAiVisionCameraKey(camera: AiVisionCamera) {
  return camera.shm_name || camera.id || String(camera.camera_id)
}

/**
 * 功能：检查或判断 `isAiVisionFeatureEnabled` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `camera`（AiVisionCamera）：摄像头配置或实体
 *   - `feature`（string）：`feature` 对应的业务输入值
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor`
 *         调用本符号；`unified_frontend/src/components/FeatureCameraManager.tsx` 的 `FeatureCameraManager`
 *         调用本符号；`unified_frontend/src/sections/HumanDetectionSection.tsx` 的 `HumanDetectionSection`
 *         调用本符号；`unified_frontend/src/sections/PhoneDetectionSection.tsx` 的 `PhoneDetectionSection` 调用本符号
 *   - 内部调用：`isArray`、`includes`、`Boolean`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function isAiVisionFeatureEnabled(camera: AiVisionCamera, feature: string) {
  const functions = camera.functions
  if (Array.isArray(functions)) {
    return functions.includes(feature)
  }
  return Boolean(functions?.[feature])
}

export type AiVisionFrameOptions = {
  maxWidth?: number
  maxHeight?: number
  quality?: number
}

/**
 * 功能：实现 `aiVisionFrameUrl` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `feature?`（string）：`feature` 对应的业务输入值
 *   - `nonce?`（number）：`nonce` 对应的业务输入值
 *   - `options`（AiVisionFrameOptions）：`options` 对应的业务输入值；声明包含默认值 `{}`
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.frame.ts` 的 `buildAiVisionPreviewFrameUrl` 调用本符号
 *   - 内部调用：`URLSearchParams`、`set`、`String`、`toString`、`encodeURIComponent`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function aiVisionFrameUrl(cameraKey: string, feature?: string, nonce?: number, options: AiVisionFrameOptions = {}) {
  const params = new URLSearchParams()
  if (feature) params.set('feature', feature)
  if (nonce) params.set('t', String(nonce))
  if (options.maxWidth) params.set('max_width', String(options.maxWidth))
  if (options.maxHeight) params.set('max_height', String(options.maxHeight))
  if (options.quality) params.set('quality', String(options.quality))
  const query = params.toString()
  return `/api/aivision/cameras/${encodeURIComponent(cameraKey)}/frame.jpg${query ? `?${query}` : ''}`
}

/**
 * 功能：创建或构建 `createAiVisionCamera` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `payload`（CreateAiVisionCameraPayload）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`fetch`、`stringify`、`Error`、`readAiVisionError`、`json`、`dispatchEvent`、`Event`、`notifyPlatformCamerasChanged`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
export async function createAiVisionCamera(payload: CreateAiVisionCameraPayload) {
  const response = await fetch('/api/aivision/cameras', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return camera
}

/**
 * 功能：创建或构建 `createAiVisionFeatureCamera` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（string）：`feature` 对应的业务输入值
 *   - `payload`（CreateAiVisionFeatureCameraPayload）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/FeatureCameraManager.tsx` 的 `FeatureCameraManager` 调用本符号
 *   - 内部调用：`fetch`、`encodeURIComponent`、`stringify`、`Error`、`readAiVisionError`、`json`、`dispatchEvent`、`Event`、`notifyPlatformCamerasChanged`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
export async function createAiVisionFeatureCamera(
  feature: string,
  payload: CreateAiVisionFeatureCameraPayload,
) {
  const response = await fetch(`/api/v2/features/${encodeURIComponent(feature)}/cameras`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return camera
}

/**
 * 功能：更新或保存 `updateAiVisionCamera` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `payload`（UpdateAiVisionCameraPayload）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`fetch`、`encodeURIComponent`、`stringify`、`Error`、`readAiVisionError`、`json`、`dispatchEvent`、`Event`、`notifyPlatformCamerasChanged`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
export async function updateAiVisionCamera(cameraKey: string, payload: UpdateAiVisionCameraPayload) {
  const response = await fetch(`/api/aivision/cameras/${encodeURIComponent(cameraKey)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return camera
}

/**
 * 功能：删除或清理 `deleteAiVisionCamera` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`fetch`、`encodeURIComponent`、`Error`、`readAiVisionError`、`dispatchEvent`、`Event`、`notifyPlatformCamerasChanged`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
export async function deleteAiVisionCamera(cameraKey: string) {
  const response = await fetch(`/api/aivision/cameras/${encodeURIComponent(cameraKey)}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return (await response.json()) as { ok: boolean }
}

/**
 * 功能：读取或查询 `getAiVisionExceptionAlertSettings` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`fetch`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionExceptionAlertSettings() {
  const response = await fetch('/api/v2/runtime/exception-alert', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionExceptionAlertSettings
}

/**
 * 功能：更新或保存 `saveAiVisionExceptionAlertSettings` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `payload`（AiVisionExceptionAlertSettings）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`fetch`、`stringify`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function saveAiVisionExceptionAlertSettings(payload: AiVisionExceptionAlertSettings) {
  const response = await fetch('/api/v2/runtime/exception-alert', {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionExceptionAlertSettings
}

/**
 * 功能：读取或查询 `getAiVisionFeatureConfig` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（string）：`feature` 对应的业务输入值
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor`
 *         调用本符号；`unified_frontend/src/components/FeatureCameraManager.tsx` 的 `FeatureCameraManager`
 *         调用本符号；`unified_frontend/src/sections/HumanDetectionSection.tsx` 的 `HumanDetectionSection` 调用本符号
 *   - 内部调用：`fetch`、`encodeURIComponent`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionFeatureConfig(feature: string, cameraKey: string) {
  const response = await fetch(`/api/v2/features/${encodeURIComponent(feature)}/configs/${encodeURIComponent(cameraKey)}`, {
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionFeatureConfigResponse
}

/**
 * 功能：更新或保存 `saveAiVisionFeatureConfig` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `feature`（string）：`feature` 对应的业务输入值
 *   - `cameraKey`（string）：`cameraKey` 对应的业务输入值
 *   - `config`（AiVisionFeatureConfig）：运行配置对象
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/FeatureCameraManager.tsx` 的 `FeatureCameraManager`
 *         调用本符号；`unified_frontend/src/sections/HumanDetectionSection.tsx` 的 `HumanDetectionSection` 调用本符号
 *   - 内部调用：`fetch`、`encodeURIComponent`、`stringify`、`Error`、`readAiVisionError`、`dispatchEvent`、`Event`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
export async function saveAiVisionFeatureConfig(feature: string, cameraKey: string, config: AiVisionFeatureConfig) {
  const response = await fetch(`/api/v2/features/${encodeURIComponent(feature)}/configs/${encodeURIComponent(cameraKey)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  window.dispatchEvent(new Event('aivision:cameras-changed'))
  return (await response.json()) as AiVisionFeatureConfigResponse
}

/**
 * 功能：读取或查询 `getAiVisionModels` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`fetch`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function getAiVisionModels() {
  const response = await fetch('/api/aivision/models', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModel[]
}

/**
 * 功能：更新或保存 `updateAiVisionModel` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `modelId`（number）：模型唯一标识
 *   - `payload`（Partial<Pick<AiVisionModel, 'path'>>）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`fetch`、`encodeURIComponent`、`String`、`stringify`、`Error`、`readAiVisionError`、`return`、`json`、`Pick`、`AiVisionModel`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function updateAiVisionModel(modelId: number, payload: Partial<Pick<AiVisionModel, 'path'>>) {
  const response = await fetch(`/api/aivision/models/${encodeURIComponent(String(modelId))}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModel
}

/**
 * 功能：创建或构建 `createAiVisionModel` 对应的`aivision` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `payload`（CreateAiVisionModelPayload）：接口或事件携带的业务数据
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`fetch`、`stringify`、`Error`、`readAiVisionError`、`return`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
export async function createAiVisionModel(payload: CreateAiVisionModelPayload) {
  const response = await fetch('/api/aivision/models', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModel
}
