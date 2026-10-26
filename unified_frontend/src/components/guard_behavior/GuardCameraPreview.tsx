import { useEffect, useMemo, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { aiVisionFrameUrl } from '@/lib/aivision'
import { createPreviewFrameBuffer } from '../AiVisionMonitor.frame'
import { AiVisionVideoPreview } from '../AiVisionVideoPreview'
import type { VideoPreviewState } from '../AiVisionVideoPreview.mse'
import { useCameraVideoPreview } from '../useCameraVideoPreview'
import { GuardVideoStatusPill } from './GuardMonitorUi'
import type { GuardMember } from './types'

export function GuardCameraPreview({ member, online, aiReady }: {
  member: GuardMember
  online: boolean | undefined
  aiReady: boolean
}) {
  const enabled = member.physical_enabled && online !== false
  const [visible, setVisible] = useState(() => !document.hidden)
  const videoPreview = useCameraVideoPreview({
    cameraKey: member.shm_name, feature: 'guard_behavior', department: member.department,
    enabled: enabled && visible,
  })
  const jpegEnabled = enabled && visible && videoPreview.mode === 'jpeg'
  const videoKey = useMemo(() => ({
    memberId: member.id, cameraKey: member.shm_name, department: member.department,
    url: videoPreview.url, enabled: enabled && visible,
  }), [enabled, member.id, member.shm_name, member.department, videoPreview.url, visible])
  const [videoState, setVideoState] = useState<{ key: typeof videoKey; state: VideoPreviewState } | null>(null)
  const currentVideoState = videoState?.key === videoKey ? videoState.state : 'connecting'
  const previewKey = useMemo(() => ({
    memberId: member.id, cameraId: member.camera_id, cameraKey: member.shm_name,
    department: member.department, enabled: jpegEnabled,
  }), [jpegEnabled, member.id, member.camera_id, member.shm_name, member.department])
  const [frameState, setFrame] = useState<{ key: typeof previewKey; url: string; annotated: boolean } | null>(null)
  const [errorState, setError] = useState<{ key: typeof previewKey; message: string } | null>(null)
  const sessionRef = useRef<{
    key: typeof previewKey
    buffer: ReturnType<typeof createPreviewFrameBuffer>
  } | null>(null)
  const frame = frameState?.key === previewKey ? frameState : null
  const error = errorState?.key === previewKey ? errorState.message : ''

  useEffect(() => {
    const syncVisibility = () => setVisible(!document.hidden)
    syncVisibility()
    document.addEventListener('visibilitychange', syncVisibility)
    return () => document.removeEventListener('visibilitychange', syncVisibility)
  }, [])
  useEffect(() => {
    if (!previewKey.enabled) return
    const session = {
      key: previewKey,
      buffer: createPreviewFrameBuffer(),
    }
    sessionRef.current = session
    return () => {
      session.buffer.dispose()
      if (sessionRef.current === session) sessionRef.current = null
    }
  }, [previewKey])

  useSerialPoll(async (signal) => {
    const session = sessionRef.current
    if (!session || session.key !== previewKey) return
    try {
      signal.throwIfAborted()
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
      signal.throwIfAborted()
      if (sessionRef.current !== session) return
      if (!response.ok) throw new Error(response.status === 503 ? '暂无视频帧' : `画面读取失败（${response.status}）`)
      const blob = await response.blob()
      signal.throwIfAborted()
      if (sessionRef.current !== session) return
      const url = await session.buffer.prepare(blob, signal)
      signal.throwIfAborted()
      if (sessionRef.current !== session) return
      setFrame({ key: previewKey, url, annotated })
      setError(null)
    } catch (cause) {
      if (sessionRef.current === session) {
        if (!signal.aborted) {
          session.buffer.clear()
          setFrame(null)
          setError({ key: previewKey, message: cause instanceof Error ? cause.message : String(cause) })
        }
      }
      throw cause
    }
  }, { intervalMs: 500, intervalMode: 'from-start', timeoutMs: 8000, enabled: jpegEnabled,
    restartKey: `${member.id}:${member.camera_id}:${member.shm_name}:${member.department}:${aiReady}` })
  const playingVideo = enabled && visible && videoPreview.mode === 'mse' && currentVideoState === 'playing'
  const message = !member.physical_enabled ? '物理设备已停用' : online === false ? '视频离线'
    : !visible ? '页面不可见，已暂停视频'
    : videoPreview.mode === 'denied' ? '视频访问已停止，请检查账号、摄像头或功能权限'
    : videoPreview.mode === 'checking' ? '正在连接视频画面'
    : videoPreview.mode === 'mse' ? currentVideoState === 'reconnecting' ? '原始视频重连中' : '正在连接原始视频'
    : error || videoPreview.fallbackReason || '等待视频画面'
  const frameLabel = playingVideo ? '原始视频（无 Guard 标注）'
    : jpegEnabled && frame ? `${videoPreview.fallbackReason ? 'JPEG 回退 · ' : ''}${frame.annotated ? 'Guard 标注画面' : '原始画面'}`
    : message
  return <div className="min-w-0 overflow-hidden bg-slate-950">
    <div className="space-y-1.5 border-b border-slate-800 bg-slate-900 px-3 py-2">
      <p className="break-words text-sm font-medium text-slate-100">{member.name}</p>
      <GuardVideoStatusPill label={frameLabel}
      state={playingVideo || (jpegEnabled && frame) ? 'normal' : 'neutral'} showDot /></div>
    {enabled && visible && videoPreview.mode === 'mse' && videoPreview.url ? (
      <div className="aspect-video w-full"><AiVisionVideoPreview
        url={videoPreview.url} cameraKey={member.shm_name} department={member.department} feature="guard_behavior"
        onFallback={videoPreview.onFallback} onAccessDenied={videoPreview.onAccessDenied}
        onStateChange={(state) => setVideoState({ key: videoKey, state })} /></div>
    ) : jpegEnabled && frame ? <img src={frame.url} alt={`${member.name}${frame.annotated ? 'Guard 标注画面' : '原始画面'}`} className="block h-auto w-full object-contain"
      onLoad={(event) => {
        const session = sessionRef.current
        if (session?.key !== previewKey) return
        session.buffer.displayed(event.currentTarget.src)
      }} />
      : <div className="flex aspect-video items-center justify-center p-8 text-center text-sm text-slate-400">{message}</div>}
  </div>
}
