import { useEffect, useMemo, useState } from 'react'
import { Camera, Copy, Power, PowerOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  getAiVisionFeatureConfig,
  type AiVisionCamera,
  isAiVisionFeatureEnabled,
  saveAiVisionFeatureConfig,
} from '@/lib/aivision'

type FeatureCameraManagerProps = {
  cameras: AiVisionCamera[]
  feature: string
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

  const handleEnableExisting = async () => {
    const shmName = selectedExistingCamera.trim()
    if (!shmName) return

    setWorkingCamera(shmName)
    try {
      await onAddCamera(shmName)
      setSelectedExistingCamera('')
      window.dispatchEvent(new Event('aivision:cameras-changed'))
    } finally {
      setWorkingCamera('')
    }
  }

  const handleRemove = async (shmName: string) => {
    setWorkingCamera(shmName)
    try {
      await onRemoveCamera(shmName)
      window.dispatchEvent(new Event('aivision:cameras-changed'))
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
      const sourceConfig = await getAiVisionFeatureConfig(feature, source)
      await saveAiVisionFeatureConfig(feature, target, {
        ...sourceConfig.config,
        enable: true,
      })
      await onConfigCopied?.(target)
      setCopyTargetCamera('')
      window.dispatchEvent(new Event('aivision:cameras-changed'))
    } catch (error) {
      setCopyError(`复制失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setWorkingCamera('')
    }
  }

  return (
    <Card className="overflow-hidden border-white/80 bg-white shadow-[0_18px_48px_rgba(20,50,92,0.10)] dark:border-slate-800 dark:bg-slate-900/92">
      <CardHeader className="border-b border-slate-100 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] dark:border-slate-800 dark:bg-none dark:bg-slate-900">
        <CardTitle className="flex items-center gap-3 text-lg font-black text-[#071d3d] dark:text-slate-100">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_12px_24px_rgba(0,27,67,0.22)] dark:bg-blue-600">
            <Camera className="h-5 w-5" />
          </span>
          摄像头管理
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 bg-[#f8fbff] p-4 sm:p-5 dark:bg-slate-950/30">
        <div className="space-y-3 rounded-2xl border border-emerald-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">当前功能摄像头</div>
            <div className="mt-1 text-xs font-medium text-slate-500">这里的摄像头会运行当前检测功能，并用于预览、ROI 和告警配置。</div>
          </div>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/80">
            {enabledCameras.length === 0 ? (
              <div className="px-4 py-5 text-sm text-slate-500">当前功能还没有加入摄像头。</div>
            ) : (
              enabledCameras.map((camera) => {
                const active = camera.shm_name === currentCameraName
                return (
                  <div
                    key={camera.id}
                    className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 transition hover:bg-emerald-50/60 last:border-b-0 dark:border-slate-800 dark:hover:bg-slate-800/60"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectCamera(camera.shm_name)}
                      className="min-w-0 text-left"
                      disabled={disabled}
                    >
                      <div className="truncate text-sm font-bold text-[#071d3d] dark:text-slate-100">{camera.name}</div>
                      <div className="text-xs text-slate-500">{active ? '当前正在编辑' : '点击切换配置'}</div>
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

        <div className="space-y-3 rounded-2xl border border-blue-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">从已有摄像头加入当前功能</div>
            <div className="mt-1 text-xs font-medium text-slate-500">选择平台汇总里维护的摄像头，并加入当前检测功能。</div>
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
                  <SelectItem key={camera.id} value={camera.shm_name}>
                    {camera.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              className="gap-2"
              onClick={handleEnableExisting}
              disabled={disabled || Boolean(workingCamera) || !selectedExistingCamera}
            >
              <Power className="h-4 w-4" />
              加入当前功能
            </Button>
          </div>
        </div>

        <div className="space-y-3 rounded-2xl border border-blue-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
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
      </CardContent>
    </Card>
  )
}
