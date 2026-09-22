import { useEffect, useRef, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { askVideo, getVisualLanguageEvents, getVisualLanguageStatus,
  type VideoAnswer, type VisualLanguageEvent, type VisualLanguageStatus } from '@/lib/visual-language-detection'

export function useVisualLanguageMonitor(cameraKey: string, department: DepartmentId) {
  const [status, setStatus] = useState<VisualLanguageStatus | null>(null)
  const [events, setEvents] = useState<VisualLanguageEvent[]>([])
  const [error, setError] = useState('')
  const [questionError, setQuestionError] = useState('')
  const [answer, setAnswer] = useState<VideoAnswer | null>(null)
  const [asking, setAsking] = useState(false)
  const questionRequest = useRef<AbortController | null>(null)

  useSerialPoll(async (signal) => {
    const [nextStatus, history] = await Promise.all([
      getVisualLanguageStatus(cameraKey, department, signal), getVisualLanguageEvents(cameraKey, department, signal),
    ])
    if (signal.aborted) return
    setStatus(nextStatus); setEvents(history.items); setError('')
  }, { enabled: Boolean(cameraKey), intervalMs: 1000, timeoutMs: 10000, restartKey: `${department}:${cameraKey}`,
    onError: (cause) => setError(cause instanceof Error ? cause.message : String(cause)) })

  useEffect(() => () => questionRequest.current?.abort(), [])

  const ask = async (question: string) => {
    if (!cameraKey || !question.trim() || questionRequest.current) return
    const controller = new AbortController()
    questionRequest.current = controller
    setAsking(true); setQuestionError(''); setAnswer(null)
    try {
      const result = await askVideo(cameraKey, department, question.trim(), controller.signal)
      if (!controller.signal.aborted) setAnswer(result)
    } catch (cause) {
      if (!controller.signal.aborted) setQuestionError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      if (!controller.signal.aborted) setAsking(false)
      questionRequest.current = null
    }
  }
  return { status, events, error, questionError, answer, asking, ask }
}
