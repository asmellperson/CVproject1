import { useState } from 'react'
import { Pencil, PlugZap, Plus, RefreshCw, Trash2, Volume2 } from 'lucide-react'
import { useAuth } from '@/auth/useAuth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import {
  DETECTION_CONFIG_CARD_CLASS, DetectionConfigCardContent, DetectionConfigCardHeader,
} from '@/components/detection/DetectionConfigUi'
import type { HornDevice } from '@/lib/horns'
import { HornDeviceDialog } from './HornDeviceDialog'
import { HORN_STATE_LABELS } from './hornDeviceForm'
import { useHornDevices } from './useHornDevices'
import { useHornAudioCatalog } from './useHornAudioCatalog'
import { HornSipServerSettings } from './HornSipServerSettings'
import { HornAudioLibrary } from './HornAudioLibrary'
import { HornDevicePlayback } from './HornPlaybackControl'

export function HornDeviceManager() {
  const { isAdmin } = useAuth()
  const devices = useHornDevices(isAdmin)
  const audio = useHornAudioCatalog(isAdmin)
  const [editor, setEditor] = useState<{ device: HornDevice | null } | null>(null)
  const [connectionMessage, setConnectionMessage] = useState('')

  const edit = async (id: number) => {
    if (!isAdmin) return
    setConnectionMessage('')
    const device = await devices.loadDevice(id)
    if (device) setEditor({ device })
  }

  const remove = (device: HornDevice) => {
    if (!isAdmin || devices.busy) return
    if (!window.confirm(`确定删除喇叭设备“${device.name}”吗？`)) return
    setConnectionMessage('')
    void devices.removeDevice(device)
  }

  const testConnection = async (device: HornDevice) => {
    if (!isAdmin) return
    setConnectionMessage('')
    const result = await devices.checkConnection({ horn_id: device.id })
    if (result) setConnectionMessage(result.success ? `${device.name}：连接成功，未播放声音。`
      : `${device.name}：连接失败，${result.runtime.last_error || '请检查设备地址和账号密码。'}`)
  }

  if (!isAdmin) {
    return <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader icon={Volume2} tone="violet" title="喇叭配置" description="全局现场设备管理" />
      <DetectionConfigCardContent>
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200">喇叭设备信息和管理操作仅对管理员开放，请联系管理员。</p>
      </DetectionConfigCardContent>
    </Card>
  }

  return (
    <>
      <Card className={DETECTION_CONFIG_CARD_CLASS}>
        <DetectionConfigCardHeader icon={Volume2} tone="violet" title="喇叭配置"
          description="全局设备由所有检测页面共享，无需先添加摄像头或物流通道。"
          actions={<>
            <Button variant="outline" onClick={devices.refresh} disabled={devices.busy || devices.loading}>
              <RefreshCw className={`h-4 w-4 ${devices.loading ? 'animate-spin' : ''}`} />刷新
            </Button>
            <Button disabled={devices.busy} onClick={() => { devices.clearFeedback(); setConnectionMessage(''); setEditor({ device: null }) }}>
              <Plus className="h-4 w-4" />新增喇叭
            </Button>
          </>}
        />
        <DetectionConfigCardContent className="space-y-4">
          <HornSipServerSettings />
          <HornAudioLibrary catalog={audio} />
          {devices.error || devices.loadError ? <p role="alert" className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">{devices.error || devices.loadError}</p> : null}
          {devices.message || connectionMessage ? <p role="status" className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:bg-slate-950/40 dark:text-slate-300">{devices.message || connectionMessage}</p> : null}
          {devices.loading && devices.devices.length === 0 ? <p role="status" className="py-10 text-center text-sm text-slate-500 dark:text-slate-400">正在读取喇叭设备...</p>
            : !devices.loadError && devices.devices.length === 0 ? <p className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">暂无喇叭设备，可点击“新增喇叭”添加现场设备。</p> : null}
          {devices.devices.map((device) => (
            <div key={device.id} className="space-y-3 rounded-xl border border-[#E8ECF5] bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="break-all font-semibold text-slate-900 dark:text-slate-100">{device.name}</span>
                  <Badge variant="outline" className={device.runtime.state === 'online'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200'
                    : ['offline', 'failed'].includes(device.runtime.state)
                      ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200'
                      : 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'}>
                    运行状态：{HORN_STATE_LABELS[device.runtime.state] ?? '未知状态'}
                  </Badge>
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                  {device.enable ? '已启用' : '已停用'}
                  <Switch checked={device.enable} disabled={devices.busy} aria-label={`${device.enable ? '停用' : '启用'}${device.name}`}
                    onCheckedChange={(enable) => { setConnectionMessage(''); void devices.setEnabled(device, enable) }} />
                </label>
              </div>
              <dl className="grid gap-3 text-sm sm:grid-cols-3">
                <div className="min-w-0"><dt className="text-xs text-slate-500 dark:text-slate-400">设备地址</dt><dd className="mt-1 break-all text-slate-700 dark:text-slate-200">{device.url}</dd></div>
                <div><dt className="text-xs text-slate-500 dark:text-slate-400">用户名</dt><dd className="mt-1 break-all text-slate-700 dark:text-slate-200">{device.username}</dd></div>
                <div><dt className="text-xs text-slate-500 dark:text-slate-400">密码</dt><dd className="mt-1 text-slate-700 dark:text-slate-200">{device.password_set ? '已设置' : '未设置'}</dd></div>
                <div><dt className="text-xs text-slate-500 dark:text-slate-400">播放方式</dt><dd className="mt-1 text-slate-700 dark:text-slate-200">{device.sip ? '服务器音频（SIP）' : '设备已有音频'}</dd></div>
                {device.sip ? <><div><dt className="text-xs text-slate-500 dark:text-slate-400">SIP 账户 / 本地端口</dt><dd className="mt-1 break-all text-slate-700 dark:text-slate-200">{device.sip.username} / {device.sip.port}</dd></div>
                  <div><dt className="text-xs text-slate-500 dark:text-slate-400">SIP 参数同步</dt><dd className="mt-1 text-slate-700 dark:text-slate-200">{device.runtime.sip_ready ? '已就绪' : '等待同步'}</dd></div></> : null}
                <div className="sm:col-span-3"><dt className="text-xs text-slate-500 dark:text-slate-400">备注</dt><dd className="mt-1 whitespace-pre-wrap break-words text-slate-700 dark:text-slate-200">{device.description || '—'}</dd></div>
              </dl>
              {device.runtime.last_error ? <p className="text-sm text-rose-600 dark:text-rose-300">{device.runtime.last_error}</p> : null}
              <HornDevicePlayback device={device} files={audio.files ?? []} disabled={devices.busy} />
              <div className="flex flex-wrap justify-end gap-2">
                <Button size="sm" variant="outline" disabled={devices.busy} onClick={() => void testConnection(device)}><PlugZap className="h-4 w-4" />测试连接</Button>
                <Button size="sm" variant="outline" disabled={devices.busy} onClick={() => void edit(device.id)}><Pencil className="h-4 w-4" />编辑</Button>
                <Button size="sm" variant="ghost" disabled={devices.busy} className="text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:hover:bg-rose-950/40" onClick={() => remove(device)}><Trash2 className="h-4 w-4" />删除</Button>
              </div>
            </div>
          ))}
        </DetectionConfigCardContent>
      </Card>
      {editor ? <HornDeviceDialog device={editor.device} busy={devices.busy} error={devices.error}
        onClose={() => setEditor(null)} onTest={devices.checkConnection}
        onSave={async (payload) => Boolean(await devices.saveDevice(editor.device?.id, payload))} /> : null}
    </>
  )
}
