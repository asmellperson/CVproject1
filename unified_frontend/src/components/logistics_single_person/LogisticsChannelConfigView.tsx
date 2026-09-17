import { splitChannelConfig } from './channelConfigDrafts'
import type { DepartmentId } from '@/auth/permissions'
import { parseNormalizedRoi } from '@/components/AiVisionRoiEditor.geometry'
import { useDepartmentCatalog } from '@/hooks/use-department-catalog'
import { toFeatureAlarm, toLogisticsAlarm } from './alarmBinding'
import { validateHornBinding } from '@/lib/horn-alarm-binding'
import { DetectionConfigTabs } from '@/components/detection/DetectionConfigTabs'
import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Bell, Camera, Crosshair, Layers3, Plus, SlidersHorizontal, Trash2 } from 'lucide-react'

import { AlarmPushConfig } from '@/components/AlarmPushConfig'
import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import {
  DETECTION_CONFIG_CARD_CLASS,
  DetectionConfigCardContent,
  DetectionConfigCardHeader,
  DetectionConfigTab,
  DetectionSaveBar,
} from '@/components/detection/DetectionConfigUi'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TabsContent } from '@/components/ui/tabs'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'

import {
  addLogisticsChannelCamera,
  createLogisticsChannel,
  deleteLogisticsChannel,
  getLogisticsChannel,
  getLogisticsCameraRoi,
  moveLogisticsChannelCamera,
  removeLogisticsChannelCamera,
  reorderLogisticsChannelCameras,
  setLogisticsChannelCameraEnabled,
  updateLogisticsCameraRoi,
  updateLogisticsChannel,
} from './api'
import type {
  LogisticsCameraRoiResponse,
  LogisticsChannel,
  LogisticsChannelAlarmDraft,
  LogisticsChannelDetectionConfig,
  LogisticsChannelDetail,
  LogisticsFeatureName,
} from './types'
import {
  collectBoundCameraIds,
  collectChannelMemberCounts,
  confirmMembershipRemoval,
  filterBindableCameras,
  isMembershipLoadCurrent,
  removalConfirmationText,
  type ChannelMemberCount,
  type MembershipLoadIdentity,
} from './membershipState'
import { channelCreateDialogReducer, initialChannelCreateDialogState } from './channelCreateDialogState'
import { LogisticsCameraCreateDialog } from './LogisticsCameraCreateDialog'
import type { LogisticsCameraCreateInput } from './logisticsCameraCreateState'
import { notifyPlatformCamerasChanged } from '@/lib/camera-events'

type Props = {
  feature: LogisticsFeatureName
  department: DepartmentId
  channels: LogisticsChannel[]
  selectedChannelId: number | null
  selectedChannelDetail: LogisticsChannelDetail | null
  isAdmin: boolean
  onSelectChannel: (channelId: number) => void
  onChannelCreated: (channel: LogisticsChannelDetail) => void
  onChannelDeleted: (channelId: number) => void
  onChanged: () => void
}

const timeForInput = (value: string) => value.slice(0, 5)
const timeForApi = (value: string) => value.length === 5 ? `${value}:00` : value

function detectionTimeSeconds(value: string): number | null {
  const match = /^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d(?:\.\d{1,6})?))?$/.exec(value)
  return match ? Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3] ?? 0) : null
}

function messageOf(reason: unknown) {
  return reason instanceof Error ? reason.message : String(reason)
}

export function LogisticsChannelConfigView({
  feature,
  department,
  channels,
  selectedChannelId,
  selectedChannelDetail,
  isAdmin,
  onSelectChannel,
  onChannelCreated,
  onChannelDeleted,
  onChanged,
}: Props) {
  const departmentCatalog = useDepartmentCatalog()
  const [cameras, setCameras] = useState<Omit<AiVisionCamera, 'sort_order'>[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('通道配置修改后请保存。')
  const [createDialog, dispatchCreateDialog] = useReducer(
    channelCreateDialogReducer,
    initialChannelCreateDialogState,
  )
  const [channelName, setChannelName] = useState('')
  const [detectionConfigDraft, setDetectionConfigDraft] = useState<LogisticsChannelDetectionConfig | null>(null)
  const [alarmDraft, setAlarmDraft] = useState<LogisticsChannelAlarmDraft | null>(null)
  const [existingCameraId, setExistingCameraId] = useState('')
  const [moveExisting, setMoveExisting] = useState(false)
  const [cameraDialogOpen, setCameraDialogOpen] = useState(false)
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null)
  const [cameraRoi, setCameraRoi] = useState<LogisticsCameraRoiResponse | null>(null)
  const [roiJson, setRoiJson] = useState('[]')
  const [boundCameraIds, setBoundCameraIds] = useState<ReadonlySet<number>>(new Set())
  const [channelMemberCounts, setChannelMemberCounts] = useState<Record<number, ChannelMemberCount>>({})
  const [membershipsLoaded, setMembershipsLoaded] = useState(false)
  const [membershipRevision, refreshMemberships] = useReducer((value: number) => value + 1, 0)
  const channelSelection = useMemo(() => ({ feature, department, selectedChannelId }), [feature, department, selectedChannelId])
  const currentChannelSelection = useRef(channelSelection)
  currentChannelSelection.current = channelSelection
  const hydratedChannelSelection = useRef<typeof channelSelection | null>(null)
  const membershipLoadRef = useRef<MembershipLoadIdentity>({ generation: 0, feature, channelIdsKey: '' })

  const members = useMemo(
    () => [...(selectedChannelDetail?.members ?? [])].sort((a, b) => a.sort_order - b.sort_order),
    [selectedChannelDetail],
  )
  const cameraById = useMemo(() => new Map(cameras.map((camera) => [camera.camera_id, camera])), [cameras])
  const selectedCamera = selectedCameraId === null ? undefined : cameraById.get(selectedCameraId)
  const selectedChannelDetailId = selectedChannelDetail?.id ?? null
  const channelIdsKey = useMemo(() => channels.map((channel) => channel.id).sort((a, b) => a - b).join(','), [channels])
  const membershipContextRef = useRef({ feature, channelIdsKey })
  membershipContextRef.current = { feature, channelIdsKey }
  const currentMemberIds = useMemo(() => new Set(members.map((member) => member.camera_id)), [members])
  const departmentCameras = cameras.filter((camera) => camera.department === department)
  const availableCameras = membershipsLoaded ? filterBindableCameras(departmentCameras, boundCameraIds) : []
  const movableCameras = membershipsLoaded
    ? departmentCameras.filter((camera) => boundCameraIds.has(camera.camera_id) && !currentMemberIds.has(camera.camera_id))
    : []
  const existingCameraOptions = moveExisting ? movableCameras : availableCameras

  useEffect(() => {
    const request: MembershipLoadIdentity = {
      generation: membershipLoadRef.current.generation + 1,
      feature,
      channelIdsKey,
    }
    membershipLoadRef.current = request
    const controller = new AbortController()
    const channelIds = channelIdsKey ? channelIdsKey.split(',').map(Number) : []
    setBoundCameraIds(new Set())
    setChannelMemberCounts({})
    setMembershipsLoaded(false)
    const load = async () => {
      try {
        const details = await Promise.all(channelIds.map((channelId) => (
          getLogisticsChannel(feature, channelId, { signal: controller.signal })
        )))
        const current = { ...membershipLoadRef.current, ...membershipContextRef.current }
        if (!isMembershipLoadCurrent(request, current)) return
        setBoundCameraIds(collectBoundCameraIds(details))
        setChannelMemberCounts(collectChannelMemberCounts(details))
        setMembershipsLoaded(true)
      } catch (reason) {
        const current = { ...membershipLoadRef.current, ...membershipContextRef.current }
        if (controller.signal.aborted || !isMembershipLoadCurrent(request, current)) return
        setMessage(`通道成员读取失败：${messageOf(reason)}`)
      }
    }
    void load()
    return () => {
      controller.abort()
      if (isMembershipLoadCurrent(request, membershipLoadRef.current)) {
        membershipLoadRef.current = { ...request, generation: request.generation + 1 }
      }
    }
  }, [channelIdsKey, feature, membershipRevision])

  useEffect(() => {
    if (!isAdmin) {
      setCameras([])
      return
    }
    let active = true
    const load = async () => {
      try {
        const result = await getAiVisionCameras(department)
        if (active) setCameras(result)
      } catch (reason) {
        if (active) setMessage(`摄像头列表读取失败：${messageOf(reason)}`)
      }
    }
    void load()
    const refresh = () => void load()
    window.addEventListener('aivision:cameras-changed', refresh)
    return () => {
      active = false
      window.removeEventListener('aivision:cameras-changed', refresh)
    }
  }, [department, isAdmin])

  useEffect(() => {
    if (isAdmin || !selectedChannelDetail) return
    const controller = new AbortController()
    Promise.all(selectedChannelDetail.members.map((member) => (
      getLogisticsCameraRoi(
        feature,
        selectedChannelDetail.id,
        member.camera_id,
        { signal: controller.signal },
      )
    )))
      .then((results) => {
        if (controller.signal.aborted) return
        setCameras(results.map(({ camera }) => ({
          id: String(camera.id),
          camera_id: camera.id,
          name: camera.name,
          shm_name: camera.shm_name,
          url: '',
          enabled: camera.enable,
          functions: {},
          department,
        })))
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setMessage(`通道摄像头读取失败：${messageOf(reason)}`)
      })
    return () => controller.abort()
  }, [department, feature, isAdmin, selectedChannelDetail])

  useEffect(() => {
    if (!selectedChannelDetail || selectedChannelDetail.id !== channelSelection.selectedChannelId) {
      hydratedChannelSelection.current = null
      setChannelName('')
      setDetectionConfigDraft(null)
      setAlarmDraft(null)
      return
    }
    // 同一通道的轮询或保存刷新不能覆盖任一 Tab 的未保存草稿。
    if (hydratedChannelSelection.current === channelSelection) return
    hydratedChannelSelection.current = channelSelection
    const { detection, alarm } = splitChannelConfig(selectedChannelDetail.config)
    setChannelName(selectedChannelDetail.name)
    setDetectionConfigDraft(detection)
    setAlarmDraft(alarm)
  }, [channelSelection, selectedChannelDetail])

  useEffect(() => {
    setSelectedCameraId((current) => members.some((member) => member.camera_id === current) ? current : members[0]?.camera_id ?? null)
  }, [members])

  useEffect(() => {
    if (selectedCameraId === null || selectedChannelDetailId === null) {
      setCameraRoi(null)
      setRoiJson('[]')
      return
    }
    let active = true
    setCameraRoi(null)
    getLogisticsCameraRoi(feature, selectedChannelDetailId, selectedCameraId)
      .then((result) => {
        if (!active) return
        setCameraRoi(result)
        setRoiJson(JSON.stringify(result.roi_pos))
      })
      .catch((reason) => active && setMessage(`逐路 ROI 读取失败：${messageOf(reason)}`))
    return () => { active = false }
  }, [feature, selectedCameraId, selectedChannelDetailId])

  const invalidateMemberships = () => {
    membershipLoadRef.current = {
      ...membershipLoadRef.current,
      generation: membershipLoadRef.current.generation + 1,
    }
    setBoundCameraIds(new Set())
    setChannelMemberCounts({})
    setMembershipsLoaded(false)
    refreshMemberships()
  }

  const run = async (action: () => Promise<unknown>, success: string, reloadMemberships = false) => {
    if (!isAdmin || busy) return
    setBusy(true)
    try {
      await action()
      if (reloadMemberships) {
        invalidateMemberships()
      }
      setMessage(success)
      onChanged()
    } catch (reason) {
      setMessage(`操作失败：${messageOf(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const createChannel = async () => {
    const name = createDialog.name.trim()
    if (!isAdmin || createDialog.submitting || !name) return
    dispatchCreateDialog({ type: 'submit' })
    try {
      const result = await createLogisticsChannel(feature, { name, department })
      onChannelCreated(result)
      onChanged()
      setMessage('物流通道已新增。')
      dispatchCreateDialog({ type: 'success' })
    } catch (reason) {
      dispatchCreateDialog({ type: 'failure', error: messageOf(reason) })
    }
  }

  const saveDetectionConfig = () => {
    if (!selectedChannelDetail || !detectionConfigDraft || hydratedChannelSelection.current !== channelSelection) return
    const name = channelName.trim()
    if (!name || name.length > 100) {
      setMessage('通道名称不能为空，且不得超过 100 个字符。')
      return
    }
    const start = detectionTimeSeconds(detectionConfigDraft.detection_start)
    const end = detectionTimeSeconds(detectionConfigDraft.detection_end)
    if (start === null || end === null || start >= end) {
      setMessage('请填写有效的检测时间，开始时间必须早于结束时间。')
      return
    }
    if (!Number.isFinite(detectionConfigDraft.confidence_threshold)
      || detectionConfigDraft.confidence_threshold < 0 || detectionConfigDraft.confidence_threshold > 1) {
      setMessage('人体检测阈值必须在 0～1 之间。')
      return
    }
    if (!Number.isFinite(detectionConfigDraft.model_iou_threshold) || detectionConfigDraft.model_iou_threshold < 0 || detectionConfigDraft.model_iou_threshold > 1
      || !Number.isInteger(detectionConfigDraft.min_box_area) || detectionConfigDraft.min_box_area < 0
      || !Number.isFinite(detectionConfigDraft.min_aspect_ratio) || detectionConfigDraft.min_aspect_ratio < 0
      || !Number.isFinite(detectionConfigDraft.max_aspect_ratio) || detectionConfigDraft.max_aspect_ratio < detectionConfigDraft.min_aspect_ratio
      || !Number.isFinite(detectionConfigDraft.cap_interval) || detectionConfigDraft.cap_interval <= 0) {
      setMessage('请检查模型 IOU（0～1）、最小面积（非负整数）、宽高比范围及处理间隔（大于 0 秒）。')
      return
    }
    if (!Number.isFinite(detectionConfigDraft.empty_grace_seconds) || detectionConfigDraft.empty_grace_seconds < 0
      || !Number.isFinite(detectionConfigDraft.multi_grace_seconds) || detectionConfigDraft.multi_grace_seconds < 0) {
      setMessage('无人、多人持续时间必须非负。')
      return
    }
    void run(async () => {
      const saved = await updateLogisticsChannel(feature, selectedChannelDetail.id, {
        name,
        config: {
          ...detectionConfigDraft,
          detection_start: timeForApi(detectionConfigDraft.detection_start),
          detection_end: timeForApi(detectionConfigDraft.detection_end),
        },
      })
      if (currentChannelSelection.current === channelSelection) {
        setDetectionConfigDraft(splitChannelConfig(saved.config).detection)
        setChannelName(saved.name)
      }
    }, '检测参数已保存。')
  }

  const saveAlarmConfig = () => {
    if (!selectedChannelDetail || !alarmDraft || hydratedChannelSelection.current !== channelSelection) return
    if (!Number.isFinite(alarmDraft.alarm_interval) || alarmDraft.alarm_interval <= 0) {
      setMessage('报警间隔必须大于 0 秒。')
      return
    }
    const hornError = validateHornBinding(toFeatureAlarm(alarmDraft.alarm).horn)
    if (hornError) { setMessage(hornError); return }
    void run(async () => {
      const saved = await updateLogisticsChannel(feature, selectedChannelDetail.id, {
        config: { ...alarmDraft },
      })
      if (currentChannelSelection.current === channelSelection) {
        setAlarmDraft(splitChannelConfig(saved.config).alarm)
      }
    }, '报警推送配置已保存。')
  }

  const setChannelEnabled = (channel: LogisticsChannel, enabled: boolean) => {
    void run(
      () => updateLogisticsChannel(feature, channel.id, { enabled }),
      enabled ? `物流通道“${channel.name}”已启用。` : `物流通道“${channel.name}”已停用。`,
    )
  }

  const deleteChannelById = (channelId: number, channelDisplayName: string) => {
    if (!window.confirm(`确定删除物流通道“${channelDisplayName}”吗？摄像头资源不会被删除。`)) return
    void run(async () => {
      await deleteLogisticsChannel(feature, channelId)
      onChannelDeleted(channelId)
    }, '物流通道已删除。')
  }

  const addExisting = () => {
    if (!selectedChannelDetail || !existingCameraId) return
    const cameraId = Number(existingCameraId)
    void run(async () => {
      if (moveExisting) {
        await moveLogisticsChannelCamera(feature, selectedChannelDetail.id, cameraId)
      } else {
        await addLogisticsChannelCamera(feature, selectedChannelDetail.id, { camera_id: cameraId })
      }
      setExistingCameraId('')
    }, moveExisting ? '摄像头已移动至当前通道。' : '已有摄像头已绑定。', true)
  }

  const createCameraAndBind = async (payload: LogisticsCameraCreateInput) => {
    if (!isAdmin) throw new Error('只有管理员可以新建摄像头。')
    const channelId = selectedChannelDetail?.id
    if (channelId === undefined) throw new Error('请先选择物流通道。')
    if (busy) throw new Error('正在处理其他操作，请稍后再试。')
    if (members.length >= 9) throw new Error('当前通道最多绑定 9 路摄像头。')

    setBusy(true)
    try {
      await addLogisticsChannelCamera(feature, channelId, payload)
      invalidateMemberships()
      setMessage('摄像头已新建并绑定。')
      onChanged()
      window.dispatchEvent(new Event('aivision:cameras-changed'))
      notifyPlatformCamerasChanged()
    } catch (reason) {
      setMessage(`操作失败：${messageOf(reason)}`)
      throw reason
    } finally {
      setBusy(false)
    }
  }

  const moveMember = (cameraId: number, offset: -1 | 1) => {
    if (!selectedChannelDetail) return
    const current = members.findIndex((member) => member.camera_id === cameraId)
    const target = current + offset
    if (current < 0 || target < 0 || target >= members.length) return
    const orderedIds = members.map((member) => member.camera_id)
    ;[orderedIds[current], orderedIds[target]] = [orderedIds[target], orderedIds[current]]
    void run(() => reorderLogisticsChannelCameras(feature, selectedChannelDetail.id, orderedIds), '摄像头顺序已更新。')
  }

  const removeMember = (cameraId: number) => {
    if (!selectedChannelDetail) return
    const cameraName = cameraById.get(cameraId)?.name ?? `摄像头 #${cameraId}`
    confirmMembershipRemoval(
      () => window.confirm(removalConfirmationText(cameraName, selectedChannelDetail.name)),
      () => void run(
        () => removeLogisticsChannelCamera(feature, selectedChannelDetail.id, cameraId),
        '摄像头已从通道移除。',
        true,
      ),
    )
  }

  const setMemberEnabled = (cameraId: number, enabled: boolean) => {
    if (!selectedChannelDetail) return
    void run(
      () => setLogisticsChannelCameraEnabled(
        feature,
        selectedChannelDetail.id,
        cameraId,
        enabled,
      ),
      enabled ? '摄像头已启用。' : '摄像头已停用。',
      true,
    )
  }

  const cameraSelection = useRef('')
  cameraSelection.current = `${department}:${feature}:${selectedChannelDetailId}:${selectedCameraId}`

  const saveCameraRoi = () => {
    if (!selectedChannelDetail || !selectedCamera || cameraRoi?.camera.id !== selectedCamera.camera_id) return
    const selection = cameraSelection.current
    void run(async () => {
      const saved = await updateLogisticsCameraRoi(feature, selectedChannelDetail.id, selectedCamera.camera_id, {
        roi_pos: parseNormalizedRoi(roiJson),
      })
      if (cameraSelection.current === selection) {
        setCameraRoi(saved)
        setRoiJson(JSON.stringify(saved.roi_pos))
      }
    }, '当前摄像头 ROI 已保存。')
  }

  return (
    <div className="space-y-5">
      {!isAdmin ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">当前为 viewer 只读模式，只有管理员可以修改物流通道配置。</div> : null}

      <DetectionConfigTabs defaultValue="channels" className="space-y-5"
        tabs={<>
          <DetectionConfigTab value="channels" icon={Layers3}>通道管理</DetectionConfigTab>
          <DetectionConfigTab value="members" icon={Camera}>摄像头</DetectionConfigTab>
          <DetectionConfigTab value="params" icon={SlidersHorizontal}>检测参数</DetectionConfigTab>
          <DetectionConfigTab value="roi" icon={Crosshair}>ROI 配置</DetectionConfigTab>
          <DetectionConfigTab value="alarm" icon={Bell}>报警推送</DetectionConfigTab>
        </>}
      >

        <TabsContent value="channels" className="mt-0">
          <Card className={DETECTION_CONFIG_CARD_CLASS}>
            <DetectionConfigCardHeader
              icon={Layers3}
              tone="blue"
              title="通道管理"
              description="选择需要配置的物流通道，或新增、删除通道。"
              actions={isAdmin ? (
                <Button onClick={() => dispatchCreateDialog({ type: 'open' })} disabled={busy}>
                  <Plus className="h-4 w-4" />添加通道
                </Button>
              ) : null}
            />
            <DetectionConfigCardContent>
              {channels.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">暂无物流通道</div>
              ) : (
                <div className="space-y-2">
                  {channels.map((channel) => {
                    const selected = selectedChannelId === channel.id
                    const memberCount = channelMemberCounts[channel.id]
                    return (
                      <div key={channel.id} className={`flex flex-col items-stretch gap-2 rounded-xl border px-3 py-3 transition-colors sm:flex-row sm:items-center sm:gap-3 ${selected ? 'border-blue-300 bg-blue-50/80 shadow-sm dark:border-blue-800 dark:bg-blue-950/30' : 'border-[#E8ECF5] bg-white hover:border-blue-200 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800/70'}`}>
                        <Button variant="ghost" className="w-full min-w-0 justify-start px-2 sm:w-auto sm:flex-1" onClick={() => onSelectChannel(channel.id)}>
                          <span className="truncate font-semibold">{channel.name}</span>
                          <span className="ml-2 text-xs text-slate-500">{departmentCatalog.labels[channel.department] ?? channel.department}</span>
                        </Button>
                        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
                          <Badge variant={channel.enabled ? 'default' : 'secondary'}>{channel.enabled ? '已启用' : '已停用'}</Badge>
                          <Badge variant="outline">{memberCount ? `${memberCount.enabled}/${memberCount.total} 路` : '--/-- 路'}</Badge>
                          {selected ? <Badge variant="outline">当前通道</Badge> : null}
                          {isAdmin ? (
                            <>
                              <Switch
                                checked={channel.enabled}
                                aria-label={channel.enabled ? '停用通道' : '启用通道'}
                                onCheckedChange={(enabled) => setChannelEnabled(channel, enabled)}
                                disabled={busy}
                              />
                              <Button size="sm" variant="ghost" className="text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:hover:bg-rose-950/40" onClick={() => deleteChannelById(channel.id, channel.name)} disabled={busy}>
                                <Trash2 className="h-4 w-4" />删除
                              </Button>
                            </>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
              <p className="mt-4 rounded-xl bg-[#F5F7FA] px-4 py-3 text-sm text-slate-500 dark:bg-slate-950/40 dark:text-slate-400">{message}</p>
            </DetectionConfigCardContent>
          </Card>
        </TabsContent>

        {!selectedChannelDetail || !detectionConfigDraft || !alarmDraft ? (
          ['members', 'params', 'roi', 'alarm'].map((tab) => (
            <TabsContent key={tab} value={tab}>
              <div className="rounded-2xl border border-dashed border-slate-300 px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">请先在“通道管理”中选择物流通道进行配置。</div>
            </TabsContent>
          ))
        ) : (
          <>

            <TabsContent value="members" className="mt-0 space-y-5">
              <Card className={DETECTION_CONFIG_CARD_CLASS}>
                <DetectionConfigCardHeader icon={Camera} tone="blue" title="摄像头" description="管理当前通道中的摄像头、顺序与启用状态。" actions={<Badge variant="outline">{members.length}/9 路 · 最多 9 路</Badge>} />
                <DetectionConfigCardContent className="space-y-3">
                  {members.length === 0 ? <p className="text-sm text-slate-500">当前通道没有摄像头，不会触发无人告警。</p> : members.map((member, index) => {
                    const camera = cameraById.get(member.camera_id)
                    return (
                      <div key={member.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-[#E8ECF5] bg-white p-3 transition hover:border-blue-200 hover:shadow-sm dark:border-slate-800 dark:bg-slate-900">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-300"><Camera className="h-4 w-4" /></span>
                        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{camera?.name ?? `摄像头 #${member.camera_id}`}</p><p className="truncate font-mono text-xs text-slate-500">{camera?.shm_name ?? '正在读取摄像头信息'}</p></div>
                        <Badge variant={member.enabled ? 'default' : 'secondary'}>{member.enabled ? '已启用' : '已停用'}</Badge>
                        <Switch checked={member.enabled} aria-label={member.enabled ? '停用' : '启用'} onCheckedChange={(enabled) => setMemberEnabled(member.camera_id, enabled)} disabled={!isAdmin || busy} />
                        <Button size="sm" variant="outline" aria-label="上移" onClick={() => moveMember(member.camera_id, -1)} disabled={!isAdmin || busy || index === 0}><ArrowUp className="h-4 w-4" />上移</Button>
                        <Button size="sm" variant="outline" aria-label="下移" onClick={() => moveMember(member.camera_id, 1)} disabled={!isAdmin || busy || index === members.length - 1}><ArrowDown className="h-4 w-4" />下移</Button>
                        <Button size="sm" variant="outline" className="text-rose-600" onClick={() => removeMember(member.camera_id)} disabled={!isAdmin || busy}><Trash2 className="h-4 w-4" />移除</Button>
                      </div>
                    )
                  })}
                </DetectionConfigCardContent>
              </Card>

              <Card className={DETECTION_CONFIG_CARD_CLASS}>
                <DetectionConfigCardHeader icon={Plus} tone="blue" title="绑定摄像头" description="选择已有摄像头，或新建摄像头并直接绑定至当前物流通道。" />
                <DetectionConfigCardContent>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="space-y-3 rounded-xl border border-[#E8ECF5] bg-[#FAFBFE] p-4 dark:border-slate-800 dark:bg-slate-950/40">
                      <div>
                        <h3 className="text-sm font-semibold">绑定已有摄像头</h3>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">从平台摄像头列表中选择并加入当前通道。</p>
                      </div>
                      <Label htmlFor="logistics-existing-camera">{moveExisting ? '从其他通道移动摄像头' : '可绑定摄像头'}</Label>
                      <Select value={existingCameraId} onValueChange={setExistingCameraId} disabled={!isAdmin || busy || members.length >= 9}>
                        <SelectTrigger id="logistics-existing-camera"><SelectValue placeholder={membershipsLoaded ? '选择已有摄像头' : '正在读取通道成员'} /></SelectTrigger>
                      <SelectContent showScrollButtons={false}>{existingCameraOptions.map((camera) => <SelectItem key={camera.camera_id} value={String(camera.camera_id)}>{camera.name}</SelectItem>)}</SelectContent>
                      </Select>
                      <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300"><Switch checked={moveExisting} onCheckedChange={(checked) => { setMoveExisting(checked); setExistingCameraId('') }} disabled={!isAdmin || busy} />摄像头已属于本功能其他通道时，移动至当前通道</label>
                      <Button onClick={addExisting} disabled={!isAdmin || busy || !existingCameraId || members.length >= 9}>{moveExisting ? '移动至当前通道' : '绑定已有摄像头'}</Button>
                    </div>
                    <div className="flex flex-col justify-between gap-4 rounded-xl border border-[#E8ECF5] bg-[#FAFBFE] p-4 dark:border-slate-800 dark:bg-slate-950/40">
                      <div>
                        <h3 className="text-sm font-semibold">新建摄像头并绑定</h3>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">填写摄像头名称、FPS 和 RTSP 地址后加入当前通道。</p>
                      </div>
                      <Button
                        className="w-full"
                        onClick={() => setCameraDialogOpen(true)}
                        disabled={!isAdmin || busy || !selectedChannelDetail || members.length >= 9}
                      >
                        <Plus className="h-4 w-4" />新建摄像头并绑定
                      </Button>
                    </div>
                  </div>
                </DetectionConfigCardContent>
              </Card>
            </TabsContent>

            <TabsContent value="roi" className="mt-0 space-y-5">
              <Card className={DETECTION_CONFIG_CARD_CLASS}>
                <DetectionConfigCardHeader icon={Camera} tone="blue" title="逐路 ROI 摄像头" description="选择通道摄像头后，直接在下方现有画布中绘制 ROI。" />
                <DetectionConfigCardContent className="space-y-2"><Label htmlFor="logistics-roi-camera">通道摄像头</Label><Select value={selectedCameraId === null ? '' : String(selectedCameraId)} onValueChange={(value) => setSelectedCameraId(Number(value))}><SelectTrigger id="logistics-roi-camera"><SelectValue placeholder="选择通道摄像头" /></SelectTrigger><SelectContent>{members.map((member) => <SelectItem key={member.camera_id} value={String(member.camera_id)}>{cameraById.get(member.camera_id)?.name ?? `摄像头 #${member.camera_id}`}</SelectItem>)}</SelectContent></Select></DetectionConfigCardContent>
              </Card>
              <AiVisionRoiEditor title="物流通道逐路 ROI 绘制" cameraKey={selectedCamera?.shm_name ?? ''} roiJson={roiJson} disabled={!isAdmin || busy || !selectedCamera || cameraRoi?.camera.id !== selectedCamera.camera_id} saving={busy} message={message} onChange={setRoiJson} onSave={saveCameraRoi} />
            </TabsContent>

            <TabsContent value="params" className="mt-0 space-y-5">
              <Card className={DETECTION_CONFIG_CARD_CLASS}>
                <DetectionConfigCardHeader icon={SlidersHorizontal} tone="emerald" title="检测参数" description="同一通道的所有摄像头统一使用以下检测策略，ROI 按摄像头独立配置。" />
                <DetectionConfigCardContent className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2"><Label htmlFor="logistics-channel-name">物流通道名称</Label><Input id="logistics-channel-name" value={channelName} onChange={(event) => setChannelName(event.target.value)} disabled={!isAdmin || busy} /></div>
                  <ConfigNumber label="每日检测开始时间" id="logistics-detection-start" type="time" value={timeForInput(detectionConfigDraft.detection_start)} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, detection_start: value })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="每日检测结束时间" id="logistics-detection-end" type="time" value={timeForInput(detectionConfigDraft.detection_end)} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, detection_end: value })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="人体检测阈值" id="logistics-confidence-threshold" value={String(detectionConfigDraft.confidence_threshold)} min={0} max={1} step={0.01} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, confidence_threshold: Number(value) })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="模型检测 IOU（0～1）" id="logistics-channel-iou" value={String(detectionConfigDraft.model_iou_threshold)} min={0} max={1} step={0.01} disabled={!isAdmin || busy} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, model_iou_threshold: Number(value) })} />
                  <ConfigNumber label="最小检测框面积（像素平方）" id="logistics-channel-area" value={String(detectionConfigDraft.min_box_area)} min={0} step={1} disabled={!isAdmin || busy} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, min_box_area: Number(value) })} />
                  <ConfigNumber label="最小宽高比（宽/高）" id="logistics-channel-min-aspect" value={String(detectionConfigDraft.min_aspect_ratio)} min={0} step={0.1} disabled={!isAdmin || busy} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, min_aspect_ratio: Number(value) })} />
                  <ConfigNumber label="最大宽高比（宽/高）" id="logistics-channel-max-aspect" value={String(detectionConfigDraft.max_aspect_ratio)} min={0} step={0.1} disabled={!isAdmin || busy} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, max_aspect_ratio: Number(value) })} />
                  <ConfigNumber label="画面处理间隔（秒，大于 0）" id="logistics-channel-interval" value={String(detectionConfigDraft.cap_interval)} min={0} step={0.01} disabled={!isAdmin || busy} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, cap_interval: Number(value) })} />
                  <ConfigNumber label="无人持续时间（秒）" id="logistics-empty-grace" value={String(detectionConfigDraft.empty_grace_seconds)} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, empty_grace_seconds: Number(value) })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="多人持续时间（秒）" id="logistics-multi-grace" value={String(detectionConfigDraft.multi_grace_seconds)} onChange={(value) => setDetectionConfigDraft({ ...detectionConfigDraft, multi_grace_seconds: Number(value) })} disabled={!isAdmin || busy} />
                </DetectionConfigCardContent>
              </Card>
              <DetectionSaveBar message={message} saving={busy} disabled={!isAdmin || !channelName.trim()} onSave={saveDetectionConfig} saveLabel="保存检测参数" />
            </TabsContent>

            <TabsContent value="alarm" className="mt-0 space-y-5">
              <AlarmPushConfig
                showSql
                alarmInterval={String(alarmDraft.alarm_interval)}
                onAlarmIntervalChange={(value) => setAlarmDraft({ ...alarmDraft, alarm_interval: Number(value) })}
                alarm={toFeatureAlarm(alarmDraft.alarm)}
                disabled={!isAdmin || busy}
                saving={busy}
                message={message}
                onChange={(alarm) => setAlarmDraft({ ...alarmDraft, alarm: toLogisticsAlarm(alarm) })}
                onSave={saveAlarmConfig}
              />
            </TabsContent>
          </>
        )}
      </DetectionConfigTabs>

      {cameraDialogOpen ? (
        <LogisticsCameraCreateDialog
          onClose={() => setCameraDialogOpen(false)}
          onSubmit={createCameraAndBind}
        />
      ) : null}

      <Dialog open={createDialog.open} onOpenChange={(open) => {
        if (open) dispatchCreateDialog({ type: 'open' })
        else if (!createDialog.submitting) dispatchCreateDialog({ type: 'close' })
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>添加通道</DialogTitle>
            <DialogDescription>在当前事业部下添加物流通道。添加后将自动选中新通道。</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="logistics-new-channel-name">通道名称</Label>
            <Input
              id="logistics-new-channel-name"
              value={createDialog.name}
              onChange={(event) => dispatchCreateDialog({ type: 'change-name', name: event.target.value })}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void createChannel()
              }}
              placeholder="例如：一号物流通道"
              disabled={createDialog.submitting}
              autoFocus
            />
            <Label htmlFor="logistics-new-channel-department">所属事业部</Label>
            <Input
              id="logistics-new-channel-department"
              value={departmentCatalog.labels[department] ?? department}
              readOnly
            />
            {createDialog.error ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-400">添加失败：{createDialog.error}</p> : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => dispatchCreateDialog({ type: 'close' })} disabled={createDialog.submitting}>取消</Button>
            <Button onClick={() => void createChannel()} disabled={createDialog.submitting || !createDialog.name.trim()}>{createDialog.submitting ? '添加中…' : '确认添加'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ConfigNumber({ label, id, value, onChange, disabled, type = 'number', min = 0, max, step = 0.1 }: { label: string; id: string; value: string; onChange: (value: string) => void; disabled: boolean; type?: 'number' | 'time'; min?: number; max?: number; step?: number }) {
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} type={type} min={type === 'number' ? min : undefined} max={type === 'number' ? max : undefined} step={type === 'number' ? step : undefined} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} /></div>
}
