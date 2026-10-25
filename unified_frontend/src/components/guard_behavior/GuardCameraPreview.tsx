import { useEffect, useMemo, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { aiVisionFrameUrl } from '@/lib/aivision'
import { createPreviewFrameBuffer } from '../AiVisionMonitor.frame'
import { createPreviewPerformanceRecorder, type PreviewPerformanceReport } from '../AiVisionMonitor.performance'
import { GuardVideoStatusPill } from './GuardMonitorUi'
import type { GuardMember } from './types'

export function GuardCameraPreview({ member, online, aiReady, onPerformanceReport }: {
  member: GuardMember
  online: boolean | undefined
  aiReady: boolean
  onPerformanceReport?: (report: PreviewPerformanceReport) => void
}) {
  const enabled = member.physical_enabled && online !== false
  const previewKey = useMemo(() => ({
    memberId: member.id, cameraId: member.camera_id, cameraKey: member.shm_name,
    department: member.department, enabled,
  }), [enabled, member.id, member.camera_id, member.shm_name, member.department])
  const [frameState, setFrame] = useState<{ key: typeof previewKey; url: string; annotated: boolean } | null>(null)
  const [errorState, setError] = useState<{ key: typeof previewKey; message: string } | null>(null)
  const sessionRef = useRef<{
    key: typeof previewKey
    buffer: ReturnType<typeof createPreviewFrameBuffer>
    recorder: ReturnType<typeof createPreviewPerformanceRecorder> | null
  } | null>(null)
  const reportCallbackRef = useRef(onPerformanceReport)
  const frame = frameState?.key === previewKey ? frameState : null
  const error = errorState?.key === previewKey ? errorState.message : ''

  useEffect(() => { reportCallbackRef.current = onPerformanceReport }, [onPerformanceReport])
  useEffect(() => {
    if (!previewKey.enabled) return
    const session = {
      key: previewKey,
      buffer: createPreviewFrameBuffer(),
      recorder: null as ReturnType<typeof createPreviewPerformanceRecorder> | null,
    }
    sessionRef.current = session
    const syncVisibility = () => {
      session.recorder?.dispose()
      // 隐藏时不把暂停时长计入帧率；当前画面仍遵循串行轮询原有的可见性流程。
      session.recorder = document.visibilityState === 'hidden' ? null : createPreviewPerformanceRecorder({
        cameraKey: previewKey.cameraKey, feature: 'guard_behavior', department: previewKey.department,
        refreshMs: 500,
        onReport(report) {
          if (sessionRef.current === session) reportCallbackRef.current?.(report)
        },
      })
    }
    syncVisibility()
    document.addEventListener('visibilitychange', syncVisibility)
    return () => {
      document.removeEventListener('visibilitychange', syncVisibility)
      session.recorder?.dispose()
      session.buffer.dispose()
      if (sessionRef.current === session) sessionRef.current = null
    }
  }, [previewKey])

  useSerialPoll(async (signal) => {
    const session = sessionRef.current
    if (!session || session.key !== previewKey) return
    const recorder = session.recorder
    const startedAt = performance.now()
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
      const headersReceivedAt = performance.now()
      signal.throwIfAborted()
      if (sessionRef.current !== session) return
      if (!response.ok) throw new Error(response.status === 503 ? '暂无视频帧' : `画面读取失败（${response.status}）`)
      const blob = await response.blob()
      const bodyReceivedAt = performance.now()
      signal.throwIfAborted()
      if (sessionRef.current !== session) return
      const url = await session.buffer.prepare(blob, signal)
      signal.throwIfAborted()
      if (sessionRef.current !== session) return
      recorder?.completed({
        startedAt, headersReceivedAt, bodyReceivedAt, decodedAt: performance.now(),
        bytes: blob.size, headers: response.headers, src: url,
      })
      setFrame({ key: previewKey, url, annotated })
      setError(null)
    } catch (cause) {
      if (sessionRef.current === session) {
        // 串行轮询会抑制取消异常，超时仍需计数，切换或卸载的主动取消不计失败。
        if (!signal.aborted || signal.reason?.name === 'TimeoutError') recorder?.failed()
        if (!signal.aborted) {
          session.buffer.clear()
          setFrame(null)
          setError({ key: previewKey, message: cause instanceof Error ? cause.message : String(cause) })
        }
      }
      throw cause
    }
  }, { intervalMs: 500, intervalMode: 'from-start', timeoutMs: 8000, enabled,
    restartKey: `${member.id}:${member.camera_id}:${member.shm_name}:${member.department}:${aiReady}` })
  const message = !member.physical_enabled ? '物理设备已停用' : online === false ? '视频离线' : error || '等待视频画面'
  return <div className="relative overflow-hidden bg-slate-950">
    <div className="absolute left-3 top-3 z-10"><GuardVideoStatusPill
      label={`${member.name} · ${enabled && frame ? frame.annotated ? 'Guard 标注画面' : '原始画面' : message}`}
      state={enabled && frame ? 'normal' : 'neutral'} showDot /></div>
    {enabled && frame ? <img src={frame.url} alt={`${member.name}${frame.annotated ? 'Guard 标注画面' : '原始画面'}`} className="block h-auto w-full object-contain"
      onLoad={(event) => {
        const session = sessionRef.current
        if (session?.key !== previewKey) return
        session.buffer.displayed(event.currentTarget.src)
        session.recorder?.displayed(event.currentTarget.src)
      }} />
      : <div className="flex aspect-video items-center justify-center p-8 text-center text-sm text-slate-400">{message}</div>}
  </div>
}
