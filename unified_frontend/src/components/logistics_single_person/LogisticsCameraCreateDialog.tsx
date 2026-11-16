import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import {
  initialLogisticsCameraDraft,
  normalizeLogisticsCameraDraft,
  validateLogisticsCameraDraft,
  type LogisticsCameraCreateInput,
} from './logisticsCameraCreateState'

type Props = {
  onClose: () => void
  onSubmit: (payload: LogisticsCameraCreateInput) => Promise<void>
  title?: string
  description?: string
  submitLabel?: string
}

function messageOf(reason: unknown) {
  return reason instanceof Error ? reason.message : String(reason)
}

export function LogisticsCameraCreateDialog({
  onClose,
  onSubmit,
  title = '新建摄像头并绑定',
  description,
  submitLabel = '新建并绑定',
}: Props) {
  const [draft, setDraft] = useState(initialLogisticsCameraDraft)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const validationError = validateLogisticsCameraDraft(draft)

  const submit = async () => {
    if (validationError) {
      setError(validationError)
      return
    }
    setBusy(true)
    setError('')
    try {
      const payload = normalizeLogisticsCameraDraft(draft)
      await onSubmit(payload)
      onClose()
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => {
      if (!open && !busy) onClose()
    }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className={description ? undefined : 'sr-only'}>{description || '摄像头连接信息'}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="logistics-new-camera-name">摄像头名称</Label>
            <Input
              id="logistics-new-camera-name"
              value={draft.name}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              disabled={busy}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="logistics-new-camera-fps">FPS</Label>
            <Input
              id="logistics-new-camera-fps"
              type="number"
              min="1"
              step="1"
              value={draft.fps}
              onChange={(event) => setDraft((current) => ({ ...current, fps: event.target.value }))}
              disabled={busy}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="logistics-new-camera-url">RTSP 地址</Label>
            <Input
              id="logistics-new-camera-url"
              value={draft.url}
              onChange={(event) => setDraft((current) => ({ ...current, url: event.target.value }))}
              placeholder="rtsp://用户名:密码@地址/stream"
              autoComplete="off"
              disabled={busy}
            />
          </div>
          {error ? (
            <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button type="button" onClick={() => void submit()} disabled={busy || validationError !== null}>
            {busy ? '正在新建' : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
