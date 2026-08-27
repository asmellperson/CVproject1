import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Activity,
  Bell,
  Camera,
  CircleDotDashed,
  Pencil,
  Plus,
  ScanFace,
  Server,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { OverviewMascot } from '@/components/OverviewMascot'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { useAuth } from '@/auth/useAuth'
import {
  filterHomeModulesByPermission,
  getAccessibleAlarmEventTypes,
  getUserDepartment,
  type Department,
} from '@/auth/permissions'
import {
  createGuardRoomSiteCamera,
  getAlarms,
  getGuardRoomSites,
  type AlarmEvent,
  type PlatformServiceStatus,
  type PlatformStatus,
} from '@/lib/api'
import { getRecognitionAbilityText, getServiceStatusText } from './HomeSection.status'
import {
  createAiVisionCamera,
  deleteAiVisionCamera,
  getAiVisionCameraKey,
  getAiVisionCameras,
  getAiVisionExceptionAlertSettings,
  saveAiVisionExceptionAlertSettings,
  updateAiVisionCamera,
  type AiVisionCamera,
} from '@/lib/aivision'
import {
  createSecurityVlmCamera,
  getSecurityVlmCameras,
  SECURITY_VLM_DEPARTMENTS,
  type SecurityVlmCamera,
  type SecurityVlmDepartment,
} from '@/lib/security-vlm'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '@/lib/camera-events'
import type { GuardRoomCamera, GuardRoomSite } from '@/types'
import { getCameraInventorySummary, getLoadedAiVisionFeatureCounts, type FeatureCameraCounts } from './homeCameraCounts'

interface HomeSectionProps {
  onNavigate: (page: string) => void
  platformStatus: PlatformStatus | null
}

const moduleEntries = [
  {
    id: 'security-vlm-general-electric',
    title: '安检流程规范检测入口',
  },
  {
    id: 'security-vlm-electronics-electrician',
    title: '安检流程规范检测入口',
  },
  {
    id: 'security-vlm-electrical-components',
    title: '安检流程规范检测入口',
  },
  {
    id: 'security-vlm-precious-metal-recycling',
    title: '安检流程规范检测入口',
  },
  {
    id: 'guard-behavior-general-electric',
    title: '保安行为规范检测入口',
  },
  {
    id: 'guard-behavior-electronics-electrician',
    title: '保安行为规范检测入口',
  },
  {
    id: 'intrusion-detection',
    title: '区域入侵检测入口',
  },
  {
    id: 'door-detection',
    title: '大门开关检测入口',
  },
  {
    id: 'face-detection',
    title: '人脸检测入口',
  },
  {
    id: 'human-detection',
    title: '人员逗留检测入口',
  },
  {
    id: 'haoda-human-detection',
    title: '人体逗留检测入口（皓达公司）',
  },
  {
    id: 'logistics-single-person-detection',
    title: '物流通道单人检测入口',
  },
  {
    id: 'logistics-single-person-electronics-electrician-detection',
    title: '物流通道单人检测入口（电子电工）',
  },
  {
    id: 'logistics-single-person-electrical-components-detection',
    title: '物流通道单人检测入口（电气部件）',
  },
  {
    id: 'logistics-single-person-precious-metal-recycling-detection',
    title: '物流通道单人检测入口（贵金属回收）',
  },
  {
    id: 'phone-detection',
    title: '手机使用检测入口',
  },
]

type OverviewState = {
  todayAlarms: number
  pendingAlarms: number
  recentAlarms: AlarmEvent[]
}

type AlarmSeverity = 'critical' | 'warning' | 'normal'

type CameraSource = 'aivision' | 'guard_room' | 'security_vlm'

type SecurityCameraInventoryItem = {
  department: SecurityVlmDepartment
  camera: SecurityVlmCamera
}

type PlatformCameraInventoryItem = {
  key: string
  source: CameraSource
  name: string
  identifier: string
  department?: string | null
  detail?: string
  featureLabels: string[]
  pageId?: string
  aiVisionCamera?: AiVisionCamera
  guardRoomCamera?: GuardRoomCamera
  securityVlmCamera?: SecurityVlmCamera
}

const departmentOptions: Array<{ value: Exclude<Department, 'all'>; label: string }> = [
  { value: 'general_electric', label: '通用电气事业部' },
  { value: 'research_institute', label: '福达新材院' },
  { value: 'electronics_electrician', label: '电子电工事业部' },
  { value: 'electrical_components', label: '电气部件事业部' },
  { value: 'precious_metal_recycling', label: '贵金属回收事业部' },
  { value: 'haoda_company', label: '皓达公司' },
]

const cameraSourceOptions: Array<{ value: CameraSource; label: string }> = [
  { value: 'aivision', label: 'AiVision 通用检测' },
  { value: 'guard_room', label: '保安行为规范检测' },
  { value: 'security_vlm', label: '安检流程规范检测' },
]

const cameraSourceDepartments: Record<CameraSource, Array<Exclude<Department, 'all'>>> = {
  aivision: departmentOptions.map((item) => item.value),
  guard_room: ['general_electric', 'electronics_electrician'],
  security_vlm: [...SECURITY_VLM_DEPARTMENTS],
}

const securityPageByDepartment: Record<SecurityVlmDepartment, string> = {
  general_electric: 'security-vlm-general-electric',
  electronics_electrician: 'security-vlm-electronics-electrician',
  electrical_components: 'security-vlm-electrical-components',
  precious_metal_recycling: 'security-vlm-precious-metal-recycling',
}

const guardPageByDepartment: Partial<Record<Department, string>> = {
  general_electric: 'guard-behavior-general-electric',
  electronics_electrician: 'guard-behavior-electronics-electrician',
}

type ServiceKey = keyof PlatformStatus['services']

type ModuleStatusSource = {
  serviceKey: ServiceKey
  featureKey?: string
}

const moduleStatusSources: Record<string, ModuleStatusSource> = {
  'security-vlm-general-electric': { serviceKey: 'security_vlm' },
  'security-vlm-electronics-electrician': { serviceKey: 'security_vlm' },
  'security-vlm-electrical-components': { serviceKey: 'security_vlm' },
  'security-vlm-precious-metal-recycling': { serviceKey: 'security_vlm' },
  'guard-behavior': { serviceKey: 'guard_room' },
  'guard-behavior-general-electric': { serviceKey: 'guard_room' },
  'guard-behavior-electronics-electrician': { serviceKey: 'guard_room' },
  'intrusion-detection': { serviceKey: 'aivision', featureKey: 'blocks' },
  'door-detection': { serviceKey: 'aivision', featureKey: 'detect_door' },
  'face-detection': { serviceKey: 'aivision', featureKey: 'detect_face' },
  'human-detection': { serviceKey: 'aivision', featureKey: 'detect_human' },
  'haoda-human-detection': { serviceKey: 'aivision', featureKey: 'detect_human_haoda' },
  'logistics-single-person-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person' },
  'logistics-single-person-electronics-electrician-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person_electronics_electrician' },
  'logistics-single-person-electrical-components-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person_electrical_components' },
  'logistics-single-person-precious-metal-recycling-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person_precious_metal_recycling' },
  'phone-detection': { serviceKey: 'aivision', featureKey: 'detect_phone' },
}

type ModuleStatusCard = (typeof moduleEntries)[number] & ModuleStatusSource

const aiVisionFeatureLabels: Record<string, string> = {
  blocks: '区域入侵',
  detect_door: '大门开关',
  detect_face: '人脸检测',
  detect_human: '人员逗留',
  detect_human_haoda: '人体逗留（皓达公司）',
  detect_logistics_single_person: '物流单人',
  detect_logistics_single_person_electronics_electrician: '物流单人（电子电工）',
  detect_logistics_single_person_electrical_components: '物流单人（电气部件）',
  detect_logistics_single_person_precious_metal_recycling: '物流单人（贵金属回收）',
  detect_phone: '手机使用',
}

const defaultOverview: OverviewState = {
  todayAlarms: 0,
  pendingAlarms: 0,
  recentAlarms: [],
}

const criticalAlarmTypes = new Set(['blocks', 'guard_absent'])
const warningAlarmTypes = new Set([
  'detect_door',
  'detect_phone',
  'guard_phone_use',
  'guard_prone_sleep',
  'security_vlm_non_compliant',
  'security_vlm_error',
])

function isToday(value?: string) {
  if (!value) return false
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false
  const now = new Date()
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
}

function formatLatestTime(value?: string) {
  if (!value) return '暂无'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无'
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getAlarmSeverity(eventType: string): AlarmSeverity {
  if (criticalAlarmTypes.has(eventType)) return 'critical'
  if (warningAlarmTypes.has(eventType)) return 'warning'
  return 'normal'
}

function getAlarmLocation(alarm: AlarmEvent) {
  return alarm.camera_name || alarm.site_name || alarm.camera_no || '未知位置'
}

function departmentLabel(department: ReturnType<typeof getUserDepartment>) {
  if (department === 'general_electric') return '通用电气视图'
  if (department === 'electronics_electrician') return '电子电工视图'
  if (department === 'electrical_components') return '电气部件视图'
  if (department === 'precious_metal_recycling') return '贵金属回收视图'
  if (department === 'haoda_company') return '皓达公司视图'
  if (department === 'research_institute') return '福达新材院视图'
  if (department === 'all') return '全局视图'
  return '权限视图'
}

function cameraDepartmentLabel(department?: string | null) {
  return departmentOptions.find((item) => item.value === department)?.label || '未分配事业部'
}

function cameraSourceLabel(source: CameraSource) {
  return cameraSourceOptions.find((item) => item.value === source)?.label || source
}

function getRunningConsumers(service?: PlatformServiceStatus) {
  return Array.isArray(service?.running_consumers) ? service.running_consumers.map(String) : []
}

function getAiVisionCameraFeatureLabels(camera: AiVisionCamera) {
  const functions = camera.functions
  const enabledFeatures = Array.isArray(functions)
    ? functions
    : Object.entries(functions || {})
      .filter(([, enabled]) => Boolean(enabled))
      .map(([feature]) => feature)
  return enabledFeatures.map((feature) => aiVisionFeatureLabels[feature] || feature)
}

function makeAiVisionShmName(alias: string) {
  const base = alias
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return `${base || 'camera'}_${Date.now().toString(36)}`
}

function getFeatureStatus(service?: PlatformServiceStatus, featureKey?: string) {
  if (!featureKey) return undefined
  return service?.feature_status?.[featureKey]
}

function getLocalFeatureCount(featureCounts: FeatureCameraCounts | undefined, featureKey?: string) {
  if (!featureKey) return undefined
  return featureCounts?.[featureKey]?.cameraCount
}

function getCapabilityCameraCount(service?: PlatformServiceStatus, featureKey?: string, featureCounts?: FeatureCameraCounts) {
  const localCount = getLocalFeatureCount(featureCounts, featureKey)
  if (typeof localCount === 'number') return localCount
  const featureStatus = getFeatureStatus(service, featureKey)
  return Number(featureStatus?.camera_count ?? service?.camera_count ?? 0)
}

function getCapabilityOnlineCameraCount(service?: PlatformServiceStatus, featureKey?: string, featureCounts?: FeatureCameraCounts) {
  const localCount = getLocalFeatureCount(featureCounts, featureKey)
  const featureStatus = getFeatureStatus(service, featureKey)
  if (typeof localCount === 'number') {
    return Math.min(localCount, Number(featureStatus?.online_camera_count ?? service?.online_camera_count ?? 0))
  }
  return Number(featureStatus?.online_camera_count ?? service?.online_camera_count ?? 0)
}

function isCapabilityRunning(service?: PlatformServiceStatus, featureKey?: string, featureCounts?: FeatureCameraCounts) {
  if (!service?.online || !service.running) return false
  if (!featureKey) return true
  const localCount = getLocalFeatureCount(featureCounts, featureKey)
  if (typeof localCount === 'number' && localCount <= 0) return false
  const featureStatus = getFeatureStatus(service, featureKey)
  if (featureStatus && Number(featureStatus.camera_count || 0) <= 0) return false
  const runningConsumers = getRunningConsumers(service)
  if (!runningConsumers.length) return true
  return runningConsumers.includes(featureKey)
}

function isCapabilityModelReady(service?: PlatformServiceStatus, featureKey?: string, featureCounts?: FeatureCameraCounts) {
  if (!featureKey) return Boolean(service?.model_status?.loaded)
  const localCount = getLocalFeatureCount(featureCounts, featureKey)
  if (typeof localCount === 'number' && localCount <= 0) return false
  const featureStatus = getFeatureStatus(service, featureKey)
  if (featureStatus && Number(featureStatus.camera_count || 0) <= 0) return false
  const runningConsumers = getRunningConsumers(service)
  if (!runningConsumers.length) return Boolean(service?.model_status?.loaded || service?.running)
  return runningConsumers.includes(featureKey)
}

function getStatusLevelForCards(cards: ModuleStatusCard[], platformStatus: PlatformStatus | null, featureCounts?: FeatureCameraCounts) {
  if (!cards.length || !platformStatus) return 'down'
  const services = cards.map((card) => platformStatus.services[card.serviceKey])
  const onlineCount = services.filter((service) => service?.online).length
  const runningCount = cards.filter((card) => isCapabilityRunning(platformStatus.services[card.serviceKey], card.featureKey, featureCounts)).length
  if (onlineCount === cards.length && runningCount === cards.length) return 'healthy'
  if (onlineCount > 0) return 'degraded'
  return 'down'
}

function getVisibleStatusCards(visibleEntries: typeof moduleEntries): ModuleStatusCard[] {
  return visibleEntries.flatMap((entry) => {
    const source = moduleStatusSources[entry.id]
    return source ? [{ ...entry, ...source }] : []
  })
}

function getScopedStatusSummary(cards: ModuleStatusCard[], platformStatus: PlatformStatus | null, featureCounts?: FeatureCameraCounts) {
  if (!platformStatus) {
    return {
      capabilityTotal: cards.length,
      capabilityOnline: 0,
      capabilityRunning: 0,
      cameraTotal: 0,
      cameraOnline: 0,
      cameraOffline: 0,
    }
  }

  const serviceCards = cards.filter((card) => !card.featureKey)
  const featureCards = cards.filter((card) => card.featureKey)
  const uniqueServices = Array.from(new Set(serviceCards.map((card) => card.serviceKey)))
  const serviceCameraTotal = uniqueServices.reduce((total, serviceKey) => {
    return total + Number(platformStatus.services[serviceKey]?.camera_count || 0)
  }, 0)
  const serviceCameraOnline = uniqueServices.reduce((total, serviceKey) => {
    return total + Number(platformStatus.services[serviceKey]?.online_camera_count || 0)
  }, 0)
  const featureCameraTotal = featureCards.reduce((total, card) => {
    return total + getCapabilityCameraCount(platformStatus.services[card.serviceKey], card.featureKey, featureCounts)
  }, 0)
  const featureCameraOnline = featureCards.reduce((total, card) => {
    return total + getCapabilityOnlineCameraCount(platformStatus.services[card.serviceKey], card.featureKey, featureCounts)
  }, 0)
  const cameraTotal = serviceCameraTotal + featureCameraTotal
  const cameraOnline = serviceCameraOnline + featureCameraOnline

  return {
    capabilityTotal: cards.length,
    capabilityOnline: cards.filter((card) => platformStatus.services[card.serviceKey]?.online).length,
    capabilityRunning: cards.filter((card) => isCapabilityRunning(platformStatus.services[card.serviceKey], card.featureKey, featureCounts)).length,
    cameraTotal,
    cameraOnline,
    cameraOffline: Math.max(0, cameraTotal - cameraOnline),
  }
}

export function HomeSection({ onNavigate, platformStatus }: HomeSectionProps) {
  const { user, isAdmin } = useAuth()
  const visibleModuleEntries = useMemo(() => filterHomeModulesByPermission(user, moduleEntries), [user])
  const visibleStatusCards = useMemo(() => getVisibleStatusCards(visibleModuleEntries), [visibleModuleEntries])
  const [overview, setOverview] = useState<OverviewState>(defaultOverview)
  const [aiVisionCameras, setAiVisionCameras] = useState<AiVisionCamera[]>([])
  const [aiVisionCamerasLoaded, setAiVisionCamerasLoaded] = useState(false)
  const [guardRoomSites, setGuardRoomSites] = useState<GuardRoomSite[]>([])
  const [securityVlmCameras, setSecurityVlmCameras] = useState<SecurityCameraInventoryItem[]>([])
  const [cameraInventoryLoaded, setCameraInventoryLoaded] = useState(false)
  const [cameraInventoryPartial, setCameraInventoryPartial] = useState(false)
  const [exceptionWechatEnabled, setExceptionWechatEnabled] = useState(false)
  const [exceptionWechatUser, setExceptionWechatUser] = useState('')
  const [exceptionRepeatIntervalMinutes, setExceptionRepeatIntervalMinutes] = useState(60)
  const [exceptionSettingsLoading, setExceptionSettingsLoading] = useState(false)
  const [exceptionSettingsSaving, setExceptionSettingsSaving] = useState(false)
  const [exceptionSettingsMessage, setExceptionSettingsMessage] = useState('')
  const [exceptionSettingsError, setExceptionSettingsError] = useState('')
  const [cameraDialogOpen, setCameraDialogOpen] = useState(false)
  const [cameraDialogMode, setCameraDialogMode] = useState<'create' | 'edit'>('create')
  const [cameraToEdit, setCameraToEdit] = useState<AiVisionCamera | null>(null)
  const [cameraSource, setCameraSource] = useState<CameraSource>('aivision')
  const [cameraDepartment, setCameraDepartment] = useState<Exclude<Department, 'all'>>('general_electric')
  const [cameraGuardSiteId, setCameraGuardSiteId] = useState('')
  const [cameraName, setCameraName] = useState('')
  const [cameraUrl, setCameraUrl] = useState('')
  const [cameraFormError, setCameraFormError] = useState('')
  const [cameraActionKey, setCameraActionKey] = useState('')
  const [cameraToDelete, setCameraToDelete] = useState<AiVisionCamera | null>(null)
  const [cameraDeleteError, setCameraDeleteError] = useState('')
  const department = getUserDepartment(user)
  const visiblePageIds = useMemo(
    () => new Set(visibleModuleEntries.map((entry) => entry.id)),
    [visibleModuleEntries],
  )
  const visibleSecurityDepartments = useMemo(
    () => SECURITY_VLM_DEPARTMENTS.filter((item) => visiblePageIds.has(securityPageByDepartment[item])),
    [visiblePageIds],
  )
  const guardRoomVisible = useMemo(
    () => Object.values(guardPageByDepartment).some((pageId) => pageId && visiblePageIds.has(pageId)),
    [visiblePageIds],
  )
  const accessibleAlarmEventTypes = useMemo(() => getAccessibleAlarmEventTypes(user), [user])
  const aiVisionFeatureCounts = useMemo(
    () => getLoadedAiVisionFeatureCounts(aiVisionCameras, aiVisionCamerasLoaded),
    [aiVisionCameras, aiVisionCamerasLoaded],
  )
  const scopedStatusSummary = useMemo(() => getScopedStatusSummary(visibleStatusCards, platformStatus, aiVisionFeatureCounts), [aiVisionFeatureCounts, platformStatus, visibleStatusCards])
  const platformCameras = useMemo<PlatformCameraInventoryItem[]>(() => {
    const aiVisionItems = aiVisionCameras.map((camera) => ({
      key: `aivision:${getAiVisionCameraKey(camera)}`,
      source: 'aivision' as const,
      name: camera.name,
      identifier: camera.shm_name,
      department: camera.department,
      featureLabels: getAiVisionCameraFeatureLabels(camera),
      aiVisionCamera: camera,
    }))
    const guardItems = guardRoomSites.flatMap((site) => site.cameras.map((camera) => ({
      key: `guard_room:${site.id}:${camera.id}`,
      source: 'guard_room' as const,
      name: camera.name,
      identifier: `保安室：${site.name}`,
      department: site.department,
      detail: camera.enabled ? '已启用' : '已停用',
      featureLabels: ['保安行为规范检测'],
      pageId: guardPageByDepartment[site.department as Department],
      guardRoomCamera: camera,
    })))
    const securityItems = securityVlmCameras.map(({ department: itemDepartment, camera }) => ({
      key: `security_vlm:${itemDepartment}:${camera.camera_id}`,
      source: 'security_vlm' as const,
      name: camera.name,
      identifier: camera.camera_id,
      department: itemDepartment,
      detail: camera.running ? '正在运行' : '未运行',
      featureLabels: ['安检流程规范检测'],
      pageId: securityPageByDepartment[itemDepartment],
      securityVlmCamera: camera,
    }))
    return [...aiVisionItems, ...guardItems, ...securityItems]
  }, [aiVisionCameras, guardRoomSites, securityVlmCameras])
  const cameraInventorySummary = useMemo(() => {
    const aiVisionSummary = getCameraInventorySummary(
      aiVisionCameras,
      platformStatus?.services.aivision.running_cameras,
      platformStatus?.services.aivision.online_camera_count,
    )
    const guardCameraTotal = guardRoomSites.reduce((total, site) => total + site.cameras.length, 0)
    const guardCameraOnline = Math.min(
      guardCameraTotal,
      Math.max(0, Number(platformStatus?.services.guard_room.online_camera_count) || 0),
    )
    const securityCameraOnline = securityVlmCameras.filter(({ camera }) => camera.running).length
    const cameraTotal = aiVisionSummary.cameraTotal + guardCameraTotal + securityVlmCameras.length
    const cameraOnline = aiVisionSummary.cameraOnline + guardCameraOnline + securityCameraOnline
    return {
      cameraTotal,
      cameraOnline,
      cameraOffline: Math.max(0, cameraTotal - cameraOnline),
    }
  }, [aiVisionCameras, guardRoomSites, platformStatus, securityVlmCameras])
  const cameraStatusReady = cameraInventoryLoaded && platformStatus !== null
  const scopedStatusLevel = useMemo(() => getStatusLevelForCards(visibleStatusCards, platformStatus, aiVisionFeatureCounts), [aiVisionFeatureCounts, platformStatus, visibleStatusCards])

  useEffect(() => {
    if (!isAdmin) {
      return
    }

    setExceptionSettingsLoading(true)
    getAiVisionExceptionAlertSettings()
      .then((settings) => {
        setExceptionWechatEnabled(Boolean(settings.wechat_enable))
        setExceptionWechatUser(settings.wechat_user || '')
        setExceptionRepeatIntervalMinutes(settings.repeat_interval_minutes || 60)
      })
      .catch((error) => {
        setExceptionSettingsError(`读取全局异常推送配置失败：${error instanceof Error ? error.message : String(error)}`)
      })
      .finally(() => setExceptionSettingsLoading(false))
  }, [isAdmin])

  const handleSaveExceptionSettings = async () => {
    if (exceptionWechatEnabled && !exceptionWechatUser.trim()) {
      setExceptionSettingsError('启用全局异常推送时，接收人不能为空。')
      setExceptionSettingsMessage('')
      return
    }
    if (exceptionRepeatIntervalMinutes < 5 || exceptionRepeatIntervalMinutes > 1440) {
      setExceptionSettingsError('重复提醒间隔必须在 5 到 1440 分钟之间。')
      setExceptionSettingsMessage('')
      return
    }

    setExceptionSettingsSaving(true)
    setExceptionSettingsError('')
    setExceptionSettingsMessage('')
    try {
      const next = await saveAiVisionExceptionAlertSettings({
        wechat_enable: exceptionWechatEnabled,
        wechat_user: exceptionWechatUser.trim(),
        repeat_interval_minutes: exceptionRepeatIntervalMinutes,
      })
      setExceptionWechatEnabled(Boolean(next.wechat_enable))
      setExceptionWechatUser(next.wechat_user || '')
      setExceptionRepeatIntervalMinutes(next.repeat_interval_minutes || 60)
      setExceptionSettingsMessage('全局异常推送配置已保存。')
    } catch (error) {
      setExceptionSettingsError(`保存全局异常推送配置失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setExceptionSettingsSaving(false)
    }
  }

  const loadCameraInventory = useCallback(async () => {
    const guardRequest = guardRoomVisible
      ? getGuardRoomSites(isAdmin || department === 'all' ? undefined : department)
      : Promise.resolve([])
    const securityRequest = Promise.allSettled(
      visibleSecurityDepartments.map(async (itemDepartment) => ({
        department: itemDepartment,
        cameras: (await getSecurityVlmCameras(itemDepartment)).cameras,
      })),
    )
    const [[aiVisionResult, guardResult], securityResults] = await Promise.all([
      Promise.allSettled([getAiVisionCameras(), guardRequest]),
      securityRequest,
    ])

    if (aiVisionResult.status === 'fulfilled') {
      setAiVisionCameras(aiVisionResult.value)
      setAiVisionCamerasLoaded(true)
    } else {
      setAiVisionCamerasLoaded(false)
    }
    if (guardResult.status === 'fulfilled') {
      setGuardRoomSites(guardResult.value)
    }
    setSecurityVlmCameras(securityResults.flatMap((result) => (
      result.status === 'fulfilled'
        ? result.value.cameras.map((camera) => ({
          department: result.value.department,
          camera,
        }))
        : []
    )))
    setCameraInventoryPartial(
      aiVisionResult.status === 'rejected'
      || guardResult.status === 'rejected'
      || securityResults.some((result) => result.status === 'rejected'),
    )
    setCameraInventoryLoaded(true)
  }, [department, guardRoomVisible, isAdmin, visibleSecurityDepartments])

  const allowedCameraDepartments = cameraSourceDepartments[cameraSource]
  const guardSiteOptions = guardRoomSites.filter((site) => site.department === cameraDepartment)

  const resetCameraForm = () => {
    setCameraName('')
    setCameraUrl('')
    setCameraToEdit(null)
    setCameraFormError('')
  }

  const openCreateCameraDialog = () => {
    setCameraDialogMode('create')
    resetCameraForm()
    setCameraSource('aivision')
    setCameraDepartment(department && department !== 'all' ? department : 'general_electric')
    setCameraGuardSiteId('')
    setCameraDialogOpen(true)
  }

  const handleCameraSourceChange = (source: CameraSource) => {
    const departments = cameraSourceDepartments[source]
    const nextDepartment = departments.includes(cameraDepartment)
      ? cameraDepartment
      : departments[0]
    setCameraSource(source)
    setCameraDepartment(nextDepartment)
    setCameraGuardSiteId(
      source === 'guard_room'
        ? String(guardRoomSites.find((site) => site.department === nextDepartment)?.id || '')
        : '',
    )
    setCameraFormError('')
  }

  const handleCameraDepartmentChange = (nextDepartment: Exclude<Department, 'all'>) => {
    setCameraDepartment(nextDepartment)
    setCameraGuardSiteId(
      cameraSource === 'guard_room'
        ? String(guardRoomSites.find((site) => site.department === nextDepartment)?.id || '')
        : '',
    )
    setCameraFormError('')
  }

  const openEditCameraDialog = (camera: AiVisionCamera) => {
    setCameraDialogMode('edit')
    setCameraToEdit(camera)
    setCameraName(camera.name)
    setCameraUrl(camera.url || '')
    setCameraFormError('')
    setCameraDialogOpen(true)
  }

  const handleSaveCamera = async () => {
    if (!isAdmin) return
    const name = cameraName.trim()
    const url = cameraUrl.trim()
    if (!name || !url) {
      setCameraFormError('摄像头名称和 RTSP 地址都不能为空。')
      return
    }

    if (cameraDialogMode === 'create' && cameraSource === 'guard_room' && !cameraGuardSiteId) {
      setCameraFormError('请先选择保安室；如暂无保安室，请先在保安行为规范配置页创建。')
      return
    }

    const generatedShmName = makeAiVisionShmName(name)
    const actionKey = cameraDialogMode === 'edit' && cameraToEdit
      ? getAiVisionCameraKey(cameraToEdit)
      : `${cameraSource}:${generatedShmName}`
    setCameraActionKey(actionKey)
    setCameraFormError('')
    try {
      if (cameraDialogMode === 'edit' && cameraToEdit) {
        await updateAiVisionCamera(getAiVisionCameraKey(cameraToEdit), { name, url })
      } else if (cameraSource === 'aivision') {
        await createAiVisionCamera({
          name,
          url,
          shm_name: generatedShmName,
          enabled: true,
          department: cameraDepartment,
        })
      } else if (cameraSource === 'guard_room') {
        await createGuardRoomSiteCamera(Number(cameraGuardSiteId), {
          name,
          rtsp_url: url,
          enabled: true,
        })
      } else {
        await createSecurityVlmCamera(
          cameraDepartment as SecurityVlmDepartment,
          name,
          url,
        )
      }
      await loadCameraInventory()
      setCameraDialogOpen(false)
      resetCameraForm()
    } catch (error) {
      setCameraFormError(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraActionKey('')
    }
  }

  const handleDeleteCamera = async () => {
    if (!isAdmin || !cameraToDelete) return

    const cameraKey = getAiVisionCameraKey(cameraToDelete)
    setCameraActionKey(cameraKey)
    setCameraDeleteError('')
    try {
      await deleteAiVisionCamera(cameraKey)
      await loadCameraInventory()
      setCameraToDelete(null)
    } catch (error) {
      setCameraDeleteError(`删除失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraActionKey('')
    }
  }

  useEffect(() => {
    void loadCameraInventory()
    const refreshCameraInventory = () => {
      void loadCameraInventory()
    }
    const timer = window.setInterval(refreshCameraInventory, 10000)
    window.addEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refreshCameraInventory)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refreshCameraInventory)
    }
  }, [loadCameraInventory])

  useEffect(() => {
    let cancelled = false

    async function loadOverview() {
      const alarms = await getAlarms(100)

      if (cancelled) return
      const allowedAlarmTypes = accessibleAlarmEventTypes ? new Set(accessibleAlarmEventTypes) : null
      const alarmItems = alarms.filter((alarm) => !allowedAlarmTypes || allowedAlarmTypes.has(alarm.event_type))

      setOverview({
        todayAlarms: alarmItems.filter((alarm) => isToday(alarm.created_at)).length,
        pendingAlarms: alarmItems.filter((alarm) => (alarm.disposition_status || 'pending') === 'pending').length,
        recentAlarms: alarmItems.slice(0, 5),
      })
    }

    void loadOverview().catch(() => {
      if (!cancelled) {
        setOverview(defaultOverview)
      }
    })

    const timer = window.setInterval(() => {
      void loadOverview().catch(() => {
        if (!cancelled) setOverview(defaultOverview)
      })
    }, 10000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [accessibleAlarmEventTypes])

  return (
    <>
      <div className="relative -mx-3 -my-4 min-h-[calc(100dvh-64px)] overflow-hidden bg-[#f5f8fc] p-3 dark:bg-[#07111f] sm:-mx-4 sm:-my-5 sm:min-h-[calc(100vh-72px)] sm:p-4 lg:-mx-8 lg:-my-6 lg:p-8 2xl:-mx-10 2xl:p-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#f8fbff_0%,#eef4fb_48%,#f8fafc_100%)] dark:bg-[linear-gradient(180deg,#07111f_0%,#0b1626_48%,#07111f_100%)]" />
      <div aria-hidden className="pointer-events-none absolute inset-x-10 top-8 h-24 rounded-full bg-blue-200/20 blur-3xl dark:bg-blue-500/10" />

      <div className="relative z-[1] flex w-full min-w-0 flex-col gap-4 sm:gap-7">
        <section className="relative overflow-hidden rounded-[14px] border border-white/80 bg-slate-900 shadow-[0_22px_54px_rgba(15,44,92,0.16)] dark:border-slate-800 dark:shadow-[0_22px_54px_rgba(0,0,0,0.36)] sm:rounded-[18px]">
          <img src="/company-home-bg.jpg" alt="" className="absolute inset-0 h-full w-full object-cover object-center" />
          <div className="absolute inset-0 z-0 bg-[linear-gradient(90deg,rgba(232,242,255,0.96)_0%,rgba(222,236,255,0.78)_50%,rgba(218,235,255,0.16)_100%)] dark:bg-[linear-gradient(90deg,rgba(7,17,31,0.94)_0%,rgba(9,25,48,0.82)_45%,rgba(9,25,48,0.24)_100%)] sm:bg-[linear-gradient(90deg,rgba(232,242,255,0.94)_0%,rgba(222,236,255,0.66)_38%,rgba(218,235,255,0.08)_72%)] dark:sm:bg-[linear-gradient(90deg,rgba(7,17,31,0.92)_0%,rgba(9,25,48,0.72)_42%,rgba(9,25,48,0.16)_78%)]" />
          <div className="absolute inset-0 z-0 bg-[radial-gradient(circle_at_15%_20%,rgba(255,255,255,0.9),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.2),rgba(255,255,255,0))] dark:bg-[radial-gradient(circle_at_15%_20%,rgba(59,130,246,0.18),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.05),rgba(255,255,255,0))]" />
          <OverviewMascot />
          <div className="relative z-[3] flex min-h-[240px] items-center justify-center px-3 py-5 text-center sm:min-h-[280px] sm:px-10 sm:py-7 lg:px-14 2xl:min-h-[380px] 2xl:px-20 2xl:py-10">
            <div className="relative z-[3] flex -translate-y-3 flex-col items-center justify-center sm:-translate-y-4">
              <Badge className="mb-4 w-fit border border-blue-200 bg-white/78 px-3 py-1 text-sm font-semibold text-[#09265a] shadow-none hover:bg-white/78 dark:border-blue-900/70 dark:bg-slate-950/70 dark:text-blue-100 dark:hover:bg-slate-950/70">
                {departmentLabel(department)}
              </Badge>
              <h2 className="whitespace-nowrap text-[clamp(1rem,4.5vw,3rem)] font-black tracking-[0] text-[#061d45] drop-shadow-[0_10px_22px_rgba(255,255,255,0.65)] dark:text-white dark:drop-shadow-[0_10px_22px_rgba(0,0,0,0.55)] 2xl:text-6xl">
                福达 AI 视觉安全监管平台
              </h2>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]">
            <div className="p-5 sm:p-6">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cyan-600 text-white shadow-sm">
                  <Activity className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">平台汇总</h3>
                  <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">平台状态 30 秒 · 摄像头 10 秒刷新</p>
                </div>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <MiniStatusMetric label="能力在线" value={`${scopedStatusSummary.capabilityOnline}/${scopedStatusSummary.capabilityTotal}`} />
                <MiniStatusMetric label="正在检测" value={`${scopedStatusSummary.capabilityRunning}/${scopedStatusSummary.capabilityTotal}`} />
                <MiniStatusMetric label="摄像头在线" value={cameraStatusReady ? `${cameraInventorySummary.cameraOnline}/${cameraInventorySummary.cameraTotal}` : '加载中'} />
                <MiniStatusMetric
                  label="摄像头离线"
                  value={cameraStatusReady ? cameraInventorySummary.cameraOffline : '加载中'}
                  warn={cameraStatusReady && cameraInventorySummary.cameraOffline > 0}
                />
              </div>

              <div className="mt-5 flex h-[360px] flex-col overflow-hidden rounded-2xl border border-blue-100 bg-[#f8fbff] shadow-sm dark:border-slate-800 dark:bg-slate-950/30">
                <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-blue-100 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm font-black text-[#071d3d] dark:text-slate-100">
                      <Camera className="h-4 w-4 text-cyan-600" />
                      全部摄像头
                    </div>
                    <div className="mt-1 text-xs font-medium text-slate-500 dark:text-slate-400">
                      共 {platformCameras.length} 路；已汇总 AiVision、保安行为和安检流程摄像头。
                      {cameraInventoryPartial ? ' 部分来源暂不可用。' : ''}
                    </div>
                  </div>
                  {isAdmin ? (
                    <Button size="sm" className="gap-2" onClick={openCreateCameraDialog} disabled={Boolean(cameraActionKey)}>
                      <Plus className="h-4 w-4" />
                      新增摄像头
                    </Button>
                  ) : (
                    <Badge variant="outline" className="shrink-0 bg-white text-xs font-semibold text-slate-500 dark:bg-slate-900">
                      只读
                    </Badge>
                  )}
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto">
                  {platformCameras.length === 0 ? (
                    <div className="px-4 py-6 text-sm font-medium text-slate-500">暂无摄像头。</div>
                  ) : (
                    <div className="grid grid-cols-1 lg:grid-cols-2">
                      {platformCameras.map((camera) => (
                          <div
                            key={camera.key}
                            className="group relative border-b border-blue-100 bg-white px-4 py-3 outline-none transition-colors hover:bg-blue-50/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 dark:border-slate-800 dark:bg-slate-900/70 dark:hover:bg-slate-800/70 lg:border-r lg:even:border-r-0"
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-bold text-[#071d3d] dark:text-slate-100">{camera.name}</div>
                                <div className="mt-1 truncate text-xs font-medium text-slate-500">
                                  {cameraSourceLabel(camera.source)} · {cameraDepartmentLabel(camera.department)} · {camera.identifier}
                                  {camera.detail ? ` · ${camera.detail}` : ''}
                                </div>
                              </div>
                              {isAdmin && camera.aiVisionCamera ? (
                                <div className="flex shrink-0 items-center gap-2 opacity-100 transition-opacity duration-200 [@media(hover:hover)]:pointer-events-none [@media(hover:hover)]:opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="gap-1.5"
                                    onClick={() => openEditCameraDialog(camera.aiVisionCamera!)}
                                    disabled={Boolean(cameraActionKey)}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                    修改
                                  </Button>
                                  <Button
                                    variant="destructive"
                                    size="sm"
                                    className="gap-1.5"
                                    onClick={() => {
                                      setCameraToDelete(camera.aiVisionCamera!)
                                      setCameraDeleteError('')
                                    }}
                                    disabled={Boolean(cameraActionKey)}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                    删除
                                  </Button>
                                </div>
                              ) : camera.pageId ? (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="shrink-0 gap-1.5"
                                  onClick={() => onNavigate(camera.pageId!)}
                                >
                                  <ArrowRight className="h-3.5 w-3.5" />
                                  配置
                                </Button>
                              ) : null}
                            </div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {camera.featureLabels.length ? (
                                camera.featureLabels.map((label) => (
                                  <Badge key={label} variant="outline" className="bg-emerald-50 text-[11px] font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
                                    {label}
                                  </Badge>
                                ))
                              ) : (
                                <span className="text-xs font-medium text-slate-400">暂未加入检测功能</span>
                              )}
                            </div>
                          </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className={cn(
            'relative flex flex-col overflow-hidden rounded-[18px] border bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]',
            overview.recentAlarms.length ? 'border-amber-100 dark:border-amber-900/50' : 'border-emerald-100 dark:border-emerald-900/50',
          )}>
            <div className="relative flex h-full flex-col p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">最近异常</h3>
                  <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">
                    {overview.recentAlarms.length ? '最近 5 条可见报警事件' : '当前可见范围内暂无异常'}
                  </p>
                </div>
                <div className={cn(
                  'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl shadow-sm',
                  overview.recentAlarms.length ? 'bg-amber-50 text-amber-600 ring-1 ring-amber-100 dark:bg-amber-950/50 dark:ring-amber-900/70' : 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100 dark:bg-emerald-950/50 dark:ring-emerald-900/70',
                )}>
                  <AlertTriangle className="h-5 w-5" />
                </div>
              </div>

              {overview.recentAlarms.length ? (
                <div className="relative mt-5 flex-1">
                  <div aria-hidden className="absolute left-[5px] bottom-2 top-2 w-px bg-slate-200 dark:bg-slate-700" />
                  <div className="space-y-0">
                    {overview.recentAlarms.map((alarm) => {
                      const severity = getAlarmSeverity(alarm.event_type)
                      return (
                        <div key={alarm.id} className="relative pb-4 pl-7 last:pb-0">
                          <span
                            aria-hidden
                            className={cn(
                              'absolute left-0 top-1 h-3 w-3 rounded-full border-2 border-white shadow-sm dark:border-slate-900',
                              severity === 'critical' && 'bg-red-500',
                              severity === 'warning' && 'bg-amber-400',
                              severity === 'normal' && 'bg-slate-400',
                            )}
                          />
                          <span className="sr-only">{severity === 'critical' ? '严重报警' : severity === 'warning' ? '中等报警' : '普通报警'}</span>
                          <div className="text-[11px] font-medium text-slate-400 dark:text-slate-500">{formatLatestTime(alarm.created_at)}</div>
                          <div className="mt-0.5 truncate text-sm font-black text-[#071d3d] dark:text-slate-100">{alarm.event_label || alarm.event_type}</div>
                          <div className="mt-0.5 truncate text-xs font-medium text-slate-500 dark:text-slate-400">{getAlarmLocation(alarm)}</div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ) : (
                <div className="mt-5 flex-1 rounded-2xl border border-emerald-100 bg-emerald-50/70 p-5 dark:border-emerald-900/50 dark:bg-emerald-950/20">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_0_6px_rgba(16,185,129,0.14)]" />
                    <div className="text-sm font-semibold leading-6 text-emerald-700 dark:text-emerald-300">
                      今日暂无异常记录，当前总览处于平稳状态。
                    </div>
                  </div>
                </div>
              )}

              <button
                type="button"
                onClick={() => onNavigate('alarms')}
                className="mt-5 flex w-full items-center justify-between border-t border-slate-200 pt-4 text-sm font-bold text-[#09265a] transition hover:text-blue-600 dark:border-slate-800 dark:text-blue-300 dark:hover:text-blue-200"
              >
                <span>查看全部报警</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92">
            <div className="p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_14px_26px_rgba(0,27,67,0.22)] dark:bg-blue-600">
                    <Server className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-xl font-black tracking-[0] text-[#071d3d] dark:text-slate-100">运行状态看板</h3>
                    <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">现场检测模块、摄像头和画面更新时间</p>
                  </div>
                </div>
                <StatusBadge level={scopedStatusLevel} />
              </div>

              {isAdmin ? (
                <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-950/40">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-amber-600 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
                      <Bell className="h-4 w-4" />
                    </div>
                    <div className="min-w-[220px] flex-1">
                      <div className="text-sm font-black text-[#071d3d] dark:text-slate-100">全局异常推送</div>
                      <div className="mt-0.5 truncate text-xs font-medium text-slate-500 dark:text-slate-400">
                        摄像头断流、功能异常、模型 Worker 退出和 API 未处理异常统一推送。
                      </div>
                    </div>
                    <Switch
                      aria-label="启用全局异常推送"
                      checked={exceptionWechatEnabled}
                      onCheckedChange={setExceptionWechatEnabled}
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving}
                    />
                    <Input
                      aria-label="推送群号"
                      className="min-w-[220px] flex-[1_1_280px] bg-white dark:bg-slate-900"
                      value={exceptionWechatUser}
                      onChange={(event) => setExceptionWechatUser(event.target.value)}
                      placeholder="推送群号，多个用 | 分隔；也可填 @all"
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving || !exceptionWechatEnabled}
                    />
                    <div className="flex min-w-[190px] items-center gap-2">
                      <Input
                        aria-label="异常重复提醒间隔（分钟）"
                        className="w-24 bg-white dark:bg-slate-900"
                        type="number"
                        min={5}
                        max={1440}
                        value={exceptionRepeatIntervalMinutes}
                        onChange={(event) => setExceptionRepeatIntervalMinutes(Number(event.target.value))}
                        disabled={exceptionSettingsLoading || exceptionSettingsSaving || !exceptionWechatEnabled}
                      />
                      <span className="whitespace-nowrap text-xs font-medium text-slate-500 dark:text-slate-400">分钟内不重复</span>
                    </div>
                    <Button
                      className="gap-2 bg-[#001b43] text-white hover:bg-[#082a5f] dark:bg-blue-600 dark:hover:bg-blue-500"
                      onClick={handleSaveExceptionSettings}
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving}
                    >
                      <Bell className="h-4 w-4" />
                      {exceptionSettingsSaving ? '保存中' : '保存'}
                    </Button>
                  </div>
                  {exceptionSettingsError ? <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{exceptionSettingsError}</div> : null}
                  {exceptionSettingsMessage ? <div className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">{exceptionSettingsMessage}</div> : null}
                </div>
              ) : null}

              <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {visibleStatusCards.map((card) => (
                  <ServiceStatusCard
                    key={card.id}
                    service={platformStatus?.services[card.serviceKey]}
                    displayName={card.title}
                    featureKey={card.featureKey}
                    featureCounts={card.serviceKey === 'aivision' ? aiVisionFeatureCounts : undefined}
                  />
                ))}
              </div>
            </div>
          </div>

          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white p-5 shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92 sm:p-6">
            <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-[linear-gradient(180deg,rgba(225,238,255,0.72),rgba(255,255,255,0))] dark:bg-[linear-gradient(180deg,rgba(37,99,235,0.16),rgba(15,23,42,0))]" />
            <div className="relative flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_14px_26px_rgba(0,27,67,0.22)] dark:bg-blue-600">
                    <ShieldCheck className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-xl font-black tracking-[0] text-[#071d3d] dark:text-slate-100">监管概况</h3>
                    <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">当前账号可查看的检测能力与现场异常概况</p>
                  </div>
                </div>
              </div>
              <Badge className="border border-blue-100 bg-blue-50 px-3 py-1.5 text-sm font-bold text-[#09265a] shadow-none hover:bg-blue-50 dark:border-blue-900/70 dark:bg-blue-950/50 dark:text-blue-100 dark:hover:bg-blue-950/50">
                {departmentLabel(department)}
              </Badge>
            </div>

            <div className="relative mt-6 grid gap-3 sm:grid-cols-2">
              <MetricTile
                title="模块覆盖"
                value={visibleModuleEntries.length}
                detail="按账号权限展示"
                icon={<CircleDotDashed className="h-5 w-5" />}
                tone="blue"
              />
              <MetricTile
                title="接入摄像头"
                value={scopedStatusSummary.cameraTotal}
                detail="平台接入总摄像头数"
                icon={<ScanFace className="h-5 w-5" />}
                tone="cyan"
              />
              <MetricTile
                title="今日异常"
                value={overview.todayAlarms}
                detail="今日累计异常报警数"
                icon={<AlertTriangle className="h-5 w-5" />}
                tone={overview.todayAlarms > 0 ? 'amber' : 'green'}
              />
              <MetricTile
                title="待处理"
                value={overview.pendingAlarms}
                detail="尚未确认处置的报警"
                icon={<AlertTriangle className="h-5 w-5" />}
                tone={overview.pendingAlarms > 0 ? 'amber' : 'green'}
              />
            </div>
          </div>
        </section>

      </div>
      </div>

      <Dialog
        open={cameraDialogOpen}
        onOpenChange={(open) => {
          setCameraDialogOpen(open)
          if (!open && !cameraActionKey) resetCameraForm()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{cameraDialogMode === 'edit' ? '修改摄像头' : '新增摄像头'}</DialogTitle>
            <DialogDescription>
              {cameraDialogMode === 'edit' ? '修改全局摄像头信息，相关检测功能会继续引用该摄像头。' : '选择目标能力并新增摄像头，保存后平台汇总会立即刷新。'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {cameraDialogMode === 'create' ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor="overview-camera-source">目标能力</Label>
                  <Select
                    value={cameraSource}
                    onValueChange={(value) => handleCameraSourceChange(value as CameraSource)}
                    disabled={Boolean(cameraActionKey)}
                  >
                    <SelectTrigger id="overview-camera-source">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {cameraSourceOptions.map((item) => (
                        <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="overview-camera-department">所属事业部</Label>
                  <Select
                    value={cameraDepartment}
                    onValueChange={(value) => handleCameraDepartmentChange(value as Exclude<Department, 'all'>)}
                    disabled={Boolean(cameraActionKey)}
                  >
                    <SelectTrigger id="overview-camera-department">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {departmentOptions
                        .filter((item) => allowedCameraDepartments.includes(item.value))
                        .map((item) => (
                          <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                {cameraSource === 'guard_room' ? (
                  <div className="space-y-2">
                    <Label htmlFor="overview-camera-guard-site">所属保安室</Label>
                    <Select
                      value={cameraGuardSiteId}
                      onValueChange={setCameraGuardSiteId}
                      disabled={Boolean(cameraActionKey) || guardSiteOptions.length === 0}
                    >
                      <SelectTrigger id="overview-camera-guard-site">
                        <SelectValue placeholder={guardSiteOptions.length ? '选择保安室' : '当前事业部暂无保安室'} />
                      </SelectTrigger>
                      <SelectContent>
                        {guardSiteOptions.map((site) => (
                          <SelectItem key={site.id} value={String(site.id)}>{site.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : null}
              </>
            ) : null}
            <div className="space-y-2">
              <Label htmlFor="overview-camera-name">摄像头名称</Label>
              <Input
                id="overview-camera-name"
                value={cameraName}
                onChange={(event) => setCameraName(event.target.value)}
                placeholder="例如：物流通道3"
                disabled={Boolean(cameraActionKey)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="overview-camera-url">RTSP 流地址</Label>
              <Input
                id="overview-camera-url"
                value={cameraUrl}
                onChange={(event) => setCameraUrl(event.target.value)}
                placeholder="rtsp://user:password@host:554/stream"
                disabled={Boolean(cameraActionKey)}
              />
            </div>
            {cameraFormError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{cameraFormError}</div> : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCameraDialogOpen(false)} disabled={Boolean(cameraActionKey)}>
              取消
            </Button>
            <Button
              className="gap-2"
              onClick={handleSaveCamera}
              disabled={Boolean(cameraActionKey) || (cameraDialogMode === 'create' && cameraSource === 'guard_room' && !cameraGuardSiteId)}
            >
              {cameraDialogMode === 'edit' ? <Pencil className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
              {cameraActionKey ? '保存中' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={Boolean(cameraToDelete)}
        onOpenChange={(open) => {
          if (!open && !cameraActionKey) {
            setCameraToDelete(null)
            setCameraDeleteError('')
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除摄像头</AlertDialogTitle>
            <AlertDialogDescription>
              删除后会从全局摄像头库移除 {cameraToDelete?.name || '该摄像头'}，并清理它在所有检测功能里的配置。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {cameraDeleteError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{cameraDeleteError}</div> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(cameraActionKey)}>取消</AlertDialogCancel>
            <Button variant="destructive" className="gap-2" onClick={handleDeleteCamera} disabled={Boolean(cameraActionKey)}>
              <Trash2 className="h-4 w-4" />
              {cameraActionKey ? '删除中' : '删除'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function MetricTile({
  title,
  value,
  detail,
  icon,
  tone,
}: {
  title: string
  value: number
  detail: string
  icon: ReactNode
  tone: 'blue' | 'cyan' | 'amber' | 'green'
}) {
  const toneClass = {
    blue: {
      shell: 'border-blue-100 bg-[linear-gradient(180deg,#eff6ff_0%,#ffffff_100%)] dark:border-blue-900/60 dark:bg-[linear-gradient(180deg,rgba(30,64,175,0.24)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-blue-600 text-white dark:bg-blue-500',
      value: 'text-blue-700 dark:text-blue-300',
    },
    cyan: {
      shell: 'border-cyan-100 bg-[linear-gradient(180deg,#ecfeff_0%,#ffffff_100%)] dark:border-cyan-900/60 dark:bg-[linear-gradient(180deg,rgba(14,116,144,0.22)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-cyan-600 text-white dark:bg-cyan-500',
      value: 'text-cyan-700 dark:text-cyan-300',
    },
    amber: {
      shell: 'border-amber-100 bg-[linear-gradient(180deg,#fffbeb_0%,#ffffff_100%)] dark:border-amber-900/60 dark:bg-[linear-gradient(180deg,rgba(180,83,9,0.22)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-amber-500 text-white dark:bg-amber-500',
      value: 'text-amber-700 dark:text-amber-300',
    },
    green: {
      shell: 'border-emerald-100 bg-[linear-gradient(180deg,#ecfdf5_0%,#ffffff_100%)] dark:border-emerald-900/60 dark:bg-[linear-gradient(180deg,rgba(6,95,70,0.22)_0%,rgba(15,23,42,0.72)_100%)]',
      icon: 'bg-emerald-500 text-white dark:bg-emerald-500',
      value: 'text-emerald-700 dark:text-emerald-300',
    },
  }[tone]

  return (
    <div className={cn('relative overflow-hidden rounded-2xl border p-4 shadow-[0_10px_24px_rgba(15,44,92,0.06)] dark:border-slate-800 dark:bg-slate-950/36', toneClass.shell)}>
      <div className="flex items-center justify-between gap-3">
        <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl shadow-sm', toneClass.icon)}>
          {icon}
        </div>
        <div className={cn('text-3xl font-black tracking-[0]', toneClass.value)}>{value}</div>
      </div>
      <div className="mt-4 text-sm font-bold text-[#071d3d] dark:text-slate-100">{title}</div>
      <div className="mt-1 text-xs font-medium leading-5 text-slate-500 dark:text-slate-400">{detail}</div>
    </div>
  )
}

function StatusBadge({ level }: { level: string }) {
  const label = level === 'healthy' ? '全部正常' : level === 'degraded' ? '部分异常' : '模块离线'
  const className =
    level === 'healthy'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : level === 'degraded'
        ? 'border-amber-200 bg-amber-50 text-amber-700'
        : 'border-red-200 bg-red-50 text-red-700'
  return <Badge className={cn('px-3 py-1.5 text-sm font-bold shadow-none hover:bg-current/0', className)}>{label}</Badge>
}

function ServiceStatusCard({
  service,
  displayName,
  featureKey,
  featureCounts,
}: {
  service?: PlatformServiceStatus
  displayName: string
  featureKey?: string
  featureCounts?: FeatureCameraCounts
}) {
  const online = Boolean(service?.online)
  const running = isCapabilityRunning(service, featureKey, featureCounts)
  const hasError = Boolean(service?.error)
  const modelLoaded = isCapabilityModelReady(service, featureKey, featureCounts)
  const cameraCount = getCapabilityCameraCount(service, featureKey, featureCounts)
  const onlineCameras = getCapabilityOnlineCameraCount(service, featureKey, featureCounts)
  const frameAge = service?.last_frame_age_sec
  const statusText = getServiceStatusText({
    online,
    running,
    hasError,
    featureKey,
    cameraCount,
  })

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/30">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-black text-[#071d3d] dark:text-slate-100">{displayName}</div>
          <div className="mt-1 text-xs font-medium text-slate-500">
            {statusText}
          </div>
        </div>
        <span
          className={cn(
            'mt-1 h-2.5 w-2.5 shrink-0 rounded-full',
            online && running && !hasError ? 'bg-emerald-500' : online ? 'bg-amber-500' : 'bg-red-500',
          )}
        />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">摄像头</div>
          <div className="mt-1 font-black text-slate-900 dark:text-slate-100">{onlineCameras}/{cameraCount}</div>
        </div>
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">识别能力</div>
          <div className={cn('mt-1 font-black', modelLoaded ? 'text-emerald-600' : 'text-amber-600')}>
            {getRecognitionAbilityText({ modelLoaded, running })}
          </div>
        </div>
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">画面更新</div>
          <div className={cn('mt-1 font-black', frameAge && frameAge > 10 ? 'text-amber-600' : 'text-slate-900 dark:text-slate-100')}>
            {typeof frameAge === 'number' ? `${frameAge}s` : '-'}
          </div>
        </div>
        <div className="rounded-xl bg-white px-3 py-2 dark:bg-slate-900/70">
          <div className="text-slate-500">连接响应</div>
          <div className="mt-1 font-black text-slate-900 dark:text-slate-100">
            {typeof service?.latency_ms === 'number' ? `${service.latency_ms}ms` : '-'}
          </div>
        </div>
      </div>
    </div>
  )
}

function MiniStatusMetric({
  label,
  value,
  warn,
}: {
  label: string
  value: string | number
  warn?: boolean
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/30">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={cn('mt-2 text-2xl font-black', warn ? 'text-amber-600' : 'text-[#071d3d] dark:text-slate-100')}>
        {value}
      </div>
    </div>
  )
}
