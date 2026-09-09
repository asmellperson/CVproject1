import { useMemo, useState } from 'react'
import { Box, RefreshCw, Save } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DETECTION_CONFIG_CARD_CLASS,
  DetectionConfigCardContent,
  DetectionConfigCardHeader,
} from '@/components/detection/DetectionConfigUi'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getAiVisionModels, updateAiVisionModelPath, type AiVisionModel } from '@/lib/aivision'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { useAuth } from '@/auth/useAuth'

type AiVisionModelConfigProps = {
  requiredModels: string[]
}

const STATUS_LABELS: Record<AiVisionModel['runtime']['status'], string> = {
  not_started: '未启动', running: '运行中', starting: '加载中', backoff: '等待重试',
  exhausted: '重试已耗尽', stopped: '已停止', failed: '加载失败',
}

export function AiVisionModelConfig({ requiredModels }: AiVisionModelConfigProps) {
  const { isAdmin } = useAuth()
  const [models, setModels] = useState<AiVisionModel[]>([])
  const [paths, setPaths] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('正在读取模型配置...')
  const [loadFailed, setLoadFailed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [savingName, setSavingName] = useState<string | null>(null)
  const [waitingModel, setWaitingModel] = useState<string | null>(null)

  const loadModels = async (signal?: AbortSignal, resetPaths = false) => {
    const items = await getAiVisionModels(signal)
    if (signal?.aborted) return
    setModels(items)
    setPaths((previous) => Object.fromEntries(items.map((model) => [
      model.name, resetPaths ? model.path : previous[model.name] ?? model.path,
    ])))
    setLoadFailed(false)
    setLoading(false)
    if (loading && waitingModel === null && savingName === null) {
      setMessage('模型配置和运行状态读取成功。')
    }
    const updated = items.find((model) => model.name === waitingModel)
    if (updated && updated.reload.status !== 'loading' && updated.reload.status !== 'idle') {
      if (updated.reload.status === 'succeeded') {
        setMessage(`配置保存成功；${updated.name} 模型加载成功。`)
      } else if (updated.reload.status === 'failed') {
        setMessage(`配置已保存，但 ${updated.name} 模型加载失败：${updated.reload.error}`)
      } else {
        setMessage('配置保存成功；运行服务未启动，模型将在服务启动时加载。')
      }
      setWaitingModel(null)
    }
  }

  useSerialPoll(loadModels, {
    intervalMs: 2000,
    timeoutMs: 8000,
    enabled: savingName === null,
    onError: (error) => {
      setLoadFailed(true)
      setLoading(false)
      setMessage(`模型状态读取失败：${error instanceof Error ? error.message : String(error)}`)
    },
  })

  const visibleModels = useMemo(() => requiredModels.map((name) => ({
    name, model: models.find((item) => item.name === name),
  })), [models, requiredModels])

  const saveModelPath = async (model: AiVisionModel) => {
    if (!isAdmin) return
    setSavingName(model.name)
    setMessage(`正在保存 ${model.name} 的本机模型路径...`)
    try {
      const result = await updateAiVisionModelPath(model.name, paths[model.name] ?? '')
      setPaths((previous) => ({ ...previous, [model.name]: result.path }))
      if (result.load_status === 'loading') {
        setWaitingModel(model.name)
        setMessage('配置保存成功，正在重载模型；加载结果会自动更新。')
      } else {
        setMessage('配置保存成功；运行服务未启动，模型将在服务启动时加载。')
      }
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSavingName(null)
    }
  }

  const refreshModels = () => {
    setLoading(true)
    loadModels(undefined, true).catch((error) => {
      setLoadFailed(true)
      setLoading(false)
      setMessage(`模型状态读取失败：${error instanceof Error ? error.message : String(error)}`)
    })
  }

  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader
        icon={Box}
        tone="violet"
        title="模型配置"
        description="查看固定模型的真实运行状态，保存本机路径后自动重载。"
        actions={(
          <Button variant="outline" className="gap-2 rounded-xl" onClick={refreshModels} disabled={loading || savingName !== null}>
            <RefreshCw className="h-4 w-4" />
            {loading ? '读取中' : '重新读取'}
          </Button>
        )}
      />
      <DetectionConfigCardContent className="space-y-5">
        {loadFailed ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            无法读取本机模型配置或运行状态，请查看下方错误信息。
          </div>
        ) : requiredModels.length === 0 ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            该功能不需要推理模型。
          </div>
        ) : (
          <div className="space-y-4">
            {visibleModels.map(({ name, model }) => (
              <div key={name} className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] p-4 dark:border-slate-800 dark:bg-slate-950/40">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-900">{name}</div>
                    {model ? <div className="text-xs text-slate-500">类型：{model.type}</div> : null}
                  </div>
                  <Badge variant={model?.runtime.running ? 'default' : 'outline'}>
                    {model ? STATUS_LABELS[model.runtime.status] : (loading ? '读取中' : '未注册')}
                  </Badge>
                </div>

                {model ? (
                  <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
                    <div className="space-y-2">
                      <Label htmlFor={`model-path-${model.name}`}>本机模型路径</Label>
                      <Input
                        id={`model-path-${model.name}`}
                        value={paths[model.name] ?? ''}
                        onChange={(event) => setPaths((prev) => ({ ...prev, [model.name]: event.target.value }))}
                        className="font-mono"
                        disabled={!isAdmin || loading || savingName !== null || waitingModel !== null}
                      />
                    </div>
                    <Button className="gap-2" onClick={() => saveModelPath(model)} disabled={!isAdmin || loading || savingName !== null || waitingModel !== null}>
                      <Save className="h-4 w-4" />
                      {savingName === model.name ? '保存中' : waitingModel === model.name ? '加载中' : '保存路径'}
                    </Button>
                  </div>
                ) : (
                  <div className="text-sm text-slate-500">
                    {loading ? '正在读取固定模型...' : '系统未注册该模型，请检查服务版本。'}
                  </div>
                )}
                {model?.runtime.loaded_path ? <div className="text-xs text-slate-500">实际加载：{model.runtime.loaded_path}</div> : null}
                {model && model.runtime.shared_models.length > 1 ? (
                  <div className="text-xs text-slate-500">共享权重：{model.runtime.shared_models.join('、')}</div>
                ) : null}
                {model?.reload.status === 'failed' ? (
                  <div className="text-sm text-red-600 dark:text-red-400">最近重载失败：{model.reload.error}</div>
                ) : model?.runtime.last_failure ? <div className="text-sm text-red-600 dark:text-red-400">{model.runtime.last_failure}</div> : null}
              </div>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-[#E8ECF5] bg-[#F5F7FA] px-4 py-3 text-sm font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-300">{message}</div>
      </DetectionConfigCardContent>
    </Card>
  )
}
