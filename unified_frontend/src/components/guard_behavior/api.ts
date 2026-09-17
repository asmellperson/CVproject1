import type { DepartmentId } from '@/auth/permissions'
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUrl } from '@/lib/api'
import type { AlarmPolicy, AlarmPolicyValues, CameraRoi, GuardAlarmType, GuardMember, GuardSite, SiteCreate, SitePolicy, SitePolicyValues, SiteStatus, SiteUpdate, VehicleRoiPoint } from './types'

const sitesPath = '/guard-behavior/sites'
const sitePath = (id: number) => `${sitesPath}/${id}`
export const getSites = (department: DepartmentId, signal?: AbortSignal) =>
  apiGet<GuardSite[]>(`${sitesPath}?${new URLSearchParams({ department })}`, { signal })
export const getSite = (id: number, signal?: AbortSignal) => apiGet<GuardSite>(sitePath(id), { signal })
export const createSite = (value: SiteCreate) => apiPost<GuardSite>(sitesPath, value)
export const updateSite = (id: number, value: SiteUpdate) => apiPatch<GuardSite>(sitePath(id), value)
export const deleteSite = (id: number) => apiDelete<{ success: boolean }>(sitePath(id))
export const getMembers = (id: number, signal?: AbortSignal) => apiGet<GuardMember[]>(`${sitePath(id)}/cameras`, { signal })
export const addCamera = (id: number, cameraId: number) => apiPost<GuardMember>(`${sitePath(id)}/cameras`, { camera_id: cameraId })
export const removeCamera = (id: number, cameraId: number) => apiDelete<{ success: boolean }>(`${sitePath(id)}/cameras/${cameraId}`)
export const setCameraEnabled = (id: number, cameraId: number, enabled: boolean) => apiPut<GuardMember>(`${sitePath(id)}/cameras/${cameraId}/enabled`, { enabled })
export const reorderCameras = (id: number, cameraIds: number[]) => apiPut<{ success: boolean }>(`${sitePath(id)}/cameras/order`, { camera_ids: cameraIds })
export const getPolicy = (id: number, signal?: AbortSignal) => apiGet<SitePolicy>(`${sitePath(id)}/policy`, { signal })
export const updatePolicy = (id: number, value: Partial<SitePolicyValues>) => apiPatch<SitePolicy>(`${sitePath(id)}/policy`, value)
export const getRoi = (id: number, cameraId: number, signal?: AbortSignal) => apiGet<CameraRoi>(`${sitePath(id)}/cameras/${cameraId}/roi`, { signal })
export const updateRoi = (id: number, cameraId: number, roi: VehicleRoiPoint[]) => apiPut<CameraRoi>(`${sitePath(id)}/cameras/${cameraId}/roi`, { vehicle_roi_pos: roi })
export const getAlarmPolicies = (id: number, signal?: AbortSignal) => apiGet<AlarmPolicy[]>(`${sitePath(id)}/alarm-policies`, { signal })
export const updateAlarmPolicy = (id: number, type: GuardAlarmType, value: Partial<AlarmPolicyValues>) => apiPatch<AlarmPolicy>(`${sitePath(id)}/alarm-policies/${type}`, value)
export const getSiteStatus = (id: number, signal?: AbortSignal) => apiGet<SiteStatus>(`${sitePath(id)}/status`, { signal })
export const siteFrameUrl = (id: number) => apiUrl(`${sitePath(id)}/frame.jpg`)
