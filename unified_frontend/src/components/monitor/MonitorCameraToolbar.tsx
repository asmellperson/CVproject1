import { useId } from 'react'
import { Camera, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getAiVisionCameraKey, type AiVisionCamera } from '@/lib/aivision'

type Props = {
  cameras: AiVisionCamera[]
  selectedCamera: string
  loading?: boolean
  onSelectCamera: (key: string) => void
  onRefreshCameras: () => void | Promise<void>
}

export function MonitorCameraToolbar({ cameras, selectedCamera, loading, onSelectCamera, onRefreshCameras }: Props) {
  const fieldId = useId()
  return <div className="flex min-w-0 items-center gap-2 border-b border-slate-100 bg-white p-3 dark:border-slate-800 dark:bg-slate-900 sm:px-5">
    <Label htmlFor={fieldId} className="sr-only">监控摄像头</Label>
    <Select value={selectedCamera} onValueChange={onSelectCamera} disabled={loading || !cameras.length}>
      <SelectTrigger id={fieldId} aria-label="监控摄像头" className="h-11 min-h-11 min-w-0 flex-1 rounded-xl border-slate-200 bg-slate-50 text-sm [&>span]:min-w-0 [&>span]:flex-1 [&>span]:truncate [&>span]:text-left dark:border-slate-700 dark:bg-slate-950/60">
        <Camera className="h-4 w-4 shrink-0 text-slate-500" />
        <SelectValue placeholder={loading ? '正在读取摄像头…' : '选择摄像头'} />
      </SelectTrigger>
      <SelectContent position="popper" className="w-[var(--radix-select-trigger-width)] max-w-[calc(100vw-1.5rem)]">
        {cameras.map((camera) => <SelectItem key={camera.camera_id} value={getAiVisionCameraKey(camera)} className="min-h-11 whitespace-normal py-2.5">
          <span className="break-words">{camera.name}{!camera.enabled ? '（已停用）' : ''}</span>
        </SelectItem>)}
      </SelectContent>
    </Select>
    <Button type="button" variant="outline" className="h-11 w-11 shrink-0 rounded-xl" disabled={loading}
      onClick={() => { void onRefreshCameras() }} aria-label="刷新摄像头" title="刷新摄像头">
      <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
    </Button>
  </div>
}
