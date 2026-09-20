import type { DepartmentId } from '../auth/permissions'
import type { AiVisionCamera } from './aivision'

export const EMPTY_FEATURE_CAMERA_MESSAGE = '当前事业部尚未启用该检测功能的摄像头'

export function getEnabledFeatureCameras(cameras: AiVisionCamera[], feature: string, department: DepartmentId) {
  return cameras.filter((camera) => camera.department === department && camera.functions[feature] === true)
    .sort((a, b) => a.feature_sort_orders[feature] - b.feature_sort_orders[feature] || a.camera_id - b.camera_id)
}

export function selectFeatureCamera(cameras: AiVisionCamera[], feature: string, department: DepartmentId, preferred: string) {
  const enabled = getEnabledFeatureCameras(cameras, feature, department)
  if (enabled.some((camera) => camera.shm_name === preferred)) return preferred
  return enabled[0]?.shm_name || ''
}
