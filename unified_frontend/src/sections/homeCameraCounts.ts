// 文件说明：实现摄像头的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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
      return runningCameras.includes(key)
    }).length
    : Math.min(cameraTotal, Math.max(0, Number(fallbackOnlineCount) || 0))

  return {
    cameraTotal,
    cameraOnline,
    cameraOffline: Math.max(0, cameraTotal - cameraOnline),
  }
}
