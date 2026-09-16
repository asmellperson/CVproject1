import type { DepartmentId } from '@/auth/permissions'
import type { AiVisionCamera } from '@/lib/aivision'
import type {
  LogisticsCameraInventoryItem,
  LogisticsCameraInventoryMembership,
} from '@/components/logistics_single_person/types'

export type FeatureCameraCounts = Record<string, {
  cameraCount: number
  enabledCameraCount: number
  onlineCameraCount?: number
}>

type CameraInventoryItem = {
  id?: string
  shm_name?: string
  camera_id?: number
  enabled: boolean
  department?: DepartmentId | null
  functions: Record<string, boolean>
  logisticsOnline?: boolean
  runtimeOnline?: boolean
}

export type OverviewAiVisionCamera = Omit<AiVisionCamera, 'sort_order'> & {
  inventoryOnly?: boolean
  logisticsOnline?: boolean
  runtimeOnline?: boolean
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
  'recognize_face',
  'detect_human',
  'detect_logistics_single_person',
  'detect_phone',
]

function hasFeature(camera: CameraInventoryItem, feature: string) {
  return Boolean(camera.functions[feature])
}

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
    const functions = { ...camera.functions }
    for (const membership of logisticsCamera.memberships) {
      functions[membership.feature_name] = true
    }
    return {
      ...camera,
      department: camera.department,
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

export function getLoadedAiVisionFeatureCounts(
  cameras: CameraInventoryItem[],
  loaded: boolean,
  department: DepartmentId,
): FeatureCameraCounts | undefined {
  if (!loaded) return undefined
  return AI_VISION_FEATURES.reduce<FeatureCameraCounts>((counts, feature) => {
    const featureCameras = cameras.filter((camera) => hasFeature(camera, feature) && camera.department === department)
    counts[feature] = {
      cameraCount: featureCameras.length,
      enabledCameraCount: featureCameras.filter((camera) => camera.enabled).length,
      onlineCameraCount: featureCameras.filter((camera) => camera.enabled && (
        feature === 'detect_logistics_single_person' ? camera.logisticsOnline === true : camera.runtimeOnline === true
      )).length,
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
