import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Camera, Plus, Save, Settings2, Trash2 } from 'lucide-react'

import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'

import {
  addLogisticsChannelCamera,
  createLogisticsChannel,
  deleteLogisticsChannel,
  getLogisticsChannel,
  getLogisticsCameraConfig,
  moveLogisticsChannelCamera,
  removeLogisticsChannelCamera,
  reorderLogisticsChannelCameras,
  setLogisticsChannelCameraEnabled,
  updateLogisticsCameraConfig,
  updateLogisticsChannel,
  updateLogisticsChannelConfig,
} from './api'
import type {
  LogisticsCameraConfigResponse,
  LogisticsChannel,
  LogisticsChannelConfig,
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

type Props = {
  feature: LogisticsFeatureName
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

function messageOf(reason: unknown) {
  return reason instanceof Error ? reason.message : String(reason)
}

function roiPayload(raw: string) {
  const parsed = JSON.parse(raw || '[]') as unknown
  if (!Array.isArray(parsed) || parsed.length === 0) return []
  return Array.isArray(parsed[0]) && typeof parsed[0][0] === 'number' ? [parsed] : parsed
}

export function LogisticsChannelConfigView({
  feature,
  channels,
  selectedChannelId,
  selectedChannelDetail,
  isAdmin,
  onSelectChannel,
  onChannelCreated,
  onChannelDeleted,
  onChanged,
}: Props) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('通道配置修改后请保存。')
  const [createDialog, dispatchCreateDialog] = useReducer(
    channelCreateDialogReducer,
    initialChannelCreateDialogState,
  )
  const [channelName, setChannelName] = useState('')
  const [config, setConfig] = useState<LogisticsChannelConfig | null>(null)
  const [existingCameraId, setExistingCameraId] = useState('')
  const [moveExisting, setMoveExisting] = useState(false)
  const [cameraDialogOpen, setCameraDialogOpen] = useState(false)
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null)
  const [cameraConfig, setCameraConfig] = useState<LogisticsCameraConfigResponse | null>(null)
  const [roiJson, setRoiJson] = useState('[]')
  const [boundCameraIds, setBoundCameraIds] = useState<ReadonlySet<number>>(new Set())
  const [channelMemberCounts, setChannelMemberCounts] = useState<Record<number, ChannelMemberCount>>({})
  const [membershipsLoaded, setMembershipsLoaded] = useState(false)
  const [membershipRevision, refreshMemberships] = useReducer((value: number) => value + 1, 0)
  const hydratedChannelId = useRef<number | null>(null)
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
  const availableCameras = membershipsLoaded ? filterBindableCameras(cameras, boundCameraIds) : []
  const movableCameras = membershipsLoaded
    ? cameras.filter((camera) => boundCameraIds.has(camera.camera_id) && !currentMemberIds.has(camera.camera_id))
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
        const result = await getAiVisionCameras()
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
  }, [isAdmin])

  useEffect(() => {
    if (isAdmin || !selectedChannelDetail) return
    const controller = new AbortController()
    Promise.all(selectedChannelDetail.members.map((member) => (
      getLogisticsCameraConfig(
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
        })))
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setMessage(`通道摄像头读取失败：${messageOf(reason)}`)
      })
    return () => controller.abort()
  }, [feature, isAdmin, selectedChannelDetail])

  useEffect(() => {
    const nextChannelId = selectedChannelDetail?.id ?? null
    if (hydratedChannelId.current === nextChannelId) return
    hydratedChannelId.current = nextChannelId
    setChannelName(selectedChannelDetail?.name ?? '')
    setConfig(selectedChannelDetail?.config ?? null)
  }, [selectedChannelDetail])

  useEffect(() => {
    setSelectedCameraId((current) => members.some((member) => member.camera_id === current) ? current : members[0]?.camera_id ?? null)
  }, [members])

  useEffect(() => {
    if (selectedCameraId === null || selectedChannelDetailId === null) {
      setCameraConfig(null)
      setRoiJson('[]')
      return
    }
    let active = true
    setCameraConfig(null)
    getLogisticsCameraConfig(feature, selectedChannelDetailId, selectedCameraId)
      .then((result) => {
        if (!active) return
        setCameraConfig(result)
        setRoiJson(JSON.stringify(result.config.value.roi_pos ?? []))
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
      const result = await createLogisticsChannel(feature, { name })
      onChannelCreated(result)
      onChanged()
      setMessage('物流通道已新增。')
      dispatchCreateDialog({ type: 'success' })
    } catch (reason) {
      dispatchCreateDialog({ type: 'failure', error: messageOf(reason) })
    }
  }

  const saveChannel = () => {
    if (!selectedChannelDetail || !config) return
    void run(async () => {
      await updateLogisticsChannel(feature, selectedChannelDetail.id, {
        name: channelName.trim(),
        enabled: config.enabled,
      })
      await updateLogisticsChannelConfig(feature, selectedChannelDetail.id, {
        ...config,
        detection_start: timeForApi(config.detection_start),
        detection_end: timeForApi(config.detection_end),
      })
    }, '通道规则已保存。')
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

  const saveRoi = () => {
    if (!selectedChannelDetail || !selectedCamera || !cameraConfig) return
    void run(() => updateLogisticsCameraConfig(
      feature,
      selectedChannelDetail.id,
      selectedCamera.camera_id,
      {
      ...cameraConfig.config,
      value: { ...cameraConfig.config.value, roi_pos: roiPayload(roiJson) },
      },
    ), '当前摄像头 ROI 已保存。')
  }

  return (
    <div className="space-y-5">
      {!isAdmin ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">当前为 viewer 只读模式，只有管理员可以修改物流通道配置。</div> : null}

      <div>
        <h2 className="text-xl font-bold text-slate-950 dark:text-slate-50">配置管理</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">管理物流通道、摄像头成员、逐路 ROI 与通道级检测规则。</p>
      </div>

      <Tabs defaultValue="channels" className="space-y-5">
        <TabsList className="grid h-auto w-full grid-cols-2 rounded-xl border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900 md:grid-cols-4">
          <TabsTrigger value="channels">通道管理</TabsTrigger>
          <TabsTrigger value="members">摄像头成员</TabsTrigger>
          <TabsTrigger value="roi">逐路 ROI</TabsTrigger>
          <TabsTrigger value="rules">通道规则</TabsTrigger>
        </TabsList>

        <TabsContent value="channels" className="mt-0">
          <Card className="border-slate-200 shadow-sm dark:border-slate-800">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="space-y-1">
                <CardTitle>通道管理</CardTitle>
                <CardDescription>选择需要配置的物流通道，或新增、删除通道。</CardDescription>
              </div>
              {isAdmin ? (
                <Button onClick={() => dispatchCreateDialog({ type: 'open' })} disabled={busy}>
                  <Plus className="h-4 w-4" />添加通道
                </Button>
              ) : null}
            </CardHeader>
            <CardContent>
              {channels.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">暂无物流通道</div>
              ) : (
                <div className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                  {channels.map((channel) => {
                    const selected = selectedChannelId === channel.id
                    const memberCount = channelMemberCounts[channel.id]
                    return (
                      <div key={channel.id} className={`flex flex-col items-stretch gap-2 px-3 py-3 transition-colors sm:flex-row sm:items-center sm:gap-3 ${selected ? 'bg-blue-50 dark:bg-blue-950/30' : 'bg-white hover:bg-slate-50 dark:bg-slate-900 dark:hover:bg-slate-800/70'}`}>
                        <Button variant="ghost" className="w-full min-w-0 justify-start px-2 sm:w-auto sm:flex-1" onClick={() => onSelectChannel(channel.id)}>
                          <span className="truncate font-semibold">{channel.name}</span>
                        </Button>
                        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
                          <Badge variant={channel.enabled ? 'default' : 'secondary'}>{channel.enabled ? '已启用' : '已停用'}</Badge>
                          <Badge variant="outline">{memberCount ? `${memberCount.enabled}/${memberCount.total} 路` : '--/-- 路'}</Badge>
                          {selected ? <Badge variant="outline">当前通道</Badge> : null}
                          {isAdmin ? (
                            <Button size="sm" variant="ghost" className="ml-auto text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:hover:bg-rose-950/40 sm:ml-0" onClick={() => deleteChannelById(channel.id, channel.name)} disabled={busy}>
                              <Trash2 className="h-4 w-4" />删除
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
              <p className="mt-4 text-sm text-slate-500 dark:text-slate-400">{message}</p>
            </CardContent>
          </Card>
        </TabsContent>

        {!selectedChannelDetail || !config ? (
          <div className="rounded-2xl border border-dashed border-slate-300 px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">请先在“通道管理”中选择物流通道进行配置。</div>
        ) : (
          <>

            <TabsContent value="members" className="mt-0 space-y-5">
              <Card>
                <CardHeader><CardTitle className="flex items-center justify-between gap-3"><span>通道摄像头</span><Badge variant="outline">{members.length}/9 路 · 最多 9 路</Badge></CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  {members.length === 0 ? <p className="text-sm text-slate-500">当前通道没有摄像头，不会触发无人告警。</p> : members.map((member, index) => {
                    const camera = cameraById.get(member.camera_id)
                    return (
                      <div key={member.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                        <Camera className="h-4 w-4 text-slate-400" />
                        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{camera?.name ?? `摄像头 #${member.camera_id}`}</p><p className="truncate text-xs text-slate-500">{camera?.shm_name ?? '正在读取摄像头信息'}</p></div>
                        <Badge variant={member.enabled ? 'default' : 'secondary'}>{member.enabled ? '已启用' : '已停用'}</Badge>
                        <Button size="sm" variant="outline" onClick={() => setMemberEnabled(member.camera_id, !member.enabled)} disabled={!isAdmin || busy}>{member.enabled ? '停用' : '启用'}</Button>
                        <Button size="sm" variant="outline" aria-label="上移" onClick={() => moveMember(member.camera_id, -1)} disabled={!isAdmin || busy || index === 0}><ArrowUp className="h-4 w-4" />上移</Button>
                        <Button size="sm" variant="outline" aria-label="下移" onClick={() => moveMember(member.camera_id, 1)} disabled={!isAdmin || busy || index === members.length - 1}><ArrowDown className="h-4 w-4" />下移</Button>
                        <Button size="sm" variant="outline" className="text-rose-600" onClick={() => removeMember(member.camera_id)} disabled={!isAdmin || busy}><Trash2 className="h-4 w-4" />移除</Button>
                      </div>
                    )
                  })}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">绑定摄像头</CardTitle>
                  <CardDescription>选择已有摄像头，或新建摄像头并直接绑定至当前物流通道。</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                      <div>
                        <h3 className="text-sm font-semibold">绑定已有摄像头</h3>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">从平台摄像头列表中选择并加入当前通道。</p>
                      </div>
                      <Label htmlFor="logistics-existing-camera">{moveExisting ? '从其他通道移动摄像头' : '可绑定摄像头'}</Label>
                      <Select value={existingCameraId} onValueChange={setExistingCameraId} disabled={!isAdmin || busy || members.length >= 9}>
                        <SelectTrigger id="logistics-existing-camera"><SelectValue placeholder={membershipsLoaded ? '选择已有摄像头' : '正在读取通道成员'} /></SelectTrigger>
                      <SelectContent showScrollButtons={false}>{existingCameraOptions.map((camera) => <SelectItem key={camera.camera_id} value={String(camera.camera_id)}>{camera.name}</SelectItem>)}</SelectContent>
                      </Select>
                      <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300"><input type="checkbox" checked={moveExisting} onChange={(event) => { setMoveExisting(event.target.checked); setExistingCameraId('') }} disabled={!isAdmin || busy} />摄像头已属于本功能其他通道时，移动至当前通道</label>
                      <Button onClick={addExisting} disabled={!isAdmin || busy || !existingCameraId || members.length >= 9}>{moveExisting ? '移动至当前通道' : '绑定已有摄像头'}</Button>
                    </div>
                    <div className="flex flex-col justify-between gap-4 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
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
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="roi" className="mt-0 space-y-5">
              <Card>
                <CardHeader><CardTitle className="text-base">逐路 ROI 摄像头</CardTitle></CardHeader>
                <CardContent className="space-y-2"><Label htmlFor="logistics-roi-camera">通道摄像头</Label><Select value={selectedCameraId === null ? '' : String(selectedCameraId)} onValueChange={(value) => setSelectedCameraId(Number(value))}><SelectTrigger id="logistics-roi-camera"><SelectValue placeholder="选择通道摄像头" /></SelectTrigger><SelectContent>{members.map((member) => <SelectItem key={member.camera_id} value={String(member.camera_id)}>{cameraById.get(member.camera_id)?.name ?? `摄像头 #${member.camera_id}`}</SelectItem>)}</SelectContent></Select></CardContent>
              </Card>
              <AiVisionRoiEditor title="物流通道逐路 ROI 绘制" cameraKey={selectedCamera?.shm_name ?? ''} roiJson={roiJson} disabled={!isAdmin || busy || !cameraConfig} saving={busy} message={message} onChange={setRoiJson} onSave={saveRoi} />
            </TabsContent>

            <TabsContent value="rules" className="mt-0 space-y-5">
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="h-5 w-5" />通道级检测与告警配置</CardTitle></CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2"><Label htmlFor="logistics-channel-name">物流通道名称</Label><Input id="logistics-channel-name" value={channelName} onChange={(event) => setChannelName(event.target.value)} disabled={!isAdmin || busy} /></div>
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800"><span>启用当前物流通道</span><input type="checkbox" checked={config.enabled} onChange={(event) => setConfig({ ...config, enabled: event.target.checked })} disabled={!isAdmin || busy} /></label>
                  <ConfigNumber label="每日检测开始时间" id="logistics-detection-start" type="time" value={timeForInput(config.detection_start)} onChange={(value) => setConfig({ ...config, detection_start: value })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="每日检测结束时间" id="logistics-detection-end" type="time" value={timeForInput(config.detection_end)} onChange={(value) => setConfig({ ...config, detection_end: value })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="无人持续时间（秒）" id="logistics-empty-grace" value={String(config.empty_grace_seconds)} onChange={(value) => setConfig({ ...config, empty_grace_seconds: Number(value) })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="多人持续时间（秒）" id="logistics-multi-grace" value={String(config.multi_grace_seconds)} onChange={(value) => setConfig({ ...config, multi_grace_seconds: Number(value) })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="告警间隔（秒）" id="logistics-alarm-interval" value={String(config.alarm_interval)} onChange={(value) => setConfig({ ...config, alarm_interval: Number(value) })} disabled={!isAdmin || busy} />
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800"><span>保存数据库告警</span><input type="checkbox" checked={config.alarm.sql_enable} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, sql_enable: event.target.checked } })} disabled={!isAdmin || busy} /></label>
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800"><span>启用企业微信推送</span><input type="checkbox" checked={config.alarm.wechat.enabled} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, wechat: { ...config.alarm.wechat, enabled: event.target.checked } } })} disabled={!isAdmin || busy} /></label>
                  <div className="space-y-2"><Label htmlFor="logistics-wechat-user">企业微信接收人</Label><Input id="logistics-wechat-user" value={config.alarm.wechat.user} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, wechat: { ...config.alarm.wechat, user: event.target.value } } })} disabled={!isAdmin || busy} /></div>
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-800"><span>启用警号</span><input type="checkbox" checked={config.alarm.horn.enabled} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, horn: { ...config.alarm.horn, enabled: event.target.checked } } })} disabled={!isAdmin || busy} /></label>
                  <ConfigNumber label="警号 ID" id="logistics-horn-id" value={config.alarm.horn.horn_id === null ? '' : String(config.alarm.horn.horn_id)} onChange={(value) => setConfig({ ...config, alarm: { ...config.alarm, horn: { ...config.alarm.horn, horn_id: value === '' ? null : Number(value) } } })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="警号事件 ID" id="logistics-horn-event-id" value={config.alarm.horn.horn_event_id === null ? '' : String(config.alarm.horn.horn_event_id)} onChange={(value) => setConfig({ ...config, alarm: { ...config.alarm, horn: { ...config.alarm.horn, horn_event_id: value === '' ? null : Number(value) } } })} disabled={!isAdmin || busy} />
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-4 dark:bg-slate-900 md:col-span-2"><p className="text-sm text-slate-600 dark:text-slate-300">{message}</p><Button onClick={saveChannel} disabled={!isAdmin || busy || !channelName.trim()}><Save className="h-4 w-4" />保存通道配置</Button></div>
                </CardContent>
              </Card>
            </TabsContent>
          </>
        )}
      </Tabs>

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
            <DialogDescription>输入物流通道名称。添加后将自动选中新通道。</DialogDescription>
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

function ConfigNumber({ label, id, value, onChange, disabled, type = 'number' }: { label: string; id: string; value: string; onChange: (value: string) => void; disabled: boolean; type?: 'number' | 'time' }) {
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} type={type} min={type === 'number' ? 0 : undefined} step={type === 'number' ? 0.1 : undefined} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} /></div>
}
