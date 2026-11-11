import { useEffect, useRef, useState } from 'react'

type Options<Config, Draft> = {
  cameraKey: string
  configVersion: number
  canConfigure: boolean
  read: (key: string) => Promise<Config>
  write: (key: string, config: Config) => Promise<Config>
  createDraft: (config: Config) => Draft
  buildConfig: (draft: Draft) => Config
}

/** 摄像头由页面统一选择，所有配置标签共用草稿和请求代次。 */
export function useFeatureConfigDraft<Config, Draft>({
  cameraKey, configVersion, canConfigure, read, write, createDraft, buildConfig,
}: Options<Config, Draft>) {
  const identity = JSON.stringify([cameraKey, configVersion])
  const selected = useRef(identity)
  selected.current = identity
  const revision = useRef(0)
  const mutation = useRef<symbol | null>(null)
  const [saving, setSaving] = useState(false)
  const [state, setState] = useState<{ identity: string; draft: Draft | null; loading: boolean; message: string }>({
    identity, draft: null, loading: Boolean(cameraKey), message: '',
  })

  useEffect(() => {
    const request = ++revision.current
    mutation.current = null
    setSaving(false)
    setState({ identity, draft: null, loading: Boolean(cameraKey), message: cameraKey ? '正在读取配置…' : '请先添加并选择摄像头。' })
    const current = () => request === revision.current && selected.current === identity
    if (cameraKey) {
      void read(cameraKey).then((config) => {
        if (current()) setState({ identity, draft: createDraft(config), loading: false, message: '当前摄像头配置已加载。' })
      }).catch((cause: unknown) => {
        if (current()) setState({ identity, draft: null, loading: false, message: `读取失败：${String(cause)}` })
      })
    }
    return () => { revision.current += 1 }
  }, [cameraKey, configVersion, identity, read, createDraft])

  const active = state.identity === identity
  const disabled = !canConfigure || !active || state.loading || saving || !state.draft
  const update = (change: (draft: Draft) => Draft) => {
    if (disabled || mutation.current) return
    setState((previous) => previous.identity === identity && previous.draft
      ? { ...previous, draft: change(previous.draft) } : previous)
  }
  const save = async () => {
    if (disabled || !state.draft || mutation.current) return
    const request = revision.current
    const token = Symbol()
    mutation.current = token
    setSaving(true)
    setState((previous) => ({ ...previous, message: '正在保存当前摄像头配置…' }))
    const current = () => request === revision.current && selected.current === identity
    try {
      const config = await write(cameraKey, buildConfig(state.draft))
      if (current()) setState({ identity, draft: createDraft(config), loading: false, message: '当前摄像头配置已保存。' })
    } catch (cause) {
      if (current()) setState((previous) => ({ ...previous, message: `保存失败：${String(cause)}` }))
    } finally {
      // 旧摄像头请求结束时不能释放新摄像头的保存门控。
      if (mutation.current === token) mutation.current = null
      if (current()) setSaving(false)
    }
  }
  return {
    draft: active ? state.draft : null, disabled, saving: active && saving,
    message: active ? state.message : '正在读取配置…', update, save,
  }
}
