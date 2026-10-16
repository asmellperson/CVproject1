import { useEffect, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { deleteHornAudio, listHornAudio, uploadHornAudio, type HornAudio } from '@/lib/horns'

const AUDIO_CHANGED = 'aicv:horn-audio-changed'

export function useHornAudioCatalog(enabled: boolean) {
  const [files, setFiles] = useState<HornAudio[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const active = useRef(enabled)
  const action = useRef<AbortController | null>(null)

  useEffect(() => {
    active.current = enabled
    const refresh = () => setRevision((value) => value + 1)
    window.addEventListener(AUDIO_CHANGED, refresh)
    return () => {
      active.current = false
      action.current?.abort()
      window.removeEventListener(AUDIO_CHANGED, refresh)
    }
  }, [enabled])

  useSerialPoll(async (signal) => {
    try {
      const items = await listHornAudio(signal)
      if (!signal.aborted && active.current) { setFiles(items); setLoadError('') }
    } catch (reason) {
      if (active.current) setLoadError(reason instanceof Error ? reason.message : '音频库读取失败。')
    }
  }, { enabled: enabled && !busy, intervalMs: 5000, timeoutMs: 8000, restartKey: revision })

  const perform = async (operation: (signal: AbortSignal) => Promise<void>) => {
    if (!active.current || action.current) return false
    const controller = new AbortController()
    action.current = controller
    setBusy(true); setError('')
    const timer = window.setTimeout(() => controller.abort(), 60000)
    try {
      await operation(controller.signal)
      if (controller.signal.aborted || !active.current) return false
      window.dispatchEvent(new Event(AUDIO_CHANGED))
      return true
    } catch (reason) {
      if (active.current) setError(controller.signal.aborted ? '音频操作超时，请刷新素材库确认结果。'
        : reason instanceof Error ? reason.message : '音频操作失败。')
      return false
    } finally {
      window.clearTimeout(timer)
      if (action.current === controller) action.current = null
      if (active.current) setBusy(false)
    }
  }

  const upload = (file: File) => perform(async (signal) => {
    if (!file.name.toLowerCase().endsWith('.aac') || !file.size) throw new Error('请选择非空的 AAC 音频文件。')
    const item = await uploadHornAudio(file, signal)
    if (!signal.aborted && active.current) setFiles((current) => [item, ...(current ?? []).filter((row) => row.id !== item.id)])
  })
  const remove = (id: number) => perform(async (signal) => {
    await deleteHornAudio(id, signal)
    if (!signal.aborted && active.current) setFiles((current) => current?.filter((row) => row.id !== id) ?? null)
  })
  return { files: enabled ? files : null, loadError: enabled ? loadError : '', error, busy, upload, remove }
}
