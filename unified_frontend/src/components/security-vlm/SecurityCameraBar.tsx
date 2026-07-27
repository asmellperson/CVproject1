import { Camera, Pencil, Plus, Power, PowerOff, RotateCw, VideoOff } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { SecurityVlmCamera } from '@/lib/security-vlm'

type Props = {
  cameras: SecurityVlmCamera[]
  selectedId?: string
  isAdmin: boolean
  busyId?: string | null
  onSelect: (cameraId: string) => void
  onToggle: (camera: SecurityVlmCamera) => void
  onRestart: (camera: SecurityVlmCamera) => void
  onEdit: (camera: SecurityVlmCamera) => void
  onAdd: () => void
}

export function SecurityCameraBar({
  cameras,
  selectedId,
  isAdmin,
  busyId,
  onSelect,
  onToggle,
  onRestart,
  onEdit,
  onAdd,
}: Props) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cameras.map((camera) => (
        <div
          key={camera.camera_id}
          role="button"
          tabIndex={0}
          className={cn(
            'rounded-xl border bg-white p-4 text-left shadow-sm transition hover:border-blue-300',
            selectedId === camera.camera_id && 'border-blue-500 ring-2 ring-blue-100',
          )}
          onClick={() => onSelect(camera.camera_id)}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return
            if (event.key === 'Enter' || event.key === ' ') onSelect(camera.camera_id)
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Camera className="h-4 w-4 shrink-0 text-slate-500" />
                <span className="truncate font-semibold text-slate-900">{camera.name}</span>
              </div>
            </div>
            <Badge
              variant={camera.running ? 'default' : 'secondary'}
              className={cn(
                camera.running && 'bg-emerald-600',
                camera.desired_running && !camera.running && 'bg-amber-500 text-white',
              )}
            >
              {camera.running
                ? '运行中'
                : camera.desired_running
                  ? '重启中'
                  : camera.last_error
                    ? '异常'
                    : '已停止'}
            </Badge>
          </div>
          <div className="mt-3 flex items-center justify-between gap-2">
            <span className="text-xs text-slate-500">
              {camera.last_error || (camera.running ? '检测与会话处理中' : '未产生 VLM 调用')}
            </span>
            {isAdmin && (
              <span className="flex shrink-0 gap-1" onClick={(event) => event.stopPropagation()}>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  disabled={busyId === camera.camera_id}
                  onClick={() => onToggle(camera)}
                  title={camera.desired_running ? '关闭摄像头' : '开启摄像头'}
                >
                  {camera.desired_running
                    ? <PowerOff className="h-4 w-4" />
                    : <Power className="h-4 w-4" />}
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  disabled={!camera.running || busyId === camera.camera_id}
                  onClick={() => onRestart(camera)}
                  title="重启摄像头"
                >
                  <RotateCw className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  disabled={Boolean(camera.desired_running) || busyId === camera.camera_id}
                  onClick={() => onEdit(camera)}
                  title="编辑摄像头"
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              </span>
            )}
          </div>
        </div>
      ))}
      {cameras.length === 0 && (
        <div className="flex min-h-32 items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-slate-500 sm:col-span-2">
          <VideoOff className="h-5 w-5" />
          尚未添加安检摄像头
        </div>
      )}
      {isAdmin && cameras.length < 4 && (
        <button
          type="button"
          className="flex min-h-32 items-center justify-center gap-2 rounded-xl border border-dashed bg-slate-50 text-sm font-medium text-slate-600 transition hover:border-blue-400 hover:text-blue-700"
          onClick={onAdd}
        >
          <Plus className="h-5 w-5" />
          添加摄像头
        </button>
      )}
    </div>
  )
}
