import { useEffect, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { getHornSipServer, saveHornSipServer, type HornSipServer } from '@/lib/horns'

type Draft = Pick<HornSipServer, 'enabled' | 'address' | 'port'>

export function useHornSipSettings() {
  const [server, setServer] = useState<HornSipServer | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const mounted = useRef(true)
  const action = useRef<AbortController | null>(null)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; action.current?.abort() }
  }, [])
  useSerialPoll(async (signal) => {
    const value = await getHornSipServer(signal)
    if (!signal.aborted && mounted.current) {
      setServer(value)
      setDraft((current) => current ?? { enabled: value.enabled, address: value.address, port: value.port })
    }
  }, { enabled: !saving, intervalMs: 5000, timeoutMs: 8000,
    onError: (reason) => setError(reason instanceof Error ? reason.message : 'SIP 服务配置读取失败。') })

  const save = async () => {
    if (!draft || action.current) return
    if (draft.enabled && !draft.address.trim()) { setError('请输入喇叭可访问的本机局域网 IPv4 地址。'); return }
    if (!Number.isInteger(draft.port) || draft.port < 1024 || draft.port > 65535) { setError('SIP 服务端口必须是 1024–65535 的整数。'); return }
    const controller = new AbortController()
    action.current = controller
    const timer = window.setTimeout(() => controller.abort(), 15000)
    setSaving(true); setError(''); setMessage('')
    try {
      const value = await saveHornSipServer({ ...draft, address: draft.address.trim() }, controller.signal)
      if (!controller.signal.aborted && mounted.current) {
        setServer(value)
        setDraft({ enabled: value.enabled, address: value.address, port: value.port })
        setMessage(value.running ? 'SIP 服务已启动，启用的喇叭会自动同步服务地址。' : 'SIP 服务已停用。')
      }
    } catch (reason) {
      if (mounted.current) setError(controller.signal.aborted ? '保存超时，请刷新确认 SIP 服务状态。'
        : reason instanceof Error ? reason.message : 'SIP 配置保存失败。')
    } finally {
      window.clearTimeout(timer)
      if (action.current === controller) action.current = null
      if (mounted.current) setSaving(false)
    }
  }
  return { server, draft, setDraft, saving, error, message, save }
}
