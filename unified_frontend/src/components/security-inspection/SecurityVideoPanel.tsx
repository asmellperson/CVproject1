import { useEffect, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { aiVisionFrameUrl, type AiVisionCamera } from '@/lib/aivision'
import { INSPECTION_FEATURE } from '@/lib/security-inspection'

export function SecurityVideoPanel({ camera }: { camera: AiVisionCamera }) {
  const [frame, setFrame] = useState('')
  const [error, setError] = useState('')
  const objectUrl = useRef('')
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current) }, [])
  const enabled = camera.enabled && camera.functions[INSPECTION_FEATURE]
  useSerialPoll(async (signal) => {
    const response = await fetch(aiVisionFrameUrl(camera.shm_name, INSPECTION_FEATURE, undefined, { maxWidth: 1280 }),
      { signal, credentials: 'include', cache: 'no-store' })
    if (!response.ok) throw new Error(response.status === 503 || response.status === 404 ? '等待检测画面，请检查摄像头和工位配置' : `读取失败（${response.status}）`)
    const blob = await response.blob()
    if (signal.aborted) return
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = URL.createObjectURL(blob)
    setFrame(objectUrl.current); setError('')
  }, { enabled, intervalMs: 500, timeoutMs: 8000, restartKey: camera.shm_name,
    onError: (cause) => { setFrame(''); setError(cause instanceof Error ? cause.message : String(cause)) } })
  return <div className="overflow-hidden rounded-lg border bg-slate-950">
    <div className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-900 px-3 py-2">
      <span className="truncate text-sm font-medium text-slate-100">{camera.name}</span>
      <span className="text-xs text-slate-400">{enabled && frame ? '实时' : '未就绪'}</span>
    </div>
    <div className="aspect-video">
      {enabled && frame ? <img src={frame} alt={`${camera.name}实时画面`} className="h-full w-full select-none object-contain" />
        : <div className="flex h-full items-center justify-center p-6 text-sm text-slate-400">{!enabled ? '检测已关闭' : error || '等待视频画面'}</div>}
    </div>
  </div>
}
