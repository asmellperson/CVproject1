import { useState } from 'react'
import { FileAudio, Pencil, Play, Plus, Radio, RefreshCw, Trash2, Volume2 } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { DEPARTMENT_LABELS } from '@/auth/permissions'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader } from '@/components/detection/DetectionConfigUi'
import { useDetectionDepartment } from '@/components/detection/DetectionDepartmentContext'
import type { HornDevice } from '@/lib/horns'
import { HornDeviceDialog } from './HornDeviceDialog'
import { HornDeleteDialog } from './HornDeleteDialog'
import { HORN_STATE_LABELS } from './hornDeviceForm'
import { useHornDevices } from './useHornDevices'
import { useHornAudioCatalog } from './useHornAudioCatalog'
import { HornSipServerSettings } from './HornSipServerSettings'
import { HornAudioLibrary } from './HornAudioLibrary'
import { HornPlaybackDialog } from './HornPlaybackControl'

export function HornDeviceManager() {
  const { isAdmin } = useAuth()
  const department = useDetectionDepartment()
  const [tab, setTab] = useState('devices')
  const [unassigned, setUnassigned] = useState(false)
  const devices = useHornDevices(isAdmin, unassigned ? 'unassigned' : department)
  const [editor, setEditor] = useState<{ device: HornDevice | null } | null>(null)
  const [deleting, setDeleting] = useState<HornDevice | null>(null)
  const [preview, setPreview] = useState<HornDevice | null>(null)
  const audio = useHornAudioCatalog(isAdmin && (tab === 'audio' || preview !== null))
  const edit = async (id: number) => {
    const device = await devices.loadDevice(id)
    if (device) setEditor({ device })
  }

  return <>
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Volume2} tone="violet" title="喇叭配置"
        description={department ? `${DEPARTMENT_LABELS[department]} · 设备按事业部管理` : '请先进入具体事业部的检测页面'}
        actions={isAdmin && department && tab === 'devices' ? <>
          <Button variant="outline" onClick={devices.refresh} disabled={devices.busy || devices.loading} aria-label="刷新喇叭列表">
            <RefreshCw className={`h-4 w-4 ${devices.loading ? 'animate-spin' : ''}`} />刷新
          </Button>
          {!unassigned ? <Button disabled={devices.busy} onClick={() => { devices.clearFeedback(); setEditor({ device: null }) }}><Plus className="h-4 w-4" />新增喇叭</Button> : null}
        </> : undefined} />
      <DetectionConfigCardContent>
        {!isAdmin ? <p className="py-4 text-sm text-slate-500 dark:text-slate-400">喇叭设备管理仅对管理员开放。</p>
          : !department ? <p className="py-4 text-sm text-slate-500">请选择事业部。</p> : <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="mb-4 grid h-auto w-full grid-cols-3 rounded-xl bg-slate-100 p-1 dark:bg-slate-950/50">
              <TabsTrigger value="devices" className="h-10 gap-2 rounded-lg"><Volume2 className="h-4 w-4" />设备管理</TabsTrigger>
              <TabsTrigger value="audio" className="h-10 gap-2 rounded-lg"><FileAudio className="h-4 w-4" />音频库</TabsTrigger>
              <TabsTrigger value="sip" className="h-10 gap-2 rounded-lg"><Radio className="h-4 w-4" />SIP 服务</TabsTrigger>
            </TabsList>
            <TabsContent value="devices" className="mt-0 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-slate-500 dark:text-slate-400">{unassigned ? '为旧设备分配归属，或查看引用后删除。' : `共 ${devices.devices.length} 台设备，报警绑定仅显示本事业部设备。`}</p>
                <Select value={unassigned ? 'unassigned' : 'department'} disabled={devices.busy} onValueChange={(value) => setUnassigned(value === 'unassigned')}>
                  <SelectTrigger className="w-44" aria-label="设备归属范围"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="department">本事业部设备</SelectItem><SelectItem value="unassigned">待分配设备</SelectItem></SelectContent>
                </Select>
              </div>
              {devices.error || devices.loadError ? <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">{devices.error || devices.loadError}</p> : null}
              {devices.message ? <p role="status" className="text-sm text-emerald-700 dark:text-emerald-300">{devices.message}</p> : null}
              {devices.loading && !devices.devices.length ? <p role="status" className="py-10 text-center text-sm text-slate-500">正在读取设备...</p>
                : !devices.loadError && !devices.devices.length ? <p className="rounded-xl border border-dashed border-slate-300 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">{unassigned ? '没有待分配设备' : '本事业部暂无喇叭设备，点击“新增喇叭”添加。'}</p> : null}
              <div className="space-y-3">{devices.devices.map((device) => {
                const state = device.enable ? device.runtime.state : 'disabled'
                return <div key={device.id} className="rounded-xl border border-[#E8ECF5] bg-[#FAFBFE] p-3 sm:p-4 dark:border-slate-800 dark:bg-slate-950/30">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="flex w-full min-w-0 items-center gap-3 sm:w-auto sm:flex-1">
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-600 dark:bg-violet-950/50 dark:text-violet-300"><Volume2 className="h-5 w-5" /></span>
                      <div className="min-w-0 flex-1"><p className="break-words text-sm font-semibold text-slate-900 dark:text-slate-100">{device.name}</p>
                        <p title={device.url} className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{device.url} · {device.sip ? 'SIP 音频' : '设备音频'}</p></div>
                    </div>
                    <Badge variant="outline" className={state === 'online' ? 'border-emerald-200 text-emerald-700 dark:border-emerald-900 dark:text-emerald-300' : 'text-slate-500 dark:text-slate-400'}>{HORN_STATE_LABELS[state]}</Badge>
                    <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">启用<Switch checked={device.enable} disabled={devices.busy} aria-label={`启用${device.name}`} onCheckedChange={(enable) => { void devices.setEnabled(device, enable) }} /></label>
                    <div className="ml-auto flex justify-end gap-2">
                      <Button size="sm" variant="outline" disabled={devices.busy || !device.enable} onClick={() => setPreview(device)}><Play className="h-4 w-4" />试播</Button>
                      <Button size="sm" variant="outline" disabled={devices.busy} onClick={() => { void edit(device.id) }}><Pencil className="h-4 w-4" />{unassigned ? '分配归属' : '编辑'}</Button>
                      <Button size="sm" variant="ghost" disabled={devices.busy} className="text-rose-600 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-950/40" aria-label={`查看引用并删除${device.name}`} onClick={() => setDeleting(device)}><Trash2 className="h-4 w-4" /><span className="hidden sm:inline">删除</span></Button>
                    </div>
                  </div>
                  {device.runtime.last_error ? <p className="mt-3 break-words text-xs text-rose-600 dark:text-rose-300">{device.runtime.last_error}</p> : null}
                </div>
              })}</div>
            </TabsContent>
            <TabsContent value="audio" className="mt-0"><HornAudioLibrary catalog={audio} /></TabsContent>
            <TabsContent value="sip" className="mt-0"><HornSipServerSettings /></TabsContent>
          </Tabs>}
      </DetectionConfigCardContent>
    </Card>
    {editor && department ? <HornDeviceDialog department={department} device={editor.device} busy={devices.busy} error={devices.error}
      onClose={() => setEditor(null)} onTest={devices.checkConnection}
      onSave={async (payload) => Boolean(await devices.saveDevice(editor.device?.id, payload))} /> : null}
    {deleting ? <HornDeleteDialog device={deleting} onClose={() => setDeleting(null)} onDeleted={() => { setDeleting(null); devices.refresh() }} /> : null}
    {preview ? <HornPlaybackDialog device={preview} files={audio.files} error={audio.loadError} onClose={() => setPreview(null)} /> : null}
  </>
}
