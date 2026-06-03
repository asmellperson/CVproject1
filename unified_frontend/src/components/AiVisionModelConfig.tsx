import { useEffect, useMemo, useState } from 'react'
import { Box, RefreshCw, Save } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { createAiVisionModel, getAiVisionModels, updateAiVisionModel, type AiVisionModel } from '@/lib/aivision'
import { useAuth } from '@/auth/useAuth'

type AiVisionModelConfigProps = {
  requiredModels: string[]
}

export function AiVisionModelConfig({ requiredModels }: AiVisionModelConfigProps) {
  const { isAdmin } = useAuth()
  const [models, setModels] = useState<AiVisionModel[]>([])
  const [paths, setPaths] = useState<Record<number, string>>({})
  const [newPaths, setNewPaths] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('正在读取模型配置...')
  const [loadFailed, setLoadFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [creatingName, setCreatingName] = useState<string | null>(null)

  const loadModels = async () => {
    setLoading(true)
    setLoadFailed(false)
    setMessage('正在读取模型配置...')
    try {
      const items = await getAiVisionModels()
      setModels(items)
      setPaths(Object.fromEntries(items.map((model) => [model.id, model.path || ''])))
      setMessage('模型配置读取成功。')
    } catch (error) {
      setModels([])
      setLoadFailed(true)
      setMessage(`模型配置读取失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadModels()
  }, [])

  const visibleModels = useMemo(() => {
    if (requiredModels.length === 0) return []
    return requiredModels.map((name) => ({
      name,
      model: models.find((item) => item.name === name),
    }))
  }, [models, requiredModels])

  const saveModelPath = async (model: AiVisionModel) => {
    if (!isAdmin) {
      setMessage('当前账号为 viewer，只能查看模型配置。')
      return
    }
    setSavingId(model.id)
    setMessage(`正在保存 ${model.name} 模型路径...`)
    try {
      const updated = await updateAiVisionModel(model.id, { path: paths[model.id] ?? '' })
      setModels((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      setPaths((prev) => ({ ...prev, [updated.id]: updated.path || '' }))
      setMessage(`保存成功：${updated.name} 模型路径已更新。`)
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setSavingId(null)
    }
  }

  const modelDefaults = (name: string) => {
    const defaults: Record<string, { description: string }> = {
      yolo_human: { description: '{"class_filter":[0],"type_label":"person"}' },
      yolo_phone: { description: '{"class_filter":[1],"type_label":"phone"}' },
      yolo_face: { description: '{"type_label":"face","conf":0.6}' },
    }
    return {
      type: 'yolo',
      import_path: 'platform.inference.workers.yolo_detector.YoloDetectorWorker',
      enable: true,
      description: defaults[name]?.description || '{}',
    }
  }

  const createMissingModel = async (name: string) => {
    if (!isAdmin) {
      setMessage('当前账号为 viewer，只能查看模型配置。')
      return
    }
    const path = (newPaths[name] || '').trim()
    if (!path) {
      setMessage(`创建失败：请先填写 ${name} 的模型路径。`)
      return
    }

    setCreatingName(name)
    setMessage(`正在创建 ${name} 模型配置...`)
    try {
      const created = await createAiVisionModel({
        name,
        path,
        ...modelDefaults(name),
      })
      setModels((prev) => [...prev, created])
      setPaths((prev) => ({ ...prev, [created.id]: created.path || '' }))
      setNewPaths((prev) => ({ ...prev, [name]: '' }))
      setMessage(`创建成功：${created.name} 模型配置已写入数据库。`)
    } catch (error) {
      setMessage(`创建失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setCreatingName(null)
    }
  }

  return (
    <Card className="overflow-hidden border-white/80 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.10)] dark:border-slate-800 dark:bg-slate-900/92">
      <CardHeader className="flex flex-col items-start justify-between gap-4 border-b border-slate-100 bg-[linear-gradient(180deg,#fbf7ff_0%,#ffffff_100%)] sm:flex-row sm:items-center dark:border-slate-800 dark:bg-slate-900">
        <CardTitle className="flex items-center gap-3 text-lg font-black text-[#071d3d] dark:text-slate-100">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-600 text-white shadow-[0_12px_24px_rgba(124,58,237,0.22)]">
            <Box className="h-5 w-5" />
          </span>
          模型配置
        </CardTitle>
        <Button variant="outline" className="gap-2" onClick={loadModels} disabled={loading || savingId !== null}>
          <RefreshCw className="h-4 w-4" />
          {loading ? '读取中' : '重新读取'}
        </Button>
      </CardHeader>
      <CardContent className="space-y-5 bg-[#fbf8ff] p-4 sm:p-5 dark:bg-slate-950/30">
        {loadFailed ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            模型接口不可用。请确认 AiVision 后端已重启并加载最新接口。
          </div>
        ) : requiredModels.length === 0 ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            该功能不需要推理模型。
          </div>
        ) : (
          <div className="space-y-4">
            {visibleModels.map(({ name, model }) => (
              <div key={name} className="space-y-3 rounded-2xl border border-violet-100 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-900">{name}</div>
                    {model ? <div className="text-xs text-slate-500">类型：{model.type}</div> : null}
                  </div>
                  <Badge variant={model?.enable ? 'default' : 'outline'}>{model ? (model.enable ? '已启用' : '未启用') : '未找到'}</Badge>
                </div>

                {model ? (
                  <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
                    <div className="space-y-2">
                      <Label htmlFor={`model-path-${model.id}`}>模型路径</Label>
                      <Input
                        id={`model-path-${model.id}`}
                        value={paths[model.id] ?? ''}
                        onChange={(event) => setPaths((prev) => ({ ...prev, [model.id]: event.target.value }))}
                        disabled={!isAdmin || loading || savingId !== null}
                      />
                    </div>
                    <Button className="gap-2" onClick={() => saveModelPath(model)} disabled={!isAdmin || loading || savingId !== null}>
                      <Save className="h-4 w-4" />
                      {savingId === model.id ? '保存中' : '保存路径'}
                    </Button>
                  </div>
                ) : (
                  <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
                    <div className="space-y-2">
                      <Label htmlFor={`new-model-path-${name}`}>模型路径</Label>
                      <Input
                        id={`new-model-path-${name}`}
                        value={newPaths[name] ?? ''}
                        onChange={(event) => setNewPaths((prev) => ({ ...prev, [name]: event.target.value }))}
                        placeholder="填写模型文件路径后创建"
                        disabled={!isAdmin || loading || creatingName !== null}
                      />
                    </div>
                    <Button className="gap-2" onClick={() => createMissingModel(name)} disabled={!isAdmin || loading || creatingName !== null}>
                      <Save className="h-4 w-4" />
                      {creatingName === name ? '创建中' : '创建模型'}
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="rounded-2xl border border-violet-100 bg-white px-4 py-3 text-sm font-medium text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">{message}</div>
      </CardContent>
    </Card>
  )
}
