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
import type { SecurityVlmCamera } from '@/lib/security-vlm'

type Props = {
  camera?: SecurityVlmCamera | null
  onClose: () => void
  onSave: (name: string, rtspUrl: string) => Promise<void>
  onTest: (rtspUrl: string) => Promise<string>
  onDelete?: () => Promise<void>
}

export function SecurityCameraDialog({
  camera,
  onClose,
  onSave,
  onTest,
  onDelete,
}: Props) {
  const [name, setName] = useState(camera?.name || '')
  const [rtspUrl, setRtspUrl] = useState(camera?.rtsp_url || '')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (operation: () => Promise<void>) => {
    setBusy(true)
    setMessage('')
    try {
      await operation()
    } catch (error) {
      console.error('[SecurityCameraDialog] 摄像头操作失败', error)
      setMessage(`操作失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{camera ? '编辑安检摄像头' : '添加安检摄像头'}</DialogTitle>
          <DialogDescription>填写摄像头名称和 RTSP 地址，最多可配置 4 台。</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="security-camera-name">摄像头名称</Label>
            <Input
              id="security-camera-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：安检工位一号"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="security-camera-rtsp">RTSP 地址</Label>
            <Input
              id="security-camera-rtsp"
              type="text"
              autoComplete="off"
              value={rtspUrl}
              onChange={(event) => setRtspUrl(event.target.value)}
              placeholder="rtsp://用户名:密码@地址/stream"
            />
          </div>
          {message && <p className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">{message}</p>}
        </div>
        <DialogFooter className="sm:justify-between">
          <div>
            {camera && onDelete && (
              <Button
                type="button"
                variant="destructive"
                disabled={busy}
                onClick={() => {
                  if (window.confirm(`确定删除“${camera.name}”吗？ROI 文件会保留。`)) {
                    void run(onDelete)
                  }
                }}
              >
                删除
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy || !rtspUrl.trim()}
              onClick={() => void run(async () => setMessage(await onTest(rtspUrl.trim())))}
            >
              测试连接
            </Button>
            <Button
              type="button"
              disabled={busy || !name.trim() || (!camera && !rtspUrl.trim())}
              onClick={() => void run(() => onSave(name.trim(), rtspUrl.trim()))}
            >
              {busy ? '处理中' : '保存'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
