import { useEffect, useMemo, useState } from 'react'
import { Bell, Camera, Copy, Pencil, Plus, Power, PowerOff, Trash2 } from 'lucide-react'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  createAiVisionCamera,
  deleteAiVisionCamera,
  getAiVisionExceptionAlertSettings,
  getAiVisionFeatureConfig,
  getAiVisionCameraKey,
  type AiVisionCamera,
  isAiVisionFeatureEnabled,
  saveAiVisionExceptionAlertSettings,
  saveAiVisionFeatureConfig,
  updateAiVisionCamera,
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
  const [dialogOpen, setDialogOpen] = useState(false)
  const [cameraAlias, setCameraAlias] = useState('')
  const [rtspUrl, setRtspUrl] = useState('')
  const [exceptionWechatEnabled, setExceptionWechatEnabled] = useState(false)
  const [exceptionWechatUser, setExceptionWechatUser] = useState('')
  const [exceptionSettingsLoading, setExceptionSettingsLoading] = useState(false)
  const [exceptionSettingsSaving, setExceptionSettingsSaving] = useState(false)
  const [exceptionSettingsMessage, setExceptionSettingsMessage] = useState('')
  const [exceptionSettingsError, setExceptionSettingsError] = useState('')
  const [formError, setFormError] = useState('')
  const [workingCamera, setWorkingCamera] = useState('')
  const [selectedExistingCamera, setSelectedExistingCamera] = useState('')
  const [renameDialogOpen, setRenameDialogOpen] = useState(false)
  const [cameraToRename, setCameraToRename] = useState<AiVisionCamera | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState('')
  const [cameraToDelete, setCameraToDelete] = useState<AiVisionCamera | null>(null)
  const [deleteError, setDeleteError] = useState('')
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

  useEffect(() => {
    setExceptionSettingsLoading(true)
    getAiVisionExceptionAlertSettings()
      .then((settings) => {
        setExceptionWechatEnabled(Boolean(settings.wechat_enable))
        setExceptionWechatUser(settings.wechat_user || '')
      })
      .catch((error) => {
        setExceptionSettingsError(`读取全局异常推送配置失败：${error instanceof Error ? error.message : String(error)}`)
      })
      .finally(() => setExceptionSettingsLoading(false))
  }, [])

  const resetCreateForm = () => {
    setCameraAlias('')
    setRtspUrl('')
    setFormError('')
  }

  const makeShmName = (alias: string) => {
    const base = alias
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
    return `${base || 'camera'}_${Date.now().toString(36)}`
  }

  const handleCreateCamera = async () => {
    const name = cameraAlias.trim()
    const url = rtspUrl.trim()
    if (!name || !url) {
      setFormError('摄像头别名和 RTSP 流地址都不能为空。')
      return
    }

    const shmName = makeShmName(name)
    setWorkingCamera(shmName)
    setFormError('')
    try {
      const camera = await createAiVisionCamera({
        name,
        url,
        shm_name: shmName,
        enabled: true,
      })
      await onAddCamera(camera.shm_name)
      window.dispatchEvent(new Event('aivision:cameras-changed'))
      resetCreateForm()
      setDialogOpen(false)
    } catch (error) {
      setFormError(`添加失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setWorkingCamera('')
    }
  }

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

  const openRenameDialog = (camera: AiVisionCamera) => {
    setCameraToRename(camera)
    setRenameValue(camera.name)
    setRenameError('')
    setRenameDialogOpen(true)
  }

  const handleRenameCamera = async () => {
    if (!cameraToRename) return

    const nextName = renameValue.trim()
    if (!nextName) {
      setRenameError('摄像头名称不能为空。')
      return
    }

    const cameraKey = getAiVisionCameraKey(cameraToRename)
    setWorkingCamera(cameraKey)
    setRenameError('')
    try {
      await updateAiVisionCamera(cameraKey, { name: nextName })
      setRenameDialogOpen(false)
      setCameraToRename(null)
    } catch (error) {
      setRenameError(`改名失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setWorkingCamera('')
    }
  }

  const handleSaveExceptionSettings = async () => {
    if (exceptionWechatEnabled && !exceptionWechatUser.trim()) {
      setExceptionSettingsError('启用全局异常推送时，接收人不能为空。')
      setExceptionSettingsMessage('')
      return
    }

    setExceptionSettingsSaving(true)
    setExceptionSettingsError('')
    setExceptionSettingsMessage('')
    try {
      const next = await saveAiVisionExceptionAlertSettings({
        wechat_enable: exceptionWechatEnabled,
        wechat_user: exceptionWechatUser.trim(),
      })
      setExceptionWechatEnabled(Boolean(next.wechat_enable))
      setExceptionWechatUser(next.wechat_user || '')
      setExceptionSettingsMessage('全局异常推送配置已保存。')
    } catch (error) {
      setExceptionSettingsError(`保存全局异常推送配置失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setExceptionSettingsSaving(false)
    }
  }

  const openDeleteDialog = (camera: AiVisionCamera) => {
    setCameraToDelete(camera)
    setDeleteError('')
  }

  const handleDeleteCamera = async () => {
    if (!cameraToDelete) return

    const cameraKey = getAiVisionCameraKey(cameraToDelete)
    setWorkingCamera(cameraKey)
    setDeleteError('')
    try {
      await deleteAiVisionCamera(cameraKey)
      setCameraToDelete(null)
    } catch (error) {
      setDeleteError(`删除失败：${error instanceof Error ? error.message : String(error)}`)
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
      <CardHeader className="border-b border-slate-100 bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_100%)] dark:border-slate-800 dark:bg-slate-900">
        <CardTitle className="flex items-center gap-3 text-lg font-black text-[#071d3d] dark:text-slate-100">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#001b43] text-white shadow-[0_12px_24px_rgba(0,27,67,0.22)] dark:bg-blue-600">
            <Camera className="h-5 w-5" />
          </span>
          摄像头管理
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 bg-[#f8fbff] p-4 sm:p-5 dark:bg-slate-950/30">
        <div className="space-y-3 rounded-2xl border border-amber-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold text-[#071d3d] dark:text-slate-100">
                <Bell className="h-4 w-4 text-amber-600" />
                全局异常推送
              </div>
              <div className="mt-1 text-xs font-medium text-slate-500">摄像头断流、功能异常、模型 Worker 退出等系统异常统一推送。</div>
            </div>
            <Switch
              checked={exceptionWechatEnabled}
              onCheckedChange={setExceptionWechatEnabled}
              disabled={disabled || exceptionSettingsLoading || exceptionSettingsSaving}
            />
          </div>
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <Input
              value={exceptionWechatUser}
              onChange={(event) => setExceptionWechatUser(event.target.value)}
              placeholder="多个接收人用 | 分隔，例如 zhangsan|lisi；也可填 @all"
              disabled={disabled || exceptionSettingsLoading || exceptionSettingsSaving || !exceptionWechatEnabled}
            />
            <Button
              className="gap-2"
              onClick={handleSaveExceptionSettings}
              disabled={disabled || exceptionSettingsLoading || exceptionSettingsSaving}
            >
              <Bell className="h-4 w-4" />
              {exceptionSettingsSaving ? '保存中' : '保存'}
            </Button>
          </div>
          {exceptionSettingsError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{exceptionSettingsError}</div> : null}
          {exceptionSettingsMessage ? <div className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{exceptionSettingsMessage}</div> : null}
        </div>

        <div className="space-y-3 rounded-2xl border border-blue-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">启用已有摄像头</div>
            <div className="mt-1 text-xs font-medium text-slate-500">从全局摄像头列表中选择，并启用当前功能。</div>
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
              启用
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-blue-100 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
          <div>
            <div className="text-sm font-bold text-[#071d3d] dark:text-slate-100">新增摄像头</div>
            <div className="mt-1 text-xs font-medium text-slate-500">写入新的摄像头别名和 RTSP 流地址，添加后自动启用当前功能。</div>
          </div>
          <Button className="gap-2" onClick={() => setDialogOpen(true)} disabled={disabled || Boolean(workingCamera)}>
            <Plus className="h-4 w-4" />
            新增摄像头
          </Button>
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

        <div className="space-y-2">
          <Label>全部摄像头</Label>
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
            {cameras.length === 0 ? (
              <div className="px-4 py-5 text-sm text-slate-500">暂无摄像头。</div>
            ) : (
              cameras.map((camera) => {
                const active = camera.shm_name === currentCameraName
                const featureEnabled = isAiVisionFeatureEnabled(camera, feature)
                const cameraKey = getAiVisionCameraKey(camera)
                return (
                  <div
                    key={camera.id}
                    className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 transition hover:bg-blue-50/60 last:border-b-0 dark:border-slate-800 dark:hover:bg-slate-800/60"
                  >
                    <button
                      type="button"
                      onClick={() => onSelectCamera(camera.shm_name)}
                      className="min-w-0 text-left"
                      disabled={disabled}
                    >
                      <div className="truncate text-sm font-bold text-[#071d3d] dark:text-slate-100">{camera.name}</div>
                      <div className="truncate text-xs text-slate-500">
                        {camera.shm_name}
                        {active ? ' · 当前正在编辑' : ''}
                        {featureEnabled ? ' · 当前功能已启用' : ' · 当前功能未启用'}
                      </div>
                    </button>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-2"
                        onClick={() => openRenameDialog(camera)}
                        disabled={disabled || Boolean(workingCamera)}
                      >
                        <Pencil className="h-4 w-4" />
                        设置
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        className="gap-2"
                        onClick={() => openDeleteDialog(camera)}
                        disabled={disabled || Boolean(workingCamera)}
                      >
                        <Trash2 className="h-4 w-4" />
                        删除
                      </Button>
                    </div>
                    {workingCamera === cameraKey ? (
                      <div className="basis-full text-xs text-slate-500">正在处理该摄像头...</div>
                    ) : null}
                  </div>
                )
              })
            )}
          </div>
        </div>

        <div className="space-y-2">
          <Label>已启用当前功能的摄像头</Label>
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
            {enabledCameras.length === 0 ? (
              <div className="px-4 py-5 text-sm text-slate-500">暂无摄像头启用当前功能。</div>
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
                      停用
                    </Button>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </CardContent>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open)
          if (!open) resetCreateForm()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新增摄像头</DialogTitle>
            <DialogDescription>新增摄像头会写入数据库，并立即启用当前功能。</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`${feature}-camera-alias`}>摄像头别名</Label>
              <Input
                id={`${feature}-camera-alias`}
                value={cameraAlias}
                onChange={(event) => setCameraAlias(event.target.value)}
                placeholder="例如：一号门摄像头"
                disabled={Boolean(workingCamera)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${feature}-camera-rtsp`}>RTSP 流地址</Label>
              <Input
                id={`${feature}-camera-rtsp`}
                value={rtspUrl}
                onChange={(event) => setRtspUrl(event.target.value)}
                placeholder="rtsp://user:password@host:554/stream"
                disabled={Boolean(workingCamera)}
              />
            </div>
            {formError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</div> : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={Boolean(workingCamera)}>
              取消
            </Button>
            <Button className="gap-2" onClick={handleCreateCamera} disabled={Boolean(workingCamera)}>
              <Plus className="h-4 w-4" />
              {workingCamera ? '添加中' : '添加'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={renameDialogOpen}
        onOpenChange={(open) => {
          setRenameDialogOpen(open)
          if (!open) {
            setCameraToRename(null)
            setRenameValue('')
            setRenameError('')
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>摄像头设置</DialogTitle>
            <DialogDescription>摄像头标识和 RTSP 地址保持不变。</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor={`${feature}-rename-camera`}>摄像头名称</Label>
              <Input
                id={`${feature}-rename-camera`}
                value={renameValue}
                onChange={(event) => setRenameValue(event.target.value)}
                disabled={Boolean(workingCamera)}
              />
            </div>
            {renameError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{renameError}</div> : null}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameDialogOpen(false)} disabled={Boolean(workingCamera)}>
              取消
            </Button>
            <Button className="gap-2" onClick={handleRenameCamera} disabled={Boolean(workingCamera)}>
              <Pencil className="h-4 w-4" />
              {workingCamera ? '保存中' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={Boolean(cameraToDelete)}
        onOpenChange={(open) => {
          if (!open && !workingCamera) {
            setCameraToDelete(null)
            setDeleteError('')
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除摄像头</AlertDialogTitle>
            <AlertDialogDescription>
              删除后会从数据库移除 {cameraToDelete?.name || '该摄像头'}，并清理它在所有算法里的配置。
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{deleteError}</div> : null}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={Boolean(workingCamera)}>取消</AlertDialogCancel>
            <Button variant="destructive" className="gap-2" onClick={handleDeleteCamera} disabled={Boolean(workingCamera)}>
              <Trash2 className="h-4 w-4" />
              {workingCamera ? '删除中' : '删除'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
