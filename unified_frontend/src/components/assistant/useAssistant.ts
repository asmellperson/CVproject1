import { useEffect, useRef, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { useAuth } from '@/auth/useAuth'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { notifyPlatformCamerasChanged } from '@/lib/camera-events'
import { cancelAssistantTurn, createAssistantSession, getAssistantConversation, listAssistantSessions, sendAssistantMessage } from './api'
import { isTurnActive, type AssistantConversation, type AssistantSession } from './types'

function requestId() {
  // 公司内网使用 HTTP，直接使用不要求安全上下文的随机字节 API。
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function useAssistant(department: DepartmentId | null) {
  const { refreshMe } = useAuth()
  const [sessions, setSessions] = useState<AssistantSession[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [conversation, setConversation] = useState<AssistantConversation | null>(null)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const activeId = useRef(sessionId)
  activeId.current = sessionId
  const mounted = useRef(false)
  const mutations = useRef(new AbortController())
  const retry = useRef<{ request_id: string; text: string } | null>(null)
  const observedActions = useRef(new Set<string>())
  const activeTurn = conversation?.turns.find(isTurnActive)

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    mutations.current = new AbortController()
    void listAssistantSessions(department, controller.signal).then((items) => {
      if (controller.signal.aborted) return
      setSessions(items)
      setSessionId(items[0]?.id ?? null)
      setLoading(false)
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : '会话读取失败'); setLoading(false) }
    })
    return () => { mounted.current = false; controller.abort(); mutations.current.abort() }
  }, [department])

  useSerialPoll(async (signal) => {
    const id = activeId.current
    if (!id) return
    const result = await getAssistantConversation(id, signal)
    if (signal.aborted || activeId.current !== id) return
    setConversation(result)
    setSessions((items) => items.map((item) => item.id === id ? result.session : item))
    for (const turn of result.turns) for (const action of turn.actions) {
      if (action.status !== 'saved' || observedActions.current.has(action.id)) continue
      observedActions.current.add(action.id)
      notifyPlatformCamerasChanged()
      if (action.resource.kind === 'department_features') void refreshMe().catch(() => setError('权限已保存，账号权限刷新失败，请刷新页面'))
    }
  }, { intervalMs: activeTurn || sending ? 800 : 5000, timeoutMs: 8000, enabled: !!sessionId, restartKey: sessionId ?? '',
    onError: (reason) => setError(reason instanceof Error ? reason.message : '任务状态读取失败') })

  const selectSession = (id: string) => { activeId.current = id; setSessionId(id); setConversation(null); setError(''); retry.current = null }
  const newSession = async () => {
    if (sending) return
    setSending(true); setError('')
    try {
      const item = await createAssistantSession(department, mutations.current.signal)
      if (!mounted.current) return
      setSessions((items) => [item, ...items]); selectSession(item.id)
      setConversation({ session: item, turns: [], hidden_turns: 0 })
    } catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '创建会话失败') }
    finally { if (mounted.current) setSending(false) }
  }
  const send = async (text: string): Promise<boolean> => {
    if (sending || activeTurn || !text.trim()) return false
    setSending(true); setError('')
    let id = sessionId
    try {
      if (!id) {
        const item = await createAssistantSession(department, mutations.current.signal)
        if (!mounted.current) return false
        id = item.id
        setSessions((items) => [item, ...items]); selectSession(id)
        setConversation({ session: item, turns: [], hidden_turns: 0 })
      }
      const payload = retry.current?.text === text ? retry.current : { request_id: requestId(), text }
      retry.current = payload
      const turn = await sendAssistantMessage(id, payload, mutations.current.signal)
      if (!mounted.current || activeId.current !== id) return false
      retry.current = null
      setConversation((current) => current && current.session.id === id ? {
        ...current, turns: [...current.turns.filter((item) => item.id !== turn.id), turn],
      } : current)
      return true
    } catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '发送失败；重试会沿用请求编号') }
    finally { if (mounted.current) setSending(false) }
    return false
  }
  const cancel = async () => {
    if (!sessionId || !activeTurn) return
    try { await cancelAssistantTurn(sessionId, activeTurn.id, mutations.current.signal) }
    catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : '停止失败') }
  }
  return { sessions, sessionId, conversation, loading, sending, error, activeTurn, selectSession, newSession, send, cancel }
}
