import { useEffect, useMemo, useState } from 'react'
import { Camera, Copy, Plus, Power, PowerOff } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DETECTION_CONFIG_CARD_CLASS,
  DetectionConfigCardContent,
  DetectionConfigCardHeader,
} from '@/components/detection/DetectionConfigUi'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  createAiVisionFeatureCamera,
  getAiVisionFeatureConfig,
  type AiVisionCamera,
  isAiVisionFeatureEnabled,
  saveAiVisionFeatureConfig,
} from '@/lib/aivision'
import { notifyPlatformCamerasChanged } from '@/lib/camera-events'
import { LogisticsCameraCreateDialog } from '@/components/logistics_single_person/LogisticsCameraCreateDialog'
import type { LogisticsCameraCreateInput } from '@/components/logistics_single_person/logisticsCameraCreateState'

type FeatureCameraManagerProps = {
  cameras: AiVisionCamera[]
  feature: string
  department: string
  currentCameraName: string
  disabled?: boolean

  onSelectCamera: (shmName: string) => void

  onAddCamera: (shmName: string) => Promise<void>

  onRemoveCamera: (shmName: string) => Promise<void>

  onConfigCopied?: (targetShmName: string) => void | Promise<void>
}

export function FeatureCameraManager({
  cameras,
  feature,
  department,
  currentCameraName,
  disabled,
  onSelectCamera,
  onAddCamera,
  onRemoveCamera,
  onConfigCopied,
}: FeatureCameraManagerProps) {
  const [workingCamera, setWorkingCamera] = useState('')
  const [selectedExistingCamera, setSelectedExistingCamera] = useState('')
  const [copySourceCamera, setCopySourceCamera] = useState('')
  const [copyTargetCamera, setCopyTargetCamera] = useState('')
  const [copyError, setCopyError] = useState('')
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

  const enabledCameras = useMemo(
    () => cameras.filter((camera) => isAiVisionFeatureEnabled(camera, feature)),
    [cameras, feature],
  )
  const availableCameras = useMemo(
    () => cameras.filter((camera) => !isAiVisionFeatureEnabled(camera, feature)),
    [cameras, feature],
  )

  useEffect(() => {
    if (selectedExistingCamera && !availableCameras.some((camera) => camera.shm_name === selectedExistingCamera)) {
      setSelectedExistingCamera('')
    }
  }, [availableCameras, selectedExistingCamera])

  useEffect(() => {
    if (copySourceCamera && !cameras.some((camera) => camera.shm_name === copySourceCamera)) {
      setCopySourceCamera('')
    }
    if (copyTargetCamera && !cameras.some((camera) => camera.shm_name === copyTargetCamera)) {
      setCopyTargetCamera('')
    }
  }, [cameras, copySourceCamera, copyTargetCamera])

  const canAddSelectedCamera = availableCameras.some((camera) => camera.shm_name === selectedExistingCamera && camera.enabled)

  const handleEnableExisting = async () => {
    const shmName = selectedExistingCamera.trim()
    if (!shmName || !canAddSelectedCamera) return

    setWorkingCamera(shmName)
    try {
      await onAddCamera(shmName)
      setSelectedExistingCamera('')
      notifyPlatformCamerasChanged()
    } catch (error) {
      setCopyError(`操作失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setWorkingCamera('')
    }
  }

  const handleRemove = async (shmName: string) => {
    setWorkingCamera(shmName)
    try {
      await onRemoveCamera(shmName)
      notifyPlatformCamerasChanged()
    } catch (error) {
      setCopyError(`操作失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setWorkingCamera('')
    }
  }

  const handleCopyConfig = async () => {
    const source = copySourceCamera.trim()
    const target = copyTargetCamera.trim()
    if (!source || !target || source === target) {
      setCopyError('请选择不同的源摄像头和目标摄像头。')
      return
    }

    setWorkingCamera(target)
    setCopyError('')
    try {
      const [sourceConfig, targetConfig] = await Promise.all([
        getAiVisionFeatureConfig(feature, source), getAiVisionFeatureConfig(feature, target),
      ])
      await saveAiVisionFeatureConfig(feature, target, {
        ...sourceConfig.config,
        enable: targetConfig.config.enable,
      })
      await onConfigCopied?.(target)
      setCopyTargetCamera('')
      notifyPlatformCamerasChanged()
    } catch (error) {
      setCopyError(`复制失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setWorkingCamera('')
    }
  }

  const handleCreateCamera = async (payload: LogisticsCameraCreateInput) => {
    setWorkingCamera('__creating__')
    try {
      const camera = await createAiVisionFeatureCamera(feature, {
        ...payload,
        department,
        enabled: true,
      })
      onSelectCamera(camera.shm_name)
    } finally {
      setWorkingCamera('')
    }
  }

  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader
        icon={Camera}
        tone="blue"
        title="摄像头"
        description="管理当前检测功能绑定的摄像头，并保持平台汇总与配置页面同步。"
      />
      <DetectionConfigCardContent className="space-y-4">
        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">当前功能摄像头</div>
            <div className="mt-1 text-xs font-medium text-slate-500">当前功能已启用的摄像头；全局停用的摄像头不会运行检测。</div>
          </div>
          <div className="overflow-hidden rounded-xl border border-[#E2E7F2] bg-white dark:border-slate-800 dark:bg-slate-900/80">
            {enabledCameras.length === 0 ? (
              <div className="px-4 py-5 text-sm text-slate-500">当前功能还没有加入摄像头。</div>
            ) : (
              enabledCameras.map((camera) => {
                const active = camera.shm_name === currentCameraName
                return (
                  <div
                    key={camera.id}
                    className={`flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 transition last:border-b-0 dark:border-slate-800 dark:hover:bg-slate-800/60 ${active ? 'bg-blue-50/70 ring-1 ring-inset ring-blue-100 dark:bg-blue-950/30 dark:ring-blue-900' : 'hover:bg-slate-50'}`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectCamera(camera.shm_name)}
                      className="min-w-0 text-left"
                      disabled={disabled}
                    >
                      <div className="truncate text-sm font-bold text-[#071d3d] dark:text-slate-100">{camera.name}{!camera.enabled && <Badge variant="secondary" className="ml-2 bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300">摄像头已停用</Badge>}</div>
                      <div className="mt-1 text-xs text-slate-500">{active ? <span className="rounded-md bg-blue-100 px-2 py-0.5 font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">当前正在编辑</span> : '点击切换配置'}</div>
                    </button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-2 text-amber-700 hover:text-amber-800"
                      onClick={() => handleRemove(camera.shm_name)}
                      disabled={disabled || Boolean(workingCamera)}
                    >
                      <PowerOff className="h-4 w-4" />
                      停用当前功能
                    </Button>
                  </div>
                )
              })
            )}
          </div>
        </div>

        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">从已有摄像头加入当前功能</div>
            <div className="mt-1 text-xs font-medium text-slate-500">从平台全局摄像头池选择；已有明确归属时，加入当前功能不会修改摄像头的所属事业部或公司。停用摄像头需先在平台启用。</div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Select
              value={selectedExistingCamera}
              onValueChange={setSelectedExistingCamera}
              disabled={disabled || Boolean(workingCamera) || availableCameras.length === 0}
            >
              <SelectTrigger className="min-w-0 flex-1 bg-white sm:min-w-60">
                <SelectValue placeholder={availableCameras.length === 0 ? '暂无可启用摄像头' : '选择已有摄像头'} />
              </SelectTrigger>
              <SelectContent>
                {availableCameras.map((camera) => (
                  <SelectItem key={camera.id} value={camera.shm_name} disabled={!camera.enabled}>
                    {camera.name}{!camera.enabled ? '（已停用）' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              className="gap-2"
              onClick={handleEnableExisting}
              disabled={disabled || Boolean(workingCamera) || !canAddSelectedCamera}
            >
              <Power className="h-4 w-4" />
              加入当前功能
            </Button>
          </div>
        </div>

        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">新建摄像头并加入当前功能</div>
            <div className="mt-1 text-xs font-medium text-slate-500">新摄像头归属当前页面对应的事业部或公司，并在保存后启用当前检测功能。</div>
          </div>
          <Button
            className="gap-2"
            onClick={() => setCreateDialogOpen(true)}
            disabled={disabled || Boolean(workingCamera)}
          >
            <Plus className="h-4 w-4" />
            新建摄像头并加入
          </Button>
        </div>

        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">复制当前功能配置</div>
            <div className="mt-1 text-xs font-medium text-slate-500">将一个摄像头的当前功能参数、ROI 和告警配置复制到另一个摄像头。</div>
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <Select
              value={copySourceCamera}
              onValueChange={setCopySourceCamera}
              disabled={disabled || Boolean(workingCamera) || enabledCameras.length === 0}
            >
              <SelectTrigger className="min-w-0 bg-white">
                <SelectValue placeholder={enabledCameras.length === 0 ? '暂无源摄像头' : '源摄像头'} />
              </SelectTrigger>
              <SelectContent>
                {enabledCameras.map((camera) => (
                  <SelectItem key={camera.id} value={camera.shm_name}>
                    {camera.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={copyTargetCamera}
              onValueChange={setCopyTargetCamera}
              disabled={disabled || Boolean(workingCamera) || cameras.length < 2}
            >
              <SelectTrigger className="min-w-0 bg-white">
                <SelectValue placeholder={cameras.length < 2 ? '暂无目标摄像头' : '目标摄像头'} />
              </SelectTrigger>
              <SelectContent>
                {cameras
                  .filter((camera) => camera.shm_name !== copySourceCamera)
                  .map((camera) => (
                    <SelectItem key={camera.id} value={camera.shm_name}>
                      {camera.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Button
              className="gap-2"
              onClick={handleCopyConfig}
              disabled={disabled || Boolean(workingCamera) || !copySourceCamera || !copyTargetCamera || copySourceCamera === copyTargetCamera}
            >
              <Copy className="h-4 w-4" />
              {workingCamera === copyTargetCamera ? '复制中' : '复制配置'}
            </Button>
          </div>
          {copyError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{copyError}</div> : null}
        </div>
      </DetectionConfigCardContent>
      {createDialogOpen ? (
        <LogisticsCameraCreateDialog
          title="新建摄像头并加入当前功能"
          description="填写摄像头信息，保存后将直接启用当前检测功能。"
          submitLabel="新建并加入"
          onClose={() => setCreateDialogOpen(false)}
          onSubmit={handleCreateCamera}
        />
      ) : null}
    </Card>
  )
}
