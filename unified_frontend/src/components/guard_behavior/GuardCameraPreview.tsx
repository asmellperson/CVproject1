import { useEffect, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { aiVisionFrameUrl } from '@/lib/aivision'
import { GuardVideoStatusPill } from './GuardMonitorUi'
import type { GuardMember } from './types'

export function GuardCameraPreview({ member, online, aiReady }: {
  member: GuardMember
  online: boolean | undefined
  aiReady: boolean
}) {
  const [frame, setFrame] = useState<{ url: string; annotated: boolean } | null>(null)
  const [error, setError] = useState('')
  const objectUrl = useRef<string | null>(null)
  const enabled = member.physical_enabled && online !== false
  const clearFrame = () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = null
    setFrame(null)
  }
  useEffect(() => {
    if (!enabled) clearFrame()
  }, [enabled])
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current) }, [])
  useSerialPoll(async (signal) => {
    const load = (annotated: boolean) => fetch(aiVisionFrameUrl(
      member.shm_name, annotated ? 'guard_behavior' : undefined, undefined, { maxWidth: 1280 },
    ), { credentials: 'include', cache: 'no-store', signal })
    let annotated = aiReady
    let response = await load(annotated)
    // 标注帧尚未生成或已过期时，继续展示同一平台 Camera 的原始画面。
    if (annotated && (response.status === 404 || response.status === 503)) {
      annotated = false
      response = await load(false)
    }
    if (!response.ok) throw new Error(response.status === 503 ? '暂无视频帧' : `画面读取失败（${response.status}）`)
    const blob = await response.blob()
    if (signal.aborted) return
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = URL.createObjectURL(blob)
    setFrame({ url: objectUrl.current, annotated }); setError('')
  }, { intervalMs: 500, timeoutMs: 8000, enabled, restartKey: `${member.shm_name}:${aiReady}`,
    onError: (cause) => { clearFrame(); setError(cause instanceof Error ? cause.message : String(cause)) } })
  const message = !member.physical_enabled ? '物理设备已停用' : online === false ? '视频离线' : error || '等待视频画面'
  return <div className="relative overflow-hidden bg-slate-950">
    <div className="absolute left-3 top-3 z-10"><GuardVideoStatusPill
      label={`${member.name} · ${enabled && frame ? frame.annotated ? 'Guard 标注画面' : '原始画面' : message}`}
      state={enabled && frame ? 'normal' : 'neutral'} showDot /></div>
    {enabled && frame ? <img src={frame.url} alt={`${member.name}${frame.annotated ? 'Guard 标注画面' : '原始画面'}`} className="block h-auto w-full object-contain" />
      : <div className="flex aspect-video items-center justify-center p-8 text-center text-sm text-slate-400">{message}</div>}
  </div>
}
