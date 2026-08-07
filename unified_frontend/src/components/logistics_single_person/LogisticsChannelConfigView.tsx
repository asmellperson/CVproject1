import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Camera, Plus, Save, Settings2, Trash2 } from 'lucide-react'

import { AiVisionRoiEditor } from '@/components/AiVisionRoiEditor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'

import {
  addLogisticsChannelCamera,
  createLogisticsChannel,
  deleteLogisticsChannel,
  getLogisticsCameraConfig,
  moveLogisticsChannelCamera,
  removeLogisticsChannelCamera,
  reorderLogisticsChannelCameras,
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

type Props = {
  feature: LogisticsFeatureName
  channels: LogisticsChannel[]
  selectedChannelId: number | null
  selectedChannelDetail: LogisticsChannelDetail | null
  isAdmin: boolean
  onSelectChannel: (channelId: number) => void
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
  onChanged,
}: Props) {
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('通道配置修改后请保存。')
  const [newChannelName, setNewChannelName] = useState('')
  const [channelName, setChannelName] = useState('')
  const [config, setConfig] = useState<LogisticsChannelConfig | null>(null)
  const [existingCameraId, setExistingCameraId] = useState('')
  const [moveExisting, setMoveExisting] = useState(false)
  const [newCamera, setNewCamera] = useState({ name: '', url: '', fps: '5' })
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null)
  const [cameraConfig, setCameraConfig] = useState<LogisticsCameraConfigResponse | null>(null)
  const [roiJson, setRoiJson] = useState('[]')
  const hydratedChannelId = useRef<number | null>(null)

  const members = useMemo(
    () => [...(selectedChannelDetail?.members ?? [])].filter((member) => member.enabled).sort((a, b) => a.sort_order - b.sort_order),
    [selectedChannelDetail],
  )
  const cameraById = useMemo(() => new Map(cameras.map((camera) => [camera.camera_id, camera])), [cameras])
  const selectedCamera = selectedCameraId === null ? undefined : cameraById.get(selectedCameraId)
  const memberIds = useMemo(() => new Set(members.map((member) => member.camera_id)), [members])
  const availableCameras = cameras.filter((camera) => !memberIds.has(camera.camera_id))

  useEffect(() => {
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
  }, [])

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
    if (!selectedCamera) {
      setCameraConfig(null)
      setRoiJson('[]')
      return
    }
    let active = true
    setCameraConfig(null)
    getLogisticsCameraConfig(feature, selectedCamera.shm_name)
      .then((result) => {
        if (!active) return
        setCameraConfig(result)
        setRoiJson(JSON.stringify(result.config.value.roi_pos ?? []))
      })
      .catch((reason) => active && setMessage(`逐路 ROI 读取失败：${messageOf(reason)}`))
    return () => { active = false }
  }, [feature, selectedCamera])

  const run = async (action: () => Promise<unknown>, success: string) => {
    if (!isAdmin || busy) return
    setBusy(true)
    try {
      await action()
      setMessage(success)
      onChanged()
    } catch (reason) {
      setMessage(`操作失败：${messageOf(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const createChannel = () => run(async () => {
    const result = await createLogisticsChannel(feature, { name: newChannelName.trim() })
    setNewChannelName('')
    onSelectChannel(result.id)
  }, '物流通道已新增。')

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

  const deleteChannel = () => {
    if (!selectedChannelDetail || !window.confirm(`确定删除物流通道“${selectedChannelDetail.name}”吗？摄像头资源不会被删除。`)) return
    void run(() => deleteLogisticsChannel(feature, selectedChannelDetail.id), '物流通道已删除。')
  }

  const addExisting = () => {
    if (!selectedChannelDetail || !existingCameraId) return
    const cameraId = Number(existingCameraId)
    void run(
      () => moveExisting
        ? moveLogisticsChannelCamera(feature, selectedChannelDetail.id, cameraId)
        : addLogisticsChannelCamera(feature, selectedChannelDetail.id, { camera_id: cameraId }),
      moveExisting ? '摄像头已移动至当前通道。' : '已有摄像头已绑定。',
    )
    setExistingCameraId('')
  }

  const createCameraAndBind = () => {
    if (!selectedChannelDetail) return
    void run(() => addLogisticsChannelCamera(feature, selectedChannelDetail.id, {
      name: newCamera.name.trim(),
      url: newCamera.url.trim(),
      fps: Math.round(Number(newCamera.fps)),
    }), '摄像头已新建并绑定。')
    setNewCamera({ name: '', url: '', fps: '5' })
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
    void run(() => removeLogisticsChannelCamera(feature, selectedChannelDetail.id, cameraId), '摄像头已从通道移除。')
  }

  const saveRoi = () => {
    if (!selectedCamera || !cameraConfig) return
    void run(() => updateLogisticsCameraConfig(feature, selectedCamera.shm_name, {
      ...cameraConfig.config,
      value: { ...cameraConfig.config.value, roi_pos: roiPayload(roiJson) },
    }), '当前摄像头 ROI 已保存。')
  }

  return (
    <div className="space-y-5">
      {!isAdmin ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">当前为 viewer 只读模式，只有管理员可以修改物流通道配置。</div> : null}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Plus className="h-5 w-5" />新增物流通道</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row">
          <Input aria-label="物流通道名称" value={newChannelName} onChange={(event) => setNewChannelName(event.target.value)} placeholder="输入物流通道名称" disabled={!isAdmin || busy} />
          <Button className="shrink-0" onClick={createChannel} disabled={!isAdmin || busy || !newChannelName.trim()}>新增物流通道</Button>
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader><CardTitle className="text-base">通道列表</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {channels.length === 0 ? <p className="text-sm text-slate-500">暂无物流通道</p> : channels.map((channel) => (
              <Button key={channel.id} variant={selectedChannelId === channel.id ? 'default' : 'outline'} className="w-full justify-between" onClick={() => onSelectChannel(channel.id)}>
                <span className="truncate">{channel.name}</span><span className="text-xs opacity-70">{channel.enabled ? '启用' : '停用'}</span>
              </Button>
            ))}
          </CardContent>
        </Card>

        {!selectedChannelDetail || !config ? (
          <div className="rounded-2xl border border-dashed border-slate-300 px-6 py-12 text-center text-sm text-slate-500">请选择物流通道进行配置。</div>
        ) : (
          <Tabs defaultValue="members" className="space-y-5">
            <TabsList className="grid h-auto w-full grid-cols-3">
              <TabsTrigger value="members">摄像头成员</TabsTrigger>
              <TabsTrigger value="roi">逐路 ROI</TabsTrigger>
              <TabsTrigger value="rules">通道规则</TabsTrigger>
            </TabsList>

            <TabsContent value="members" className="space-y-5">
              <Card>
                <CardHeader><CardTitle className="flex items-center justify-between gap-3"><span>通道摄像头</span><Badge variant="outline">{members.length}/9 路 · 最多 9 路</Badge></CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  {members.length === 0 ? <p className="text-sm text-slate-500">当前通道没有摄像头，不会触发无人告警。</p> : members.map((member, index) => {
                    const camera = cameraById.get(member.camera_id)
                    return (
                      <div key={member.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 p-3">
                        <Camera className="h-4 w-4 text-slate-400" />
                        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{camera?.name ?? `摄像头 #${member.camera_id}`}</p><p className="truncate text-xs text-slate-500">{camera?.shm_name ?? '正在读取摄像头信息'}</p></div>
                        <Button size="sm" variant="outline" aria-label="上移" onClick={() => moveMember(member.camera_id, -1)} disabled={!isAdmin || busy || index === 0}><ArrowUp className="h-4 w-4" />上移</Button>
                        <Button size="sm" variant="outline" aria-label="下移" onClick={() => moveMember(member.camera_id, 1)} disabled={!isAdmin || busy || index === members.length - 1}><ArrowDown className="h-4 w-4" />下移</Button>
                        <Button size="sm" variant="outline" className="text-rose-600" onClick={() => removeMember(member.camera_id)} disabled={!isAdmin || busy}><Trash2 className="h-4 w-4" />移除</Button>
                      </div>
                    )
                  })}
                </CardContent>
              </Card>

              <div className="grid gap-5 xl:grid-cols-2">
                <Card>
                  <CardHeader><CardTitle className="text-base">绑定已有摄像头</CardTitle></CardHeader>
                  <CardContent className="space-y-3">
                    <Select value={existingCameraId} onValueChange={setExistingCameraId} disabled={!isAdmin || busy || members.length >= 9}>
                      <SelectTrigger><SelectValue placeholder="选择已有摄像头" /></SelectTrigger>
                      <SelectContent>{availableCameras.map((camera) => <SelectItem key={camera.camera_id} value={String(camera.camera_id)}>{camera.name}</SelectItem>)}</SelectContent>
                    </Select>
                    <label className="flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={moveExisting} onChange={(event) => setMoveExisting(event.target.checked)} disabled={!isAdmin || busy} />摄像头已属于本功能其他通道时，移动至当前通道</label>
                    <Button onClick={addExisting} disabled={!isAdmin || busy || !existingCameraId || members.length >= 9}>{moveExisting ? '移动至当前通道' : '绑定已有摄像头'}</Button>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-base">新建摄像头并绑定</CardTitle></CardHeader>
                  <CardContent className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2"><Label htmlFor="logistics-new-camera-name">摄像头名称</Label><Input id="logistics-new-camera-name" value={newCamera.name} onChange={(event) => setNewCamera((current) => ({ ...current, name: event.target.value }))} disabled={!isAdmin || busy} /></div>
                    <div className="space-y-2"><Label htmlFor="logistics-new-camera-fps">FPS</Label><Input id="logistics-new-camera-fps" type="number" min="1" step="1" value={newCamera.fps} onChange={(event) => setNewCamera((current) => ({ ...current, fps: event.target.value }))} disabled={!isAdmin || busy} /></div>
                    <div className="space-y-2 sm:col-span-2"><Label htmlFor="logistics-new-camera-url">RTSP 地址</Label><Input id="logistics-new-camera-url" value={newCamera.url} onChange={(event) => setNewCamera((current) => ({ ...current, url: event.target.value }))} placeholder="rtsp://..." disabled={!isAdmin || busy} /></div>
                    <Button className="sm:col-span-2" onClick={createCameraAndBind} disabled={!isAdmin || busy || members.length >= 9 || !newCamera.name.trim() || !newCamera.url.trim()}>新建摄像头并绑定</Button>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            <TabsContent value="roi" className="space-y-5">
              <Card>
                <CardHeader><CardTitle className="text-base">逐路 ROI 摄像头</CardTitle></CardHeader>
                <CardContent><Select value={selectedCameraId === null ? '' : String(selectedCameraId)} onValueChange={(value) => setSelectedCameraId(Number(value))}><SelectTrigger><SelectValue placeholder="选择通道摄像头" /></SelectTrigger><SelectContent>{members.map((member) => <SelectItem key={member.camera_id} value={String(member.camera_id)}>{cameraById.get(member.camera_id)?.name ?? `摄像头 #${member.camera_id}`}</SelectItem>)}</SelectContent></Select></CardContent>
              </Card>
              <AiVisionRoiEditor title="物流通道逐路 ROI 绘制" cameraKey={selectedCamera?.shm_name ?? ''} feature={feature} roiJson={roiJson} disabled={!isAdmin || busy || !cameraConfig} saving={busy} message={message} onChange={setRoiJson} onSave={saveRoi} />
            </TabsContent>

            <TabsContent value="rules" className="space-y-5">
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="h-5 w-5" />通道级检测与告警配置</CardTitle></CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2"><Label htmlFor="logistics-channel-name">物流通道名称</Label><Input id="logistics-channel-name" value={channelName} onChange={(event) => setChannelName(event.target.value)} disabled={!isAdmin || busy} /></div>
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm"><span>启用当前物流通道</span><input type="checkbox" checked={config.enabled} onChange={(event) => setConfig({ ...config, enabled: event.target.checked })} disabled={!isAdmin || busy} /></label>
                  <ConfigNumber label="每日检测开始时间" id="logistics-detection-start" type="time" value={timeForInput(config.detection_start)} onChange={(value) => setConfig({ ...config, detection_start: value })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="每日检测结束时间" id="logistics-detection-end" type="time" value={timeForInput(config.detection_end)} onChange={(value) => setConfig({ ...config, detection_end: value })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="无人持续时间（秒）" id="logistics-empty-grace" value={String(config.empty_grace_seconds)} onChange={(value) => setConfig({ ...config, empty_grace_seconds: Number(value) })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="多人持续时间（秒）" id="logistics-multi-grace" value={String(config.multi_grace_seconds)} onChange={(value) => setConfig({ ...config, multi_grace_seconds: Number(value) })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="告警间隔（秒）" id="logistics-alarm-interval" value={String(config.alarm_interval)} onChange={(value) => setConfig({ ...config, alarm_interval: Number(value) })} disabled={!isAdmin || busy} />
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm"><span>保存数据库告警</span><input type="checkbox" checked={config.alarm.sql_enable} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, sql_enable: event.target.checked } })} disabled={!isAdmin || busy} /></label>
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm"><span>启用企业微信推送</span><input type="checkbox" checked={config.alarm.wechat.enabled} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, wechat: { ...config.alarm.wechat, enabled: event.target.checked } } })} disabled={!isAdmin || busy} /></label>
                  <div className="space-y-2"><Label htmlFor="logistics-wechat-user">企业微信接收人</Label><Input id="logistics-wechat-user" value={config.alarm.wechat.user} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, wechat: { ...config.alarm.wechat, user: event.target.value } } })} disabled={!isAdmin || busy} /></div>
                  <label className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm"><span>启用警号</span><input type="checkbox" checked={config.alarm.horn.enabled} onChange={(event) => setConfig({ ...config, alarm: { ...config.alarm, horn: { ...config.alarm.horn, enabled: event.target.checked } } })} disabled={!isAdmin || busy} /></label>
                  <ConfigNumber label="警号 ID" id="logistics-horn-id" value={config.alarm.horn.horn_id === null ? '' : String(config.alarm.horn.horn_id)} onChange={(value) => setConfig({ ...config, alarm: { ...config.alarm, horn: { ...config.alarm.horn, horn_id: value === '' ? null : Number(value) } } })} disabled={!isAdmin || busy} />
                  <ConfigNumber label="警号事件 ID" id="logistics-horn-event-id" value={config.alarm.horn.horn_event_id === null ? '' : String(config.alarm.horn.horn_event_id)} onChange={(value) => setConfig({ ...config, alarm: { ...config.alarm, horn: { ...config.alarm.horn, horn_event_id: value === '' ? null : Number(value) } } })} disabled={!isAdmin || busy} />
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-4 md:col-span-2"><p className="text-sm text-slate-600">{message}</p><div className="flex gap-2"><Button variant="outline" className="text-rose-600" onClick={deleteChannel} disabled={!isAdmin || busy}><Trash2 className="h-4 w-4" />删除通道</Button><Button onClick={saveChannel} disabled={!isAdmin || busy || !channelName.trim()}><Save className="h-4 w-4" />保存通道配置</Button></div></div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        )}
      </div>
    </div>
  )
}

function ConfigNumber({ label, id, value, onChange, disabled, type = 'number' }: { label: string; id: string; value: string; onChange: (value: string) => void; disabled: boolean; type?: 'number' | 'time' }) {
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><Input id={id} type={type} min={type === 'number' ? 0 : undefined} step={type === 'number' ? 0.1 : undefined} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled} /></div>
}
