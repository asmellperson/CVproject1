import { getEnabledFeatureCameras } from '@/lib/feature-cameras'
import type { DepartmentId } from '@/auth/permissions'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Camera, Copy, Plus } from 'lucide-react'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
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
  saveAiVisionFeatureConfig,
  saveAiVisionFeatureCameraOrder,
} from '@/lib/aivision'
import { notifyPlatformCamerasChanged } from '@/lib/camera-events'
import { LogisticsCameraCreateDialog } from '@/components/logistics_single_person/LogisticsCameraCreateDialog'
import { CameraZoomButton } from '@/components/camera/CameraZoomButton'
import type { LogisticsCameraCreateInput } from '@/components/logistics_single_person/logisticsCameraCreateState'

type FeatureCameraManagerProps = {
  cameras: AiVisionCamera[]
  feature: string
  department: DepartmentId
  currentCameraName: string
  disabled?: boolean

  onSelectCamera: (shmName: string) => void

  onCamerasChanged: (preferredCamera?: string) => Promise<unknown>

  onConfigCopied?: (targetShmName: string) => void | Promise<void>
}

export function FeatureCameraManager({
  cameras: sourceCameras,
  feature,
  department,
  currentCameraName,
  disabled,
  onSelectCamera,
  onCamerasChanged,
  onConfigCopied,
}: FeatureCameraManagerProps) {
  const cameras = useMemo(() => sourceCameras.filter((camera) => camera.department === department), [sourceCameras, department])
  const enabledCameras = useMemo(() => getEnabledFeatureCameras(cameras, feature, department), [cameras, feature, department])
  const availableCameras = cameras.filter((camera) => camera.enabled && !camera.functions[feature])
  const [existingCamera, setExistingCamera] = useState('')
  const cameraToAdd = availableCameras.find((camera) => camera.shm_name === existingCamera)
  const [workingCamera, setWorkingCamera] = useState('')
  const [copySourceCamera, setCopySourceCamera] = useState('')
  const [copyTargetCamera, setCopyTargetCamera] = useState('')
  const [operationError, setOperationError] = useState('')
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

  const canConfigure = useDepartmentConfigAccess(department, feature)
  const operationRef = useRef(0)
  const busyRef = useRef(false)
  const readOnly = !canConfigure || disabled || Boolean(workingCamera)

  useEffect(() => {
    setWorkingCamera('')
    setExistingCamera('')
    setCopySourceCamera('')
    setCopyTargetCamera('')
    setOperationError('')
    setCreateDialogOpen(false)
    busyRef.current = false
    return () => { operationRef.current += 1 }
  }, [department, feature])

  useEffect(() => {
    if (copySourceCamera && !enabledCameras.some((camera) => camera.shm_name === copySourceCamera)) {
      setCopySourceCamera('')
    }
    if (copyTargetCamera && !enabledCameras.some((camera) => camera.shm_name === copyTargetCamera)) {
      setCopyTargetCamera('')
    }
  }, [enabledCameras, copySourceCamera, copyTargetCamera])

  const handleToggle = async (camera: AiVisionCamera, enable: boolean) => {
    if (readOnly || busyRef.current) return
    if (enable && !camera.enabled) {
      setOperationError('请先在平台启用该摄像头')
      return
    }
    const operation = operationRef.current
    busyRef.current = true
    setWorkingCamera(camera.shm_name)
    setOperationError('')
    try {
      const payload = await getAiVisionFeatureConfig(feature, camera.shm_name)
      if (operation !== operationRef.current) return
      await saveAiVisionFeatureConfig(feature, camera.shm_name, { ...payload.config, enable })
      if (operation !== operationRef.current) return
      if (!enable && camera.shm_name === currentCameraName) onSelectCamera('')
      await onCamerasChanged(enable ? camera.shm_name : currentCameraName)
      if (operation === operationRef.current) {
        if (enable) setExistingCamera('')
        notifyPlatformCamerasChanged()
      }
    } catch (error) {
      if (operation === operationRef.current) setOperationError(`操作失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (operation === operationRef.current) {
        busyRef.current = false
        setWorkingCamera('')
      }
    }
  }

  const handleMove = async (index: number, direction: -1 | 1) => {
    const destination = index + direction
    if (readOnly || busyRef.current || destination < 0 || destination >= enabledCameras.length) return
    const operation = operationRef.current
    const ids = enabledCameras.map((camera) => camera.camera_id)
    ;[ids[index], ids[destination]] = [ids[destination], ids[index]]
    busyRef.current = true
    setWorkingCamera(enabledCameras[index].shm_name)
    setOperationError('')
    try {
      await saveAiVisionFeatureCameraOrder(feature, department, ids)
      if (operation !== operationRef.current) return
      await onCamerasChanged()
      if (operation === operationRef.current) notifyPlatformCamerasChanged()
    } catch (error) {
      if (operation !== operationRef.current) return
      setOperationError(`排序失败：${error instanceof Error ? error.message : String(error)}`)
      try {
        await onCamerasChanged()
      } catch (reloadError) {
        if (operation === operationRef.current) setOperationError(`重新加载失败：${reloadError instanceof Error ? reloadError.message : String(reloadError)}`)
      }
    } finally {
      if (operation === operationRef.current) {
        busyRef.current = false
        setWorkingCamera('')
      }
    }
  }

  const handleCopyConfig = async () => {
    if (readOnly || busyRef.current) return
    const operation = operationRef.current
    const source = copySourceCamera.trim()
    const target = copyTargetCamera.trim()
    if (!source || !target || source === target || !enabledCameras.some((camera) => camera.shm_name === source) || !enabledCameras.some((camera) => camera.shm_name === target)) {
      setOperationError('请选择不同的源摄像头和目标摄像头。')
      return
    }

    busyRef.current = true
    setWorkingCamera(target)
    setOperationError('')
    try {
      const [sourceConfig, targetConfig] = await Promise.all([
        getAiVisionFeatureConfig(feature, source), getAiVisionFeatureConfig(feature, target),
      ])
      if (operation !== operationRef.current) return
      if (!sourceConfig.config.enable || !targetConfig.config.enable) throw new Error('源和目标摄像头必须启用当前检测')
      await saveAiVisionFeatureConfig(feature, target, {
        ...sourceConfig.config,
        enable: targetConfig.config.enable,
      })
      if (operation !== operationRef.current) return
      await onCamerasChanged()
      if (operation !== operationRef.current) return
      await onConfigCopied?.(target)
      if (operation === operationRef.current) {
        setCopyTargetCamera('')
        notifyPlatformCamerasChanged()
      }
    } catch (error) {
      if (operation === operationRef.current) setOperationError(`复制失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (operation === operationRef.current) {
        busyRef.current = false
        setWorkingCamera('')
      }
    }
  }

  const handleCreateCamera = async (payload: LogisticsCameraCreateInput) => {
    if (readOnly || busyRef.current) throw new Error('当前无法新建摄像头')
    const operation = operationRef.current
    busyRef.current = true
    setWorkingCamera('__creating__')
    try {
      const camera = await createAiVisionFeatureCamera(feature, {
        ...payload,
        department,
        enabled: true,
      })
      if (operation !== operationRef.current) return
      await onCamerasChanged(camera.shm_name)
    } finally {
      if (operation === operationRef.current) {
        busyRef.current = false
        setWorkingCamera('')
      }
    }
  }

  return (
    <Card className={DETECTION_CONFIG_CARD_CLASS}>
      <DetectionConfigCardHeader
        icon={Camera}
        tone="blue"
        title="摄像头"
        description="管理已启用当前检测功能的摄像头、展示顺序和功能配置。"
      />
      <DetectionConfigCardContent className="space-y-4">
        {operationError ? <div role="alert" className="break-words rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{operationError}</div> : null}
        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">添加已有摄像头到当前功能</div>
            <div className="mt-1 text-xs font-medium text-slate-500">选择当前事业部尚未启用本功能的摄像头，添加后即可配置检测参数。</div>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Select value={cameraToAdd ? existingCamera : ''} onValueChange={setExistingCamera} disabled={readOnly || availableCameras.length === 0}>
              <SelectTrigger className="min-h-11 w-full min-w-0 flex-1 bg-white sm:min-h-9" aria-label="添加已有摄像头">
                <SelectValue placeholder={availableCameras.length ? '选择已有摄像头' : '暂无可添加的摄像头'} />
              </SelectTrigger>
              <SelectContent>{availableCameras.map((camera) => <SelectItem key={camera.camera_id} value={camera.shm_name}>{camera.name}</SelectItem>)}</SelectContent>
            </Select>
            <Button className="h-11 sm:h-9" disabled={readOnly || !cameraToAdd} onClick={() => { if (cameraToAdd) void handleToggle(cameraToAdd, true) }}><Plus className="h-4 w-4" />添加到当前功能</Button>
          </div>
        </div>

        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">已启用当前功能的摄像头</div>
            <div className="mt-1 text-xs font-medium text-slate-500">停用后从列表移除，原有配置保留，可通过上方下拉框重新添加。顺序仅对当前功能生效。</div>
          </div>
          {enabledCameras.length === 0 ? <div className="px-4 py-5 text-sm text-slate-500">尚未添加摄像头到当前功能</div> : enabledCameras.map((camera, index) => {
            const active = camera.shm_name === currentCameraName
            return (
              <div key={camera.camera_id} className={`flex flex-col gap-3 rounded-xl border p-3 transition dark:border-slate-800 sm:flex-row sm:flex-wrap sm:items-center sm:gap-2 ${active ? 'border-blue-200 bg-blue-50/70 dark:bg-blue-950/30' : 'border-[#E8ECF5] bg-white hover:border-blue-200 dark:bg-slate-900'}`}>
                <div className="flex min-w-0 items-start gap-2 sm:flex-1 sm:items-center">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-300"><Camera className="h-4 w-4" /></span>
                  <button type="button" onClick={() => onSelectCamera(camera.shm_name)} disabled={Boolean(workingCamera)} className="min-h-11 min-w-0 flex-1 text-left sm:min-h-0" aria-pressed={active}>
                    <div className="break-words text-sm font-semibold sm:truncate">{camera.name}</div>
                    <div className="break-all font-mono text-xs text-slate-500 sm:truncate">{camera.shm_name}</div>
                    {active ? <span className="text-xs font-semibold text-blue-700 dark:text-blue-300">当前正在编辑</span> : <span className="text-xs text-slate-500">点击切换配置</span>}
                  </button>
                </div>
                <div className="flex flex-col items-start gap-2 sm:contents">
                  <Badge variant="secondary">{camera.enabled ? '摄像头正常' : '摄像头已停用'}</Badge>
                  <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto">
                    <CameraZoomButton camera={camera} feature={feature} disabled={readOnly} />
                    <Button size="sm" variant="outline" className="h-11 sm:h-8" aria-label={`${camera.name}：停用检测`} onClick={() => void handleToggle(camera, false)} disabled={readOnly}>停用</Button>
                    <Button size="sm" variant="outline" className="h-11 sm:h-8" aria-label={`${camera.name}上移`} onClick={() => void handleMove(index, -1)} disabled={readOnly || index === 0}><ArrowUp className="h-4 w-4" />上移</Button>
                    <Button size="sm" variant="outline" className="h-11 sm:h-8" aria-label={`${camera.name}下移`} onClick={() => void handleMove(index, 1)} disabled={readOnly || index === enabledCameras.length - 1}><ArrowDown className="h-4 w-4" />下移</Button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">新建摄像头并加入当前功能</div>
            <div className="mt-1 text-xs font-medium text-slate-500">新摄像头归属当前页面对应的事业部或公司，并在保存后启用当前检测功能。</div>
          </div>
          <Button
            className="h-11 w-full gap-2 sm:h-9 sm:w-auto"
            onClick={() => setCreateDialogOpen(true)}
            disabled={readOnly}
          >
            <Plus className="h-4 w-4" />
            新建摄像头并加入
          </Button>
        </div>

        <div className="space-y-3 rounded-2xl border border-[#E8ECF5] bg-[#FAFBFE] px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">复制当前功能配置</div>
            <div className="mt-1 text-xs font-medium text-slate-500">将一个摄像头的当前功能配置复制到另一个摄像头。</div>
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <Select
              value={copySourceCamera}
              onValueChange={setCopySourceCamera}
              disabled={readOnly || enabledCameras.length === 0}
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
              disabled={readOnly || enabledCameras.length < 2}
            >
              <SelectTrigger className="min-w-0 bg-white">
                <SelectValue placeholder={enabledCameras.length < 2 ? '暂无目标摄像头' : '目标摄像头'} />
              </SelectTrigger>
              <SelectContent>
                {enabledCameras
                  .filter((camera) => camera.shm_name !== copySourceCamera)
                  .map((camera) => (
                    <SelectItem key={camera.id} value={camera.shm_name}>
                      {camera.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Button
              className="h-11 gap-2 sm:h-9"
              onClick={handleCopyConfig}
              disabled={readOnly || !copySourceCamera || !copyTargetCamera || copySourceCamera === copyTargetCamera}
            >
              <Copy className="h-4 w-4" />
              {workingCamera && workingCamera === copyTargetCamera ? '复制中' : '复制配置'}
            </Button>
          </div>
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
