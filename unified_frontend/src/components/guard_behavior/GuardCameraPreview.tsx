import { useCallback, useState } from 'react'
import { CameraLivePreview } from '@/components/monitor/CameraLivePreview'
import { GuardVideoStatusPill } from './GuardMonitorUi'
import type { GuardMember } from './types'

export function GuardCameraPreview({ member, online, aiReady }: {
  member: GuardMember
  online: boolean | undefined
  aiReady: boolean
}) {
  const [connection, setConnection] = useState({ connected: false, message: '正在连接原始画面…' })
  const onConnectionChange = useCallback((connected: boolean, message: string) => setConnection({ connected, message }), [])
  return <div className="min-w-0 overflow-hidden bg-slate-950">
    <div className="space-y-1.5 border-b border-slate-800 bg-slate-900 px-3 py-2">
      <p className="break-words text-sm font-medium text-slate-100">{member.name}</p>
      <GuardVideoStatusPill label={connection.connected ? '实时原始画面' : connection.message} state={connection.connected ? 'normal' : 'neutral'} showDot />
      <p className="text-xs text-slate-400">{aiReady ? '检测结果见旁侧卡片' : '等待有效检测结果'}</p>
    </div>
    <div className="aspect-video w-full"><CameraLivePreview cameraKey={member.shm_name} feature="guard_behavior" department={member.department}
      enabled={member.physical_enabled && online !== false} onConnectionChange={onConnectionChange} /></div>
  </div>
}
