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
  'detect_logistics_single_person',
  'detect_logistics_single_person_electronics_electrician',
  'detect_logistics_single_person_electrical_components',
  'detect_logistics_single_person_precious_metal_recycling',
  'detect_phone',
]

function hasFeature(camera: CameraInventoryItem, feature: string) {
  return Array.isArray(camera.functions)
    ? camera.functions.includes(feature)
    : Boolean(camera.functions?.[feature])
}

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
