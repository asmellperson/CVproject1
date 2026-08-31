// 文件说明：实现摄像头的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { AiVisionCamera } from '@/lib/aivision'
import type {
  LogisticsCameraInventoryItem,
  LogisticsCameraInventoryMembership,
} from '@/components/logistics_single_person/types'

export type FeatureCameraCounts = Record<string, {
  cameraCount: number
  enabledCameraCount: number
}>

type CameraInventoryItem = {
  id?: string
  shm_name?: string
  camera_id?: number
  enabled: boolean
  functions: Record<string, boolean> | string[]
  logisticsOnline?: boolean
}

export type OverviewAiVisionCamera = AiVisionCamera & {
  inventoryOnly?: boolean
  logisticsOnline?: boolean
  logisticsMemberships?: LogisticsCameraInventoryMembership[]
}

export type CameraInventorySummary = {
  cameraTotal: number
  cameraOnline: number
  cameraOffline: number
}

const AI_VISION_FEATURES = [
  'blocks',
  'detect_door',
  'detect_face',
  'detect_human',
  'detect_human_haoda',
  'detect_logistics_single_person',
  'detect_logistics_single_person_electronics_electrician',
  'detect_logistics_single_person_electrical_components',
  'detect_logistics_single_person_precious_metal_recycling',
  'detect_phone',
]

/**
 * 功能：检查或判断 `hasFeature` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `camera`（CameraInventoryItem）：摄像头配置或实体
 *   - `feature`（string）：`feature` 对应的业务输入值
 * 返回：boolean（由实现推断）；返回条件是否成立。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/homeCameraCounts.ts` 的 `getLoadedAiVisionFeatureCounts` 调用本符号
 *   - 内部调用：`isArray`、`includes`、`Boolean`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function hasFeature(camera: CameraInventoryItem, feature: string) {
  return Array.isArray(camera.functions)
    ? camera.functions.includes(feature)
    : Boolean(camera.functions?.[feature])
}

/**
 * 功能：将普通 AiVision 摄像头与物流通道成员清单按 `camera_id` 合并，补齐遗漏摄像头和物流功能标签。
 * 参数：
 *   - `cameras`（AiVisionCamera[]）：普通 AiVision 摄像头接口返回值
 *   - `logisticsCameras`（LogisticsCameraInventoryItem[]）：物流通道成员清单
 * 返回：OverviewAiVisionCamera[]；返回按物理摄像头去重、可供首页统一统计和展示的清单。
 * 调用关系：
 *   - 调用方：`HomeSection` 的 `mergedAiVisionCameras` 计算调用本符号；单元测试直接调用验证去重与回退
 *   - 内部调用：`Map`、`Array.isArray`、`Object.fromEntries`、`map`、`push`。
 * 副作用/注意事项：不修改输入数组；物流清单补出的项目不含 RTSP 地址并标记为 `inventoryOnly`，避免进入编辑流程。
 */
export function mergeAiVisionAndLogisticsCameras(
  cameras: AiVisionCamera[],
  logisticsCameras: LogisticsCameraInventoryItem[],
): OverviewAiVisionCamera[] {
  const logisticsByCameraId = new Map(
    logisticsCameras.map((camera) => [camera.camera_id, camera]),
  )
  const merged = cameras.map<OverviewAiVisionCamera>((camera) => {
    const logisticsCamera = logisticsByCameraId.get(camera.camera_id)
    if (!logisticsCamera) return { ...camera }
    logisticsByCameraId.delete(camera.camera_id)
    const functions = Array.isArray(camera.functions)
      ? Object.fromEntries(camera.functions.map((feature) => [feature, true]))
      : { ...camera.functions }
    for (const membership of logisticsCamera.memberships) {
      functions[membership.feature_name] = true
    }
    return {
      ...camera,
      department: camera.department || logisticsCamera.department,
      functions,
      logisticsOnline: logisticsCamera.online,
      logisticsMemberships: logisticsCamera.memberships,
    }
  })

  for (const camera of logisticsByCameraId.values()) {
    merged.push({
      id: camera.shm_name || `camera_${camera.camera_id}`,
      camera_id: camera.camera_id,
      name: camera.name,
      shm_name: camera.shm_name || `camera_${camera.camera_id}`,
      enabled: camera.enabled,
      department: camera.department,
      functions: Object.fromEntries(
        camera.memberships.map((membership) => [membership.feature_name, true]),
      ),
      inventoryOnly: true,
      logisticsOnline: camera.online,
      logisticsMemberships: camera.memberships,
    })
  }
  return merged
}

/**
 * 功能：读取或查询 `getLoadedAiVisionFeatureCounts` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameras`（CameraInventoryItem[]）：`cameras` 对应的业务输入值
 *   - `loaded`（boolean）：`loaded` 对应的业务输入值
 * 返回：FeatureCameraCounts | undefined；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`reduce`、`filter`、`hasFeature`、`FeatureCameraCounts`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function getLoadedAiVisionFeatureCounts(
  cameras: CameraInventoryItem[],
  loaded: boolean,
): FeatureCameraCounts | undefined {
  if (!loaded) return undefined
  return AI_VISION_FEATURES.reduce<FeatureCameraCounts>((counts, feature) => {
    const featureCameras = cameras.filter((camera) => hasFeature(camera, feature))
    counts[feature] = {
      cameraCount: featureCameras.length,
      enabledCameraCount: featureCameras.filter((camera) => camera.enabled).length,
    }
    return counts
  }, {})
}

/**
 * 功能：读取或查询 `getCameraInventorySummary` 对应的摄像头逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `cameras`（CameraInventoryItem[]）：`cameras` 对应的业务输入值
 *   - `runningCameras`（string[] | undefined）：`runningCameras` 对应的业务输入值
 *   - `fallbackOnlineCount`（未显式标注）：`fallbackOnlineCount` 对应的数量或大小；声明包含默认值 `0`
 * 返回：CameraInventorySummary；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/sections/HomeSection.tsx` 的 `HomeSection` 调用本符号
 *   - 内部调用：`isArray`、`filter`、`String`、`includes`、`min`、`max`、`Number`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
export function getCameraInventorySummary(
  cameras: CameraInventoryItem[],
  runningCameras: string[] | undefined,
  fallbackOnlineCount = 0,
): CameraInventorySummary {
  const cameraTotal = cameras.length
  const cameraOnline = Array.isArray(runningCameras)
    ? cameras.filter((camera) => {
      const key = String(camera.shm_name || camera.id || camera.camera_id || '')
      return runningCameras.includes(key) || camera.logisticsOnline === true
    }).length
    : Math.max(
      cameras.filter((camera) => camera.logisticsOnline === true).length,
      Math.min(cameraTotal, Math.max(0, Number(fallbackOnlineCount) || 0)),
    )

  return {
    cameraTotal,
    cameraOnline,
    cameraOffline: Math.max(0, cameraTotal - cameraOnline),
  }
}
