import { useCallback, useImperativeHandle, useLayoutEffect, useRef } from 'react'
import { Pause } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  securityVlmCameraVideoUrl,
  type SecurityVlmCamera,
  type SecurityVlmDepartment,
} from '@/lib/security-vlm'

type Props = {
  department: SecurityVlmDepartment
  cameras: SecurityVlmCamera[]
  cameraId?: string
  kind?: 'original' | 'rule'
  nonce: number
  onCameraChange: (cameraId: string) => void
  selectable?: boolean
  imageRef?: React.Ref<HTMLImageElement>
  onLoad?: React.ReactEventHandler<HTMLImageElement>
}

export function SecurityVideoPanel({
  department,
  cameras,
  cameraId,
  kind = 'rule',
  nonce,
  onCameraChange,
  selectable = true,
  imageRef,
  onLoad,
}: Props) {
  const camera = cameras.find((item) => item.camera_id === cameraId)
  const streamImageRef = useRef<HTMLImageElement | null>(null)
  const setStreamImageRef = useCallback((node: HTMLImageElement | null) => {
    streamImageRef.current = node
  }, [])
  useImperativeHandle(imageRef, () => streamImageRef.current as HTMLImageElement)

  const streamUrl = camera?.running
    ? securityVlmCameraVideoUrl(department, camera.camera_id, kind, nonce)
    : ''

  useLayoutEffect(() => {
    const image = streamImageRef.current
    if (!image || !streamUrl) return
    image.src = streamUrl
    return () => {
      image.removeAttribute('src')
    }
  }, [streamUrl])

  return (
    <div className="overflow-hidden rounded-lg border bg-slate-950">
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 bg-slate-900 px-3 py-2">
        {selectable ? (
          <Select value={cameraId} onValueChange={onCameraChange}>
            <SelectTrigger className="h-8 w-full max-w-64 border-slate-700 bg-slate-800 text-slate-100">
              <SelectValue placeholder="选择摄像头" />
            </SelectTrigger>
            <SelectContent>
              {cameras.map((item) => (
                <SelectItem key={item.camera_id} value={item.camera_id}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="truncate text-sm font-medium text-slate-100">
            {camera?.name || '暂无摄像头'}
          </span>
        )}
        <span className="shrink-0 text-xs text-slate-400">
          {camera?.running ? '实时' : '已停止'}
        </span>
      </div>
      <div className="aspect-video">
        {camera?.running ? (
          <img
            ref={setStreamImageRef}
            alt={`${camera.name}实时画面`}
            className="h-full w-full select-none object-contain"
            draggable={false}
            onLoad={onLoad}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
            <Pause className="h-8 w-8" />
            <span className="text-sm">{camera ? '该摄像头检测已关闭' : '请选择摄像头'}</span>
          </div>
        )}
      </div>
    </div>
  )
}
