import { useEffect, useRef, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  createHorn, getHorn, getHornStatus, listHorns, testHornConnection, updateHorn,
  type HornConnectionInput, type HornDevice, type HornWrite, type HornScope,
} from '@/lib/horns'

const POLL_INTERVAL_MS = 5000
const READ_TIMEOUT_MS = 8000
const ACTION_TIMEOUT_MS = 20000

export function useHornDevices(isAdmin: boolean, scope: HornScope | null) {
  const [devices, setDevices] = useState<HornDevice[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const generation = useRef(0)
  const action = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  const canManage = useRef(isAdmin)

  useEffect(() => {
    canManage.current = isAdmin && scope !== null
    generation.current += 1
    action.current?.abort()
    setDevices([]); setLoading(true); setLoadError(''); setError(''); setMessage('')
  }, [isAdmin, scope])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      generation.current += 1
      action.current?.abort()
    }
  }, [])

  const load = async (signal: AbortSignal) => {
    if (!isAdmin || !scope || !canManage.current || action.current) return
    const requestGeneration = generation.current
    let items: HornDevice[]
    try {
      items = await listHorns(scope, signal)
    } catch (reason) {
      if (signal.aborted && mounted.current && requestGeneration === generation.current) {
        setLoading(false)
        setLoadError('设备列表读取超时或中断，请刷新重试。')
        return
      }
      throw reason
    }
    if (signal.aborted || !mounted.current || requestGeneration !== generation.current) return
    setDevices(items)
    setLoading(false)
    setLoadError('')
  }

  useSerialPoll(load, {
    intervalMs: POLL_INTERVAL_MS, timeoutMs: READ_TIMEOUT_MS,
    enabled: isAdmin && scope !== null && !busy, restartKey: `${scope}:${revision}`,
    onError: (reason) => {
      setLoading(false)
      setLoadError(`设备列表读取失败：${reason instanceof Error ? reason.message : '请检查网络连接。'}`)
    },
  })

  const perform = async <T,>(operation: (signal: AbortSignal) => Promise<T>, success: string): Promise<T | undefined> => {
    if (!isAdmin || !canManage.current || action.current || !mounted.current) return undefined
    const controller = new AbortController()
    action.current = controller
    generation.current += 1
    setBusy(true)
    setError('')
    setMessage('')
    const timer = window.setTimeout(() => controller.abort(), ACTION_TIMEOUT_MS)
    try {
      const result = await operation(controller.signal)
      if (!mounted.current || controller.signal.aborted) return undefined
      setMessage(success)
      return result
    } catch (reason) {
      if (mounted.current) {
        setError(controller.signal.aborted
          ? '请求超时，请刷新列表确认设备状态后再操作。'
          : reason instanceof Error ? reason.message : '操作失败，请检查网络连接。')
      }
      return undefined
    } finally {
      window.clearTimeout(timer)
      if (action.current === controller) action.current = null
      if (mounted.current) setBusy(false)
    }
  }

  const acceptDevice = (device: HornDevice, signal: AbortSignal) => {
    if (signal.aborted || !mounted.current) return
    setDevices((current) => [...current.filter((item) => item.id !== device.id),
      ...(device.department === (scope === 'unassigned' ? null : scope) ? [device] : [])].sort((a, b) => a.id - b.id))
  }

  const saveDevice = (id: number | undefined, payload: HornWrite) => perform(async (signal) => {
    if (id === undefined && !payload.password) throw new Error('新建设备必须输入密码。')
    const device = id === undefined
      ? await createHorn({ ...payload, password: payload.password! }, signal)
      : await updateHorn(id, payload, scope!, signal)
    acceptDevice(device, signal)
    return device
  }, '设备配置已保存，运行状态会自动更新。')

  const setEnabled = (device: HornDevice, enable: boolean) => perform(async (signal) => {
    const updated = await updateHorn(device.id, { enable }, scope!, signal)
    acceptDevice(updated, signal)
    return updated
  }, enable ? '设备已启用，正在连接。' : '设备已停用。')

  const checkConnection = (payload: HornConnectionInput) => perform(async (signal) => {
    const result = await testHornConnection(payload, scope!, signal)
    if (payload.horn_id !== undefined) {
      // 临时测试结果与运行状态分开；测试成功不能把已停用设备显示成运行中。
      const runtime = await getHornStatus(payload.horn_id, scope!, signal)
      if (!signal.aborted && mounted.current) {
        setDevices((current) => current.map((item) => item.id === payload.horn_id ? { ...item, runtime } : item))
      }
    }
    return result
  }, '')

  return {
    devices, loading, loadError, error, message, busy,
    refresh: () => { if (isAdmin && !action.current) { setLoading(true); setRevision((value) => value + 1) } },
    clearFeedback: () => { setError(''); setMessage('') },
    loadDevice: (id: number) => perform((signal) => getHorn(id, scope!, signal), ''),
    saveDevice, setEnabled, checkConnection,
  }
}
