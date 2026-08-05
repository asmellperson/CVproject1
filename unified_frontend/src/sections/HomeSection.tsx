import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Activity,
  Bell,
  Camera,
  CircleDotDashed,
  DoorOpen,
  Pencil,
  Plus,
  ScanFace,
  Server,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Trash2,
  UserRound,
  UsersRound,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { useAuth } from '@/auth/useAuth'
import { departmentPermissions, filterHomeModulesByPermission, getAccessibleAlarmEventTypes, getUserDepartment } from '@/auth/permissions'
import { getAlarms, type AlarmEvent, type PlatformServiceStatus, type PlatformStatus } from '@/lib/api'
import { getRecognitionAbilityText, getServiceStatusText } from './HomeSection.status'
import {
  createAiVisionCamera,
  deleteAiVisionCamera,
  getAiVisionCameraKey,
  getAiVisionCameras,
  getAiVisionExceptionAlertSettings,
  isAiVisionFeatureEnabled,
  saveAiVisionExceptionAlertSettings,
  updateAiVisionCamera,
  type AiVisionCamera,
} from '@/lib/aivision'

interface HomeSectionProps {
  onNavigate: (page: string) => void
  platformStatus: PlatformStatus | null
}

const moduleEntries = [
  {
    id: 'security-vlm-general-electric',
    title: '安检流程规范检测入口',
    icon: ShieldAlert,
    status: '已接入',
    accent: 'from-cyan-500 to-blue-500',
    glow: 'shadow-cyan-500/16',
    iconColor: 'text-cyan-700',
    iconBg: 'from-cyan-50 to-blue-100',
  },
  {
    id: 'security-vlm-electronics-electrician',
    title: '安检流程规范检测入口',
    icon: ShieldAlert,
    status: '已接入',
    accent: 'from-cyan-500 to-blue-500',
    glow: 'shadow-cyan-500/16',
    iconColor: 'text-cyan-700',
    iconBg: 'from-cyan-50 to-blue-100',
  },
  {
    id: 'security-vlm-electrical-components',
    title: '安检流程规范检测入口',
    icon: ShieldAlert,
    status: '已接入',
    accent: 'from-cyan-500 to-blue-500',
    glow: 'shadow-cyan-500/16',
    iconColor: 'text-cyan-700',
    iconBg: 'from-cyan-50 to-blue-100',
  },
  {
    id: 'security-vlm-precious-metal-recycling',
    title: '安检流程规范检测入口',
    icon: ShieldAlert,
    status: '已接入',
    accent: 'from-cyan-500 to-blue-500',
    glow: 'shadow-cyan-500/16',
    iconColor: 'text-cyan-700',
    iconBg: 'from-cyan-50 to-blue-100',
  },
  {
    id: 'guard-behavior-general-electric',
    title: '保安行为规范检测入口',
    icon: ShieldCheck,
    status: '已接入',
    accent: 'from-sky-500 to-blue-600',
    glow: 'shadow-blue-500/18',
    iconColor: 'text-blue-600',
    iconBg: 'from-blue-50 to-sky-100',
  },
  {
    id: 'guard-behavior-electronics-electrician',
    title: '保安行为规范检测入口',
    icon: ShieldCheck,
    status: '已接入',
    accent: 'from-blue-500 to-cyan-600',
    glow: 'shadow-cyan-500/18',
    iconColor: 'text-cyan-700',
    iconBg: 'from-cyan-50 to-blue-100',
  },
  {
    id: 'intrusion-detection',
    title: '区域入侵检测入口',
    icon: UserRound,
    status: '已接入',
    accent: 'from-teal-400 to-emerald-500',
    glow: 'shadow-emerald-500/16',
    iconColor: 'text-teal-600',
    iconBg: 'from-teal-50 to-cyan-100',
  },
  {
    id: 'door-detection',
    title: '大门开关检测入口',
    icon: DoorOpen,
    status: '已接入',
    accent: 'from-indigo-500 to-blue-600',
    glow: 'shadow-indigo-500/16',
    iconColor: 'text-indigo-600',
    iconBg: 'from-indigo-50 to-blue-100',
  },
  {
    id: 'face-detection',
    title: '人脸检测入口',
    icon: ScanFace,
    status: '已接入',
    accent: 'from-violet-500 to-purple-600',
    glow: 'shadow-violet-500/16',
    iconColor: 'text-violet-600',
    iconBg: 'from-violet-50 to-purple-100',
  },
  {
    id: 'human-detection',
    title: '人员逗留检测入口',
    icon: CircleDotDashed,
    status: '已接入',
    accent: 'from-amber-400 to-orange-500',
    glow: 'shadow-orange-500/16',
    iconColor: 'text-orange-600',
    iconBg: 'from-orange-50 to-amber-100',
  },
  {
    id: 'logistics-single-person-detection',
    title: '物流通道单人检测入口',
    icon: UsersRound,
    status: '已接入',
    accent: 'from-teal-500 to-cyan-600',
    glow: 'shadow-teal-500/16',
    iconColor: 'text-teal-700',
    iconBg: 'from-teal-50 to-cyan-100',
  },
  {
    id: 'logistics-single-person-electronics-electrician-detection',
    title: '物流通道单人检测入口（电子电工）',
    icon: UsersRound,
    status: '已接入',
    accent: 'from-teal-500 to-cyan-600',
    glow: 'shadow-teal-500/16',
    iconColor: 'text-teal-700',
    iconBg: 'from-teal-50 to-cyan-100',
  },
  {
    id: 'logistics-single-person-electrical-components-detection',
    title: '物流通道单人检测入口（电气部件）',
    icon: UsersRound,
    status: '已接入',
    accent: 'from-teal-500 to-cyan-600',
    glow: 'shadow-teal-500/16',
    iconColor: 'text-teal-700',
    iconBg: 'from-teal-50 to-cyan-100',
  },
  {
    id: 'logistics-single-person-precious-metal-recycling-detection',
    title: '物流通道单人检测入口（贵金属回收）',
    icon: UsersRound,
    status: '已接入',
    accent: 'from-teal-500 to-cyan-600',
    glow: 'shadow-teal-500/16',
    iconColor: 'text-teal-700',
    iconBg: 'from-teal-50 to-cyan-100',
  },
  {
    id: 'phone-detection',
    title: '手机使用检测入口',
    icon: Smartphone,
    status: '已接入',
    accent: 'from-rose-500 to-red-500',
    glow: 'shadow-rose-500/16',
    iconColor: 'text-rose-600',
    iconBg: 'from-rose-50 to-red-100',
  },
  
]

type OverviewState = {
  todayAlarms: number
  pendingAlarms: number
  latestAlarm: AlarmEvent | null
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
  'logistics-single-person-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person' },
  'logistics-single-person-electronics-electrician-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person_electronics_electrician' },
  'logistics-single-person-electrical-components-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person_electrical_components' },
  'logistics-single-person-precious-metal-recycling-detection': { serviceKey: 'aivision', featureKey: 'detect_logistics_single_person_precious_metal_recycling' },
  'phone-detection': { serviceKey: 'aivision', featureKey: 'detect_phone' },
}

type ModuleStatusCard = (typeof moduleEntries)[number] & ModuleStatusSource
type ModuleEntry = (typeof moduleEntries)[number]
type DepartmentModuleGroup = {
  id: string
  title: string
  description: string
  entries: ModuleEntry[]
}

type FeatureCameraCounts = Record<string, {
  cameraCount: number
  enabledCameraCount: number
}>

const aiVisionFeatureLabels: Record<string, string> = {
  blocks: '区域入侵',
  detect_door: '大门开关',
  detect_face: '人脸检测',
  detect_human: '人员逗留',
  detect_logistics_single_person: '物流单人',
  detect_logistics_single_person_electronics_electrician: '物流单人（电子电工）',
  detect_logistics_single_person_electrical_components: '物流单人（电气部件）',
  detect_logistics_single_person_precious_metal_recycling: '物流单人（贵金属回收）',
  detect_phone: '手机使用',
}

const defaultOverview: OverviewState = {
  todayAlarms: 0,
  pendingAlarms: 0,
  latestAlarm: null,
}

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

function departmentLabel(department: ReturnType<typeof getUserDepartment>) {
  if (department === 'general_electric') return '通用电气视图'
  if (department === 'electronics_electrician') return '电子电工视图'
  if (department === 'electrical_components') return '电气部件视图'
  if (department === 'precious_metal_recycling') return '贵金属回收视图'
  if (department === 'research_institute') return '研究院视图'
  if (department === 'all') return '全局视图'
  return '权限视图'
}

function getRunningConsumers(service?: PlatformServiceStatus) {
  return Array.isArray(service?.running_consumers) ? service.running_consumers.map(String) : []
}

function getAiVisionFeatureCounts(cameras: AiVisionCamera[]): FeatureCameraCounts {
  const features = ['blocks', 'detect_door', 'detect_face', 'detect_human', 'detect_logistics_single_person', 'detect_logistics_single_person_electronics_electrician', 'detect_logistics_single_person_electrical_components', 'detect_logistics_single_person_precious_metal_recycling', 'detect_phone']
  return features.reduce<FeatureCameraCounts>((acc, feature) => {
    const featureCameras = cameras.filter((camera) => isAiVisionFeatureEnabled(camera, feature))
    acc[feature] = {
      cameraCount: featureCameras.length,
      enabledCameraCount: featureCameras.filter((camera) => camera.enabled).length,
    }
    return acc
  }, {})
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

const adminDepartmentGroups = [
  {
    id: 'general_electric',
    title: '通用电气部',
    description: '安检流程、保安行为、后大门异常逗留等检测能力',
    pages: departmentPermissions.general_electric.pages,
  },
  {
    id: 'electronics_electrician',
    title: '电子电工',
    description: '保安行为规范检测能力',
    pages: departmentPermissions.electronics_electrician.pages,
  },
  {
    id: 'electrical_components',
    title: '电气部件事业部',
    description: '物流通道单人检测能力',
    pages: departmentPermissions.electrical_components.pages,
  },
  {
    id: 'precious_metal_recycling',
    title: '贵金属回收事业部',
    description: '物流通道单人检测能力',
    pages: departmentPermissions.precious_metal_recycling.pages,
  },
  {
    id: 'research_institute',
    title: '研究院',
    description: '区域入侵、人脸检测、手机使用等检测能力',
    pages: departmentPermissions.research_institute.pages,
  },
]

function getAdminDepartmentModuleGroups(entries: ModuleEntry[]): DepartmentModuleGroup[] {
  const byId = new Map(entries.map((entry) => [entry.id, entry]))
  const groupedIds = new Set<string>()
  const groups = adminDepartmentGroups.flatMap((group) => {
    const groupEntries = group.pages.flatMap((pageId) => {
      const entry = byId.get(pageId)
      if (!entry) return []
      groupedIds.add(entry.id)
      return [entry]
    })
    if (!groupEntries.length) return []
    return [{ id: group.id, title: group.title, description: group.description, entries: groupEntries }]
  })
  const unassignedEntries = entries.filter((entry) => !groupedIds.has(entry.id))
  if (unassignedEntries.length) {
    groups.push({
      id: 'shared',
      title: '公共能力',
      description: '暂未归入单一部门的检测能力',
      entries: unassignedEntries,
    })
  }
  return groups
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
  const overviewMascotVideoRef = useRef<HTMLVideoElement | null>(null)
  const visibleModuleEntries = useMemo(() => filterHomeModulesByPermission(user, moduleEntries), [user])
  const adminModuleGroups = useMemo(
    () => (isAdmin ? getAdminDepartmentModuleGroups(visibleModuleEntries) : []),
    [isAdmin, visibleModuleEntries],
  )
  const visibleStatusCards = useMemo(() => getVisibleStatusCards(visibleModuleEntries), [visibleModuleEntries])
  const [overview, setOverview] = useState<OverviewState>(defaultOverview)
  const [aiVisionCameras, setAiVisionCameras] = useState<AiVisionCamera[]>([])
  const [exceptionWechatEnabled, setExceptionWechatEnabled] = useState(false)
  const [exceptionWechatUser, setExceptionWechatUser] = useState('')
  const [exceptionSettingsLoading, setExceptionSettingsLoading] = useState(false)
  const [exceptionSettingsSaving, setExceptionSettingsSaving] = useState(false)
  const [exceptionSettingsMessage, setExceptionSettingsMessage] = useState('')
  const [exceptionSettingsError, setExceptionSettingsError] = useState('')
  const [cameraDialogOpen, setCameraDialogOpen] = useState(false)
  const [cameraDialogMode, setCameraDialogMode] = useState<'create' | 'edit'>('create')
  const [cameraToEdit, setCameraToEdit] = useState<AiVisionCamera | null>(null)
  const [cameraName, setCameraName] = useState('')
  const [cameraUrl, setCameraUrl] = useState('')
  const [cameraFormError, setCameraFormError] = useState('')
  const [cameraActionKey, setCameraActionKey] = useState('')
  const [cameraToDelete, setCameraToDelete] = useState<AiVisionCamera | null>(null)
  const [cameraDeleteError, setCameraDeleteError] = useState('')
  const department = getUserDepartment(user)
  const accessibleAlarmEventTypes = useMemo(() => getAccessibleAlarmEventTypes(user), [user])
  const aiVisionFeatureCounts = useMemo(() => getAiVisionFeatureCounts(aiVisionCameras), [aiVisionCameras])
  const scopedStatusSummary = useMemo(() => getScopedStatusSummary(visibleStatusCards, platformStatus, aiVisionFeatureCounts), [aiVisionFeatureCounts, platformStatus, visibleStatusCards])
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

    setExceptionSettingsSaving(true)
    setExceptionSettingsError('')
    setExceptionSettingsMessage('')
    try {
      const next = await saveAiVisionExceptionAlertSettings({
        wechat_enable: exceptionWechatEnabled,
        wechat_user: exceptionWechatUser.trim(),
      })
      setExceptionWechatEnabled(Boolean(next.wechat_enable))
      setExceptionWechatUser(next.wechat_user || '')
      setExceptionSettingsMessage('全局异常推送配置已保存。')
    } catch (error) {
      setExceptionSettingsError(`保存全局异常推送配置失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setExceptionSettingsSaving(false)
    }
  }

  const reloadAiVisionCameras = async () => {
    const cameras = await getAiVisionCameras()
    setAiVisionCameras(cameras)
    window.dispatchEvent(new Event('aivision:cameras-changed'))
  }

  const resetCameraForm = () => {
    setCameraName('')
    setCameraUrl('')
    setCameraToEdit(null)
    setCameraFormError('')
  }

  const openCreateCameraDialog = () => {
    setCameraDialogMode('create')
    resetCameraForm()
    setCameraDialogOpen(true)
  }

  const openEditCameraDialog = (camera: AiVisionCamera) => {
    setCameraDialogMode('edit')
    setCameraToEdit(camera)
    setCameraName(camera.name)
    setCameraUrl(camera.url)
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

    const actionKey = cameraDialogMode === 'edit' && cameraToEdit
      ? getAiVisionCameraKey(cameraToEdit)
      : makeAiVisionShmName(name)
    setCameraActionKey(actionKey)
    setCameraFormError('')
    try {
      if (cameraDialogMode === 'edit' && cameraToEdit) {
        await updateAiVisionCamera(getAiVisionCameraKey(cameraToEdit), { name, url })
      } else {
        await createAiVisionCamera({
          name,
          url,
          shm_name: actionKey,
          enabled: true,
        })
      }
      await reloadAiVisionCameras()
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
      await reloadAiVisionCameras()
      setCameraToDelete(null)
    } catch (error) {
      setCameraDeleteError(`删除失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCameraActionKey('')
    }
  }

  useEffect(() => {
    let cancelled = false

    async function loadOverview() {
      const [alarms, cameras] = await Promise.allSettled([
        getAlarms(100),
        getAiVisionCameras(),
      ])

      if (cancelled) return
      const currentAiVisionCameras = cameras.status === 'fulfilled' ? cameras.value : []
      setAiVisionCameras(currentAiVisionCameras)

      const allowedAlarmTypes = accessibleAlarmEventTypes ? new Set(accessibleAlarmEventTypes) : null
      const alarmItems = alarms.status === 'fulfilled'
        ? alarms.value.filter((alarm) => !allowedAlarmTypes || allowedAlarmTypes.has(alarm.event_type))
        : []

      setOverview({
        todayAlarms: alarmItems.filter((alarm) => isToday(alarm.created_at)).length,
        pendingAlarms: alarmItems.filter((alarm) => (alarm.disposition_status || 'pending') === 'pending').length,
        latestAlarm: alarmItems[0] || null,
      })
    }

    loadOverview().catch(() => {
      if (!cancelled) {
        setOverview(defaultOverview)
      }
    })

    const timer = window.setInterval(() => {
      loadOverview().catch(() => {
        if (!cancelled) setOverview(defaultOverview)
      })
    }, 10000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [accessibleAlarmEventTypes])

  const replayOverviewMascot = () => {
    const video = overviewMascotVideoRef.current
    if (!video) return
    video.currentTime = 0
    void video.play().catch(() => undefined)
  }

  return (
    <>
      <div className="relative -mx-3 -my-4 min-h-[calc(100dvh-64px)] overflow-hidden bg-[#f5f8fc] p-3 dark:bg-[#07111f] sm:-mx-4 sm:-my-5 sm:min-h-[calc(100vh-72px)] sm:p-4 lg:-mx-8 lg:-my-6 lg:p-8 2xl:-mx-10 2xl:p-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#f8fbff_0%,#eef4fb_48%,#f8fafc_100%)] dark:bg-[linear-gradient(180deg,#07111f_0%,#0b1626_48%,#07111f_100%)]" />
      <div aria-hidden className="pointer-events-none absolute inset-x-10 top-8 h-24 rounded-full bg-blue-200/20 blur-3xl dark:bg-blue-500/10" />

      <div className="relative z-[1] flex w-full min-w-0 flex-col gap-4 sm:gap-7">
        <section className="relative overflow-hidden rounded-[14px] border border-white/80 bg-slate-900 shadow-[0_22px_54px_rgba(15,44,92,0.16)] dark:border-slate-800 dark:shadow-[0_22px_54px_rgba(0,0,0,0.36)] sm:rounded-[18px]">
          <img src="/company-home-bg.jpg" alt="" className="absolute inset-0 h-full w-full object-cover object-center" />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(232,242,255,0.96)_0%,rgba(222,236,255,0.78)_50%,rgba(218,235,255,0.16)_100%)] dark:bg-[linear-gradient(90deg,rgba(7,17,31,0.94)_0%,rgba(9,25,48,0.82)_45%,rgba(9,25,48,0.24)_100%)] sm:bg-[linear-gradient(90deg,rgba(232,242,255,0.94)_0%,rgba(222,236,255,0.66)_38%,rgba(218,235,255,0.08)_72%)] dark:sm:bg-[linear-gradient(90deg,rgba(7,17,31,0.92)_0%,rgba(9,25,48,0.72)_42%,rgba(9,25,48,0.16)_78%)]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(255,255,255,0.9),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.2),rgba(255,255,255,0))] dark:bg-[radial-gradient(circle_at_15%_20%,rgba(59,130,246,0.18),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.05),rgba(255,255,255,0))]" />
          <div className="relative flex min-h-[240px] px-5 py-5 sm:min-h-[280px] sm:px-10 sm:py-7 md:pl-[340px] lg:px-14 lg:pl-[390px]">
            <div className="relative z-[3] flex max-w-3xl -translate-y-3 flex-col justify-center sm:-translate-y-4">
              <Badge className="mb-4 w-fit border border-blue-200 bg-white/78 px-3 py-1 text-sm font-semibold text-[#09265a] shadow-none hover:bg-white/78 dark:border-blue-900/70 dark:bg-slate-950/70 dark:text-blue-100 dark:hover:bg-slate-950/70">
                {departmentLabel(department)}
              </Badge>
              <h2 className="max-w-2xl text-3xl font-black tracking-[0] text-[#061d45] drop-shadow-[0_10px_22px_rgba(255,255,255,0.65)] dark:text-white dark:drop-shadow-[0_10px_22px_rgba(0,0,0,0.55)] sm:text-4xl md:text-5xl">
                福达 AI 视觉安全监管平台
              </h2>
            </div>
            <div className="pointer-events-none absolute inset-y-0 left-0 z-[2] hidden w-[40%] max-w-[560px] justify-center md:flex">
              <button
                type="button"
                className="overview-mascot-trigger pointer-events-auto block w-full cursor-pointer border-0 bg-transparent p-0"
                aria-label="重新播放平台吉祥物动画"
                onClick={replayOverviewMascot}
              >
                <video
                  ref={overviewMascotVideoRef}
                  className="overview-mascot-media block h-full w-full select-none object-cover object-right opacity-50 mix-blend-multiply [mask-image:linear-gradient(to_right,#000_0%,#000_28%,transparent_100%)] [-webkit-mask-image:linear-gradient(to_right,#000_0%,#000_28%,transparent_100%)]"
                  autoPlay
                  muted
                  playsInline
                  preload="auto"
                  poster="/平台总览动画-蓝白版-poster.jpg?v=3"
                  onEnded={(event) => {
                    event.currentTarget.pause()
                  }}
                >
                  <source src="/平台总览动画-蓝白版.mp4?v=3" type="video/mp4" />
                </video>
              </button>
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]">
            <div className="h-1.5 bg-gradient-to-r from-[#001b43] via-blue-500 to-cyan-400" />
            <div className="relative p-5 sm:p-6">
              <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-[linear-gradient(180deg,rgba(225,238,255,0.72),rgba(255,255,255,0))] dark:bg-[linear-gradient(180deg,rgba(37,99,235,0.16),rgba(15,23,42,0))]" />
              <div className="relative flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_14px_26px_rgba(0,27,67,0.22)] dark:bg-blue-600">
                      <ShieldCheck className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="text-xl font-black tracking-[0] text-[#071d3d] dark:text-slate-100">统一监管总览</h3>
                      <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">当前账号可查看的检测能力与现场异常概况</p>
                    </div>
                  </div>
                </div>
                <Badge className="border border-blue-100 bg-blue-50 px-3 py-1.5 text-sm font-bold text-[#09265a] shadow-none hover:bg-blue-50 dark:border-blue-900/70 dark:bg-blue-950/50 dark:text-blue-100 dark:hover:bg-blue-950/50">
                  {departmentLabel(department)}
                </Badge>
              </div>

              <div className="relative mt-6 grid gap-3 sm:grid-cols-4">
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
          </div>

          <div className={cn(
            'relative overflow-hidden rounded-[18px] border bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:bg-slate-900/92 dark:shadow-[0_18px_48px_rgba(0,0,0,0.32)]',
            overview.latestAlarm ? 'border-amber-100 dark:border-amber-900/50' : 'border-emerald-100 dark:border-emerald-900/50',
          )}>
            <div className={cn('h-1.5', overview.latestAlarm ? 'bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500' : 'bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500')} />
            <div className="relative p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">最近异常</h3>
                  <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">
                    {overview.latestAlarm ? '最新一条可见报警事件' : '当前可见范围内暂无异常'}
                  </p>
                </div>
                <div className={cn(
                  'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl shadow-sm',
                  overview.latestAlarm ? 'bg-amber-50 text-amber-600 ring-1 ring-amber-100 dark:bg-amber-950/50 dark:ring-amber-900/70' : 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100 dark:bg-emerald-950/50 dark:ring-emerald-900/70',
                )}>
                  <AlertTriangle className="h-5 w-5" />
                </div>
              </div>

              {overview.latestAlarm ? (
                <div className="mt-5 rounded-2xl border border-amber-100 bg-[linear-gradient(180deg,#fffaf0_0%,#ffffff_100%)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.8)] dark:border-amber-900/50 dark:bg-[linear-gradient(180deg,rgba(69,42,15,0.32)_0%,rgba(15,23,42,0.22)_100%)]">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-base font-black text-[#071d3d] dark:text-slate-100">{overview.latestAlarm.event_label || overview.latestAlarm.event_type}</div>
                      <div className="mt-1 truncate text-sm font-semibold text-slate-500 dark:text-slate-400">{overview.latestAlarm.camera_name || overview.latestAlarm.camera_no || '未知摄像头'}</div>
                    </div>
                    <Badge className="shrink-0 border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-700 shadow-none hover:bg-amber-50">
                      {formatLatestTime(overview.latestAlarm.created_at)}
                    </Badge>
                  </div>
                  <div className="mt-4 rounded-xl border border-white/80 bg-white/78 p-3 text-sm font-medium leading-6 text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-950/42 dark:text-slate-300">
                    <p className="line-clamp-3">{overview.latestAlarm.reason}</p>
                  </div>
                </div>
              ) : (
                <div className="mt-5 rounded-2xl border border-emerald-100 bg-[linear-gradient(180deg,#ecfdf5_0%,#ffffff_100%)] p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.86)] dark:border-emerald-900/50 dark:bg-[linear-gradient(180deg,rgba(6,78,59,0.25)_0%,rgba(15,23,42,0.18)_100%)]">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_0_6px_rgba(16,185,129,0.14)]" />
                    <div className="text-sm font-semibold leading-6 text-emerald-700 dark:text-emerald-300">
                      今日暂无异常记录，当前总览处于平稳状态。
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,430px)]">
          <div className="relative overflow-hidden rounded-[18px] border border-white/90 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.12)] dark:border-slate-800 dark:bg-slate-900/92">
            <div className={cn(
              'h-1.5',
              platformStatus?.level === 'healthy'
                ? 'bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500'
                : platformStatus?.level === 'degraded'
                  ? 'bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500'
                  : 'bg-gradient-to-r from-red-600 via-rose-500 to-orange-500',
            )} />
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
                <div className="mt-5 rounded-2xl border border-amber-100 bg-amber-50/55 p-4 shadow-sm dark:border-amber-900/50 dark:bg-amber-950/20">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm font-black text-[#071d3d] dark:text-slate-100">
                        <Bell className="h-4 w-4 text-amber-600" />
                        全局异常推送
                      </div>
                      <div className="mt-1 text-xs font-medium leading-5 text-slate-500 dark:text-slate-400">
                        摄像头断流、功能异常、模型 Worker 退出和 API 未处理异常统一推送。
                      </div>
                    </div>
                    <Switch
                      checked={exceptionWechatEnabled}
                      onCheckedChange={setExceptionWechatEnabled}
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving}
                    />
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                    <Input
                      value={exceptionWechatUser}
                      onChange={(event) => setExceptionWechatUser(event.target.value)}
                      placeholder="多个接收人用 | 分隔，例如 zhangsan|lisi；也可填 @all"
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving || !exceptionWechatEnabled}
                    />
                    <Button
                      className="gap-2"
                      onClick={handleSaveExceptionSettings}
                      disabled={exceptionSettingsLoading || exceptionSettingsSaving}
                    >
                      <Bell className="h-4 w-4" />
                      {exceptionSettingsSaving ? '保存中' : '保存'}
                    </Button>
                  </div>
                  {exceptionSettingsError ? <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{exceptionSettingsError}</div> : null}
                  {exceptionSettingsMessage ? <div className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{exceptionSettingsMessage}</div> : null}
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
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cyan-600 text-white shadow-sm">
                <Activity className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">平台汇总</h3>
                <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">平台状态 30 秒 · 摄像头 10 秒刷新</p>
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <MiniStatusMetric label="能力在线" value={`${scopedStatusSummary.capabilityOnline}/${scopedStatusSummary.capabilityTotal}`} />
              <MiniStatusMetric label="正在检测" value={`${scopedStatusSummary.capabilityRunning}/${scopedStatusSummary.capabilityTotal}`} />
              <MiniStatusMetric label="摄像头在线" value={`${scopedStatusSummary.cameraOnline}/${scopedStatusSummary.cameraTotal}`} />
              <MiniStatusMetric label="摄像头离线" value={scopedStatusSummary.cameraOffline} warn={scopedStatusSummary.cameraOffline > 0} />
            </div>

            <div className="mt-5 flex h-[360px] flex-col overflow-hidden rounded-2xl border border-blue-100 bg-[#f8fbff] shadow-sm dark:border-slate-800 dark:bg-slate-950/30">
              <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-blue-100 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-black text-[#071d3d] dark:text-slate-100">
                    <Camera className="h-4 w-4 text-cyan-600" />
                    全部摄像头
                  </div>
                  <div className="mt-1 text-xs font-medium text-slate-500 dark:text-slate-400">
                    共 {aiVisionCameras.length} 路；在各检测功能配置页可选择加入当前功能。
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
                {aiVisionCameras.length === 0 ? (
                  <div className="px-4 py-6 text-sm font-medium text-slate-500">暂无摄像头。</div>
                ) : (
                  aiVisionCameras.map((camera) => {
                    const cameraKey = getAiVisionCameraKey(camera)
                    const featureLabels = getAiVisionCameraFeatureLabels(camera)
                    return (
                      <div
                        key={cameraKey}
                        className="border-b border-blue-100 bg-white px-4 py-3 last:border-b-0 dark:border-slate-800 dark:bg-slate-900/70"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-bold text-[#071d3d] dark:text-slate-100">{camera.name}</div>
                            <div className="mt-1 truncate text-xs font-medium text-slate-500">{camera.shm_name}</div>
                          </div>
                          {isAdmin ? (
                            <div className="flex shrink-0 items-center gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                className="gap-1.5"
                                onClick={() => openEditCameraDialog(camera)}
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
                                  setCameraToDelete(camera)
                                  setCameraDeleteError('')
                                }}
                                disabled={Boolean(cameraActionKey)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                删除
                              </Button>
                            </div>
                          ) : null}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {featureLabels.length ? (
                            featureLabels.map((label) => (
                              <Badge key={label} variant="outline" className="bg-emerald-50 text-[11px] font-semibold text-emerald-700">
                                {label}
                              </Badge>
                            ))
                          ) : (
                            <span className="text-xs font-medium text-slate-400">暂未加入检测功能</span>
                          )}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          </div>
        </section>

        {isAdmin ? (
          <section className="space-y-4">
            {adminModuleGroups.map((group) => (
              <div key={group.id} className="space-y-3">
                <div className="flex flex-wrap items-end justify-between gap-3 px-1">
                  <div>
                    <h3 className="text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">{group.title}</h3>
                    <p className="mt-1 text-sm font-medium text-slate-500 dark:text-slate-400">{group.description}</p>
                  </div>
                  <Badge className="border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-bold text-[#09265a] shadow-none hover:bg-blue-50 dark:border-blue-900/70 dark:bg-blue-950/50 dark:text-blue-100">
                    {group.entries.length} 项能力
                  </Badge>
                </div>
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-7">
                  {group.entries.map((entry) => (
                    <ModuleEntryCard key={entry.id} entry={entry} onNavigate={onNavigate} />
                  ))}
                </div>
              </div>
            ))}
          </section>
        ) : (
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-7">
            {visibleModuleEntries.map((entry) => (
              <ModuleEntryCard key={entry.id} entry={entry} onNavigate={onNavigate} />
            ))}
          </section>
        )}
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
              {cameraDialogMode === 'edit' ? '修改全局摄像头信息，相关检测功能会继续引用该摄像头。' : '新增后会出现在各检测功能配置页的已有摄像头列表中。'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
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
            <Button className="gap-2" onClick={handleSaveCamera} disabled={Boolean(cameraActionKey)}>
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

function ModuleEntryCard({ entry, onNavigate }: { entry: ModuleEntry; onNavigate: (page: string) => void }) {
  const Icon = entry.icon
  return (
    <article
      className={cn(
        'group relative min-h-[176px] overflow-hidden rounded-[14px] border border-white bg-white shadow-[0_16px_42px_rgba(25,53,93,0.10)] dark:border-slate-800 dark:bg-slate-900/92 dark:shadow-[0_16px_42px_rgba(0,0,0,0.30)] sm:min-h-[218px]',
        'transition duration-200 hover:-translate-y-1 hover:shadow-[0_24px_58px_rgba(25,53,93,0.16)]',
        entry.glow,
      )}
    >
      <div className={`h-1.5 bg-gradient-to-r ${entry.accent}`} />
      <div className="absolute -right-10 bottom-2 opacity-[0.055] transition duration-200 group-hover:scale-105 group-hover:opacity-[0.08] sm:-right-12">
        <Icon className="h-32 w-32 text-slate-900 sm:h-40 sm:w-40" strokeWidth={1.4} />
      </div>
      <div className="relative flex h-full flex-col justify-between p-5 sm:p-7">
        <div className="flex items-start gap-4 sm:gap-5">
          <div className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${entry.iconBg} shadow-[0_10px_26px_rgba(30,78,141,0.12)] ring-1 ring-white sm:h-[74px] sm:w-[74px]`}>
            <Icon className={`h-7 w-7 sm:h-9 sm:w-9 ${entry.iconColor}`} strokeWidth={1.8} />
          </div>
          <div className="min-w-0 pt-1 sm:pt-3">
            <h3 className="text-lg font-bold tracking-[0] text-[#071d3d] sm:text-[22px]">{entry.title}</h3>
            <Badge className="mt-3 border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-600 shadow-none hover:bg-emerald-50">
              {entry.status}
            </Badge>
          </div>
        </div>
        <Button
          className="mt-5 h-11 w-full justify-between rounded-xl bg-[#001b43] px-5 text-base font-semibold text-white shadow-[0_10px_20px_rgba(0,27,67,0.22)] hover:bg-[#082a5f] dark:bg-blue-600 dark:hover:bg-blue-500 sm:mt-7 sm:h-12 sm:w-[210px] sm:px-8"
          onClick={() => onNavigate(entry.id)}
        >
          进入功能
          <ArrowRight className="h-5 w-5" />
        </Button>
      </div>
    </article>
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
      shell: 'border-blue-100 bg-[linear-gradient(180deg,#eff6ff_0%,#ffffff_100%)]',
      icon: 'bg-blue-600 text-white',
      value: 'text-blue-700',
    },
    cyan: {
      shell: 'border-cyan-100 bg-[linear-gradient(180deg,#ecfeff_0%,#ffffff_100%)]',
      icon: 'bg-cyan-600 text-white',
      value: 'text-cyan-700',
    },
    amber: {
      shell: 'border-amber-100 bg-[linear-gradient(180deg,#fffbeb_0%,#ffffff_100%)]',
      icon: 'bg-amber-500 text-white',
      value: 'text-amber-700',
    },
    green: {
      shell: 'border-emerald-100 bg-[linear-gradient(180deg,#ecfdf5_0%,#ffffff_100%)]',
      icon: 'bg-emerald-500 text-white',
      value: 'text-emerald-700',
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
